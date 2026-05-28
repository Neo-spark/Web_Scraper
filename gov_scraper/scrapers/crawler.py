"""
Sampark Setu - Async Government Website Crawler
------------------------------------------------
Crawls .gov.in / .nic.in domains, extracts contacts, officers and org info,
stores everything in PostgreSQL with proper relationships.

Usage:
    python scrapers/crawler.py                           # default 500 pages
    python scrapers/crawler.py --max-pages 0             # UNLIMITED
    python scrapers/crawler.py --max-pages 5000          # 5000 pages
    python scrapers/crawler.py --seed seeds/gov_seeds.txt --concurrency 15
"""

import asyncio
import aiohttp
import argparse
import hashlib
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse
from typing import Optional

from bs4 import BeautifulSoup
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv

# Load env variables early
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import (
    get_engine, get_session,
    State, District, Category, Organization, Officer, Contact,
    CrawlJob, CrawlURL
)
from extractors.extractors import (
    extract_emails, extract_phones, extract_officers,
    extract_org_from_page, classify_category, content_hash
)

# ─── Logging ──────────────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/crawler.log", mode="a", encoding="utf-8"),
    ]
)
log = logging.getLogger("crawler")

# ─── Config ───────────────────────────────────────────────────────────────────
CONCURRENCY     = 12
REQUEST_TIMEOUT = 25
DELAY_PER_DOMAIN = 0.4    # seconds between requests to same domain
MAX_DEPTH       = 4       # follow links this many levels deep
MAX_RETRIES     = 3

ALLOWED_TLDS = re.compile(
    r'\.(gov\.in|nic\.in|ac\.in|res\.in|org\.in|edu\.in|co\.in)$',
    re.IGNORECASE
)

SKIP_EXT = {
    ".jpg",".jpeg",".png",".gif",".svg",".ico",".webp",
    ".css",".js",".woff",".woff2",".ttf",".eot",
    ".mp4",".mp3",".avi",".zip",".rar",".tar",".gz",
    ".xls",".xlsx",".ppt",".pptx",".doc",".docx",
}

# Contact/directory pages get highest priority
HIGH_PRIORITY_KEYWORDS = [
    "contact", "contactus", "contact-us", "contacts",
    "directory", "officer", "officers", "staff", "personnel",
    "grievance", "helpdesk", "feedback", "complaint",
    "about", "aboutus", "team", "management",
]
MEDIUM_PRIORITY_KEYWORDS = [
    "department", "scheme", "service", "district",
    "phone", "email", "address", "locate",
]
LOW_PRIORITY_KEYWORDS = [
    "gallery", "photo", "news", "media", "event",
    "tender", "career", "recruitment", "admit", "result",
    "archive", "annual-report", "budget",
]

def score_url(url: str) -> int:
    """Lower returned score = crawled sooner (used as queue priority)."""
    lower = url.lower()
    for kw in HIGH_PRIORITY_KEYWORDS:
        if kw in lower:
            return 0        # crawl first
    for kw in MEDIUM_PRIORITY_KEYWORDS:
        if kw in lower:
            return 30
    if lower.endswith(".pdf"):
        return 20           # PDFs often have phone directories
    for kw in LOW_PRIORITY_KEYWORDS:
        if kw in lower:
            return 90
    return 50


def normalize_url(url: str) -> str:
    """Strip trailing slash, fragment, and tracking params."""
    p = urlparse(url)
    clean = urlunparse((p.scheme, p.netloc, p.path.rstrip("/"), "", "", ""))
    return clean


# ─── Lookup Tables ────────────────────────────────────────────────────────────

