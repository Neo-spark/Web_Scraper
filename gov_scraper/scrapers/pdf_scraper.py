"""
PDF Contact Extractor
Handles government PDFs (annual reports, phone directories, circulars).
Uses pdfplumber for text-based PDFs, Tesseract OCR for scanned ones.

Usage:
    python scrapers/pdf_scraper.py --url https://example.gov.in/directory.pdf
    python scrapers/pdf_scraper.py --folder pdfs/
"""

import argparse
import asyncio
import io
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import pdfplumber

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import get_engine, get_session, Contact, Organization, CrawlURL
from extractors.extractors import (
    extract_emails, extract_phones, extract_officers,
    extract_org_from_page, classify_category, content_hash
)

log = logging.getLogger("pdf_scraper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


async def download_pdf(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, ssl=False, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status == 200:
                return await resp.read()
            raise Exception(f"HTTP {resp.status} for {url}")


def extract_text_from_pdf(pdf_bytes: bytes) -> tuple[str, str]:
    """
    Returns (text, source_type) where source_type is 'pdf' or 'pdf_ocr'.
    Tries pdfplumber first; falls back to Tesseract OCR if text is sparse.
    """
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages_text = []
            for page in pdf.pages:
                pt = page.extract_text() or ""
                # Also extract tables
                for table in page.extract_tables():
                    for row in table:
                        if row:
                            pages_text.append(" | ".join(str(c) for c in row if c))
                pages_text.append(pt)
            text = "\n".join(pages_text)
    except Exception as e:
        log.warning(f"pdfplumber failed: {e}")

    # If very little text extracted, try OCR
    if len(text.strip()) < 200:
        try:
            import pytesseract
            from PIL import Image
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                ocr_pages = []
                for page in pdf.pages:
                    img = page.to_image(resolution=200).original
                    ocr_pages.append(pytesseract.image_to_string(img, lang="eng+hin"))
            text = "\n".join(ocr_pages)
            return text, "pdf_ocr"
        except Exception as e:
            log.warning(f"OCR failed: {e}")

    return text, "pdf"


def process_pdf(pdf_bytes: bytes, source_url: str, db_session, org_cache=None) -> int:
    """Extract contacts from PDF bytes and save to DB. Returns count saved."""
    text, source_type = extract_text_from_pdf(pdf_bytes)
    if not text.strip():
        log.warning(f"No text extracted from {source_url}")
        return 0

    c_hash = content_hash(text[:5000])

    # Check duplicate
    existing = db_session.query(CrawlURL).filter_by(url=source_url).first()
    if existing and existing.content_hash == c_hash:
        log.info(f"PDF unchanged, skipping: {source_url}")
        return 0

    # Detect org / category
    domain = urlparse(source_url).netloc
    title = Path(urlparse(source_url).path).stem.replace("-", " ").replace("_", " ").title()
    org_info = extract_org_from_page(source_url, title, text)
    category_slug = classify_category(source_url, title, text)

    emails  = extract_emails(text)
    phones  = extract_phones(text)
    all_contacts = emails + phones

    if not all_contacts:
        return 0

    # Get/create org
    org = None
    if org_cache:
        org = org_cache.get_or_create_org(org_info["name"], {
            "org_type":   org_info.get("org_type", "department"),
            "level":      org_info.get("level", "central"),
            "source_url": source_url,
        })

    saved = 0
    for c in all_contacts:
        # Check duplicate
        exists = db_session.query(Contact).filter_by(
            contact_type=c["contact_type"],
            value=c["value"],
            org_id=org.id if org else None
        ).first()
        if exists:
            continue

        contact = Contact(
            contact_type=c["contact_type"],
            value=c["value"][:300],
            label=c.get("label", "")[:200] if c.get("label") else None,
            org_id=org.id if org else None,
            level=org_info.get("level", "central"),
            confidence=c.get("confidence", 0.6),
            source_url=source_url[:500],
            source_type=source_type,
            domain=domain[:200],
            content_hash=c_hash,
            page_title=title[:300],
        )
        db_session.add(contact)
        saved += 1

    try:
        db_session.commit()
        log.info(f"PDF: saved {saved} contacts from {source_url}")
    except Exception as e:
        db_session.rollback()
        log.error(f"DB error: {e}")

    return saved


async def process_pdf_url(url: str, db_url: str):
    engine = get_engine(db_url)
    session = get_session(engine)
    try:
        log.info(f"Downloading PDF: {url}")
        pdf_bytes = await download_pdf(url)
        count = process_pdf(pdf_bytes, url, session)
        print(f"✅ Saved {count} contacts from {url}")
    finally:
        session.close()


def process_pdf_folder(folder: str, db_url: str):
    """Process all PDFs in a local folder."""
    engine = get_engine(db_url)
    session = get_session(engine)
    total = 0
    for pdf_path in Path(folder).glob("**/*.pdf"):
        try:
            pdf_bytes = pdf_path.read_bytes()
            source_url = f"file://{pdf_path.resolve()}"
            count = process_pdf(pdf_bytes, source_url, session)
            total += count
            print(f"  {pdf_path.name}: {count} contacts")
        except Exception as e:
            log.error(f"Error processing {pdf_path}: {e}")
    session.close()
    print(f"\n✅ Total: {total} contacts from {folder}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url",    help="PDF URL to process")
    parser.add_argument("--folder", help="Local folder with PDFs")
    parser.add_argument("--db",     default=os.getenv("DATABASE_URL",
                                    "postgresql://postgres:password@localhost:5432/govcontacts"))
    args = parser.parse_args()

    if args.url:
        asyncio.run(process_pdf_url(args.url, args.db))
    elif args.folder:
        process_pdf_folder(args.folder, args.db)
    else:
        print("Provide --url or --folder")