class LookupCache:
    def __init__(self, session):
        self.session = session
        self._states     = {s.name.lower(): s  for s in session.query(State).all()}
        self._state_code = {s.code.lower(): s  for s in session.query(State).all()}
        self._categories = {c.slug: c          for c in session.query(Category).all()}
        self._orgs: dict[str, int] = {}
        log.info(f"Cache: {len(self._states)} states, {len(self._categories)} categories")

    def get_state(self, hint: str) -> Optional[State]:
        if not hint:
            return None
        key = hint.lower().strip()
        return self._states.get(key) or self._state_code.get(key)

    def get_category(self, slug: str) -> Optional[Category]:
        return self._categories.get(slug)

    def get_or_create_org(self, name: str, data: dict) -> Optional[Organization]:
        if not name or len(name.strip()) < 3:
            return None
        norm = name.lower().strip()[:299]
        if norm in self._orgs:
            return self.session.get(Organization, self._orgs[norm])
        existing = (self.session.query(Organization)
                    .filter(Organization.name_normalized == norm).first())
        if existing:
            self._orgs[norm] = existing.id
            return existing
        org = Organization(
            name=name[:300], name_normalized=norm,
            org_type=data.get("org_type", "department"),
            level=data.get("level", "central"),
            state_id=data.get("state_id"),
            category_id=data.get("category_id"),
            website=data.get("website"),
            source_url=data.get("source_url"),
        )
        self.session.add(org)
        try:
            self.session.flush()
            self._orgs[norm] = org.id
        except IntegrityError:
            self.session.rollback()
            existing = (self.session.query(Organization)
                        .filter(Organization.name_normalized == norm).first())
            if existing:
                self._orgs[norm] = existing.id
                return existing
        return org


# ─── Main Crawler ─────────────────────────────────────────────────────────────

class GovCrawler:
    def __init__(self, db_url: str, max_pages: int = 500, concurrency: int = CONCURRENCY):
        self.engine      = get_engine(db_url)
        self.session     = get_session(self.engine)
        self.cache       = LookupCache(self.session)
        self.max_pages   = max_pages   # 0 = unlimited
        self.concurrency = concurrency

        self.visited: set[str] = set()
        self.queue = asyncio.PriorityQueue()   # (priority, depth, url)
        self.domain_last: dict[str, float] = {}

        self.pages_crawled  = 0
        self.contacts_saved = 0
        self.job: Optional[CrawlJob] = None

    # ── Helpers ────────────────────────────────────────────────────────────

    @property
    def _under_limit(self) -> bool:
        return self.max_pages == 0 or self.pages_crawled < self.max_pages

    def _load_visited(self):
        done = (self.session.query(CrawlURL.url)
                .filter(CrawlURL.status.in_(["crawled", "skipped"])).all())
        self.visited = {r.url for r in done}
        # Also mark failed URLs as visited to avoid infinite retry
        failed = (self.session.query(CrawlURL.url)
                  .filter(CrawlURL.status == "failed").all())
        self.visited.update(r.url for r in failed)
        log.info(f"Loaded {len(self.visited)} already-visited URLs from DB")

    def _enqueue(self, url: str, depth: int):
        url = normalize_url(url)
        if url and url not in self.visited:
            self.queue.put_nowait((score_url(url), depth, url))

    def _save_url_record(self, url, status, status_code=None, contacts=0, error=None):
        try:
            ex = self.session.query(CrawlURL).filter_by(url=url).first()
            if ex:
                ex.status = status
                ex.status_code = status_code
                ex.contacts_found = contacts
                ex.error = error
                ex.crawled_at = datetime.utcnow()
            else:
                self.session.add(CrawlURL(
                    job_id=self.job.id if self.job else None,
                    url=url[:1000], domain=urlparse(url).netloc,
                    status=status, status_code=status_code,
                    contacts_found=contacts, error=error,
                    crawled_at=datetime.utcnow(),
                ))
            self.session.commit()
        except Exception:
            self.session.rollback()

    # ── Network ────────────────────────────────────────────────────────────

    async def _delay(self, domain: str):
        now = time.monotonic()
        wait = DELAY_PER_DOMAIN - (now - self.domain_last.get(domain, 0))
        if wait > 0:
            await asyncio.sleep(wait)
        self.domain_last[domain] = time.monotonic()

    async def _fetch(self, http: aiohttp.ClientSession, url: str) -> tuple[Optional[str], int]:
        domain = urlparse(url).netloc
        await self._delay(domain)
        for attempt in range(MAX_RETRIES):
            try:
                async with http.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                    allow_redirects=True, ssl=False
                ) as resp:
                    if resp.status == 200:
                        ct = resp.headers.get("Content-Type", "")
                        if "html" in ct or "xhtml" in ct:
                            return await resp.text(errors="replace"), 200
                        return None, 200      # non-HTML (PDF handled separately)
                    if resp.status in (429, 503, 504):
                        await asyncio.sleep(2 ** attempt + 0.5 * attempt)
                        continue
                    return None, resp.status
            except asyncio.TimeoutError:
                log.debug(f"Timeout ({attempt+1}): {url}")
                await asyncio.sleep(1)
            except Exception as e:
                log.debug(f"Error ({attempt+1}) {url}: {type(e).__name__}")
                await asyncio.sleep(0.5)
        return None, 0

    # ── Parsing ────────────────────────────────────────────────────────────

    def _allowed(self, url: str) -> bool:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False
        if Path(p.path).suffix.lower() in SKIP_EXT:
            return False
        return bool(ALLOWED_TLDS.search(p.netloc.lower()))

    def _links(self, html: str, base: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            full = normalize_url(urljoin(base, href))
            if self._allowed(full):
                links.append(full)
        return links

    # ── DB save ────────────────────────────────────────────────────────────

    def _save_contacts(self, raw_contacts, org, state_id, district_id,
                        category_id, source_url, title, c_hash) -> int:
        saved = 0
        for c in raw_contacts:
            try:
                ex = (self.session.query(Contact)
                      .filter_by(contact_type=c["contact_type"],
                                 value=c["value"],
                                 org_id=org.id if org else None).first())
                if ex:
                    continue
                self.session.add(Contact(
                    contact_type=c["contact_type"],
                    value=c["value"][:300],
                    label=(c.get("label") or "")[:200] or None,
                    org_id=org.id if org else None,
                    level=org.level if org else "central",
                    state_id=state_id, district_id=district_id,
                    category_id=category_id,
                    confidence=c.get("confidence", 0.5),
                    source_url=source_url[:500],
                    page_title=(title or "")[:300] or None,
                    domain=urlparse(source_url).netloc[:200],
                    content_hash=c_hash, source_type="web",
                ))
                saved += 1
            except IntegrityError:
                self.session.rollback()
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
        return saved

    def _save_officers(self, raw_officers, org, state_id, source_url):
        for o in raw_officers:
            try:
                ex = (self.session.query(Officer)
                      .filter_by(name=o["name"], designation=o["designation"],
                                 org_id=org.id if org else None).first())
                if not ex:
                    self.session.add(Officer(
                        name=o["name"][:200],
                        designation=o["designation"][:300],
                        cadre=o.get("cadre"),
                        org_id=org.id if org else None,
                        state_id=state_id,
                        source_url=source_url[:500],
                    ))
            except Exception:
                self.session.rollback()
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()

    # ── Page process ───────────────────────────────────────────────────────

    async def _process(self, html: str, url: str, depth: int) -> tuple[int, list[str]]:
        soup  = BeautifulSoup(html, "lxml")
        text  = soup.get_text(" ", strip=True)
        title = (soup.find("title") or soup.new_tag("x")).get_text(strip=True)
        c_hash = content_hash(text[:5000])

        org_info  = extract_org_from_page(url, title, text)
        cat_slug  = classify_category(url, title, text)
        category  = self.cache.get_category(cat_slug) if cat_slug else None

        state_id = None
        if org_info.get("detected_state"):
            s = self.cache.get_state(org_info["detected_state"])
            if s:
                state_id = s.id

        org = self.cache.get_or_create_org(org_info["name"], {
            "org_type":    org_info.get("org_type", "department"),
            "level":       org_info.get("level", "central"),
            "state_id":    state_id,
            "category_id": category.id if category else None,
            "website":     urlparse(url)._replace(path="", query="", fragment="").geturl(),
            "source_url":  url,
        })

        emails   = extract_emails(text)
        phones   = extract_phones(text)
        officers = extract_officers(text)

        saved = 0
        if emails or phones:
            saved = self._save_contacts(
                emails + phones, org, state_id, None,
                category.id if category else None,
                url, title, c_hash
            )
        if officers:
            self._save_officers(officers, org, state_id, url)

        new_links = self._links(html, url) if depth < MAX_DEPTH else []
        return saved, new_links

    # ── Worker ────────────────────────────────────────────────────────────

    async def _worker(self, http: aiohttp.ClientSession, wid: int):
        while True:
            try:
                priority, depth, url = await asyncio.wait_for(
                    self.queue.get(), timeout=8.0
                )
            except asyncio.TimeoutError:
                break

            if url in self.visited or not self._under_limit:
                self.queue.task_done()
                continue

            self.visited.add(url)
            limit_str = "∞" if self.max_pages == 0 else str(self.max_pages)
            log.info(f"[W{wid:02d}] [{self.pages_crawled}/{limit_str}] "
                     f"[Q:{self.queue.qsize()}] {url}")

            html, code = await self._fetch(http, url)
            saved = 0; error = None

            if html:
                try:
                    saved, new_links = await self._process(html, url, depth)
                    self.contacts_saved += saved
                    self.pages_crawled  += 1

                    for link in new_links:
                        if link not in self.visited and self._under_limit:
                            self._enqueue(link, depth + 1)

                except Exception as e:
                    log.error(f"Processing error {url}: {e}", exc_info=False)
                    error = str(e)[:500]

            status = "crawled" if html and not error else ("failed" if error else "skipped")
            self._save_url_record(url, status, code, saved, error)
            self.queue.task_done()

            # Progress heartbeat every 50 pages
            if self.pages_crawled > 0 and self.pages_crawled % 50 == 0:
                log.info(f"━━ PROGRESS: {self.pages_crawled} pages | "
                         f"{self.contacts_saved} contacts | "
                         f"Queue: {self.queue.qsize()} ━━")

    # ── Run ───────────────────────────────────────────────────────────────

    async def run(self, seed_urls: list[str]):
        self.job = CrawlJob(
            job_name=f"crawl_{datetime.utcnow().strftime('%Y%m%d_%H%M')}",
            urls_total=len(seed_urls),
        )
        self.session.add(self.job)
        self.session.commit()

        self._load_visited()

        new_seeds = [u for u in seed_urls if normalize_url(u) not in self.visited]
        log.info(f"Seeds: {len(seed_urls)} total, {len(new_seeds)} new (not yet visited)")

        for url in seed_urls:           # enqueue ALL seeds, visited check in worker
            self._enqueue(url, depth=0)

        limit_str = "UNLIMITED" if self.max_pages == 0 else str(self.max_pages)
        log.info(f"🚀 Crawl started — limit={limit_str} pages, "
                 f"{self.concurrency} workers, queue={self.queue.qsize()}")

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
        }
        connector = aiohttp.TCPConnector(limit=self.concurrency * 2, ssl=False)
        async with aiohttp.ClientSession(headers=headers, connector=connector) as http:
            workers = [
                asyncio.create_task(self._worker(http, i))
                for i in range(self.concurrency)
            ]
            await asyncio.gather(*workers, return_exceptions=True)

        self.job.finished_at    = datetime.utcnow()
        self.job.status         = "completed"
        self.job.urls_done      = self.pages_crawled
        self.job.contacts_found = self.contacts_saved
        self.session.commit()

        log.info(f"✅ CRAWL COMPLETE — {self.pages_crawled} pages crawled, "
                 f"{self.contacts_saved} new contacts saved")
        return {"pages_crawled": self.pages_crawled, "contacts_saved": self.contacts_saved}


# ─── Entrypoint ───────────────────────────────────────────────────────────────

def load_seeds(path: str) -> list[str]:
    urls = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


async def main():
    parser = argparse.ArgumentParser(description="Sampark Setu Government Crawler")
    parser.add_argument("--max-pages",   type=int, default=500,
                        help="Max pages (0 = unlimited)")
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY)
    parser.add_argument("--seed",        type=str, default="seeds/gov_seeds.txt")
    parser.add_argument("--db",          type=str,
                        default=os.getenv("DATABASE_URL",
                                "postgresql://postgres:yourpassword@localhost:5432/govcontacts"))
    args = parser.parse_args()

    Path("logs").mkdir(exist_ok=True)
    seeds = load_seeds(args.seed)
    log.info(f"Loaded {len(seeds)} seed URLs from {args.seed}")

    crawler = GovCrawler(
        db_url=args.db,
        max_pages=args.max_pages,
        concurrency=args.concurrency,
    )
    await crawler.run(seeds)


if __name__ == "__main__":
    asyncio.run(main())
