"""
Extractors: pull structured data (emails, phones, org names, officer names)
from raw HTML text scraped from government websites.
"""

import re
import hashlib
from urllib.parse import urlparse
from typing import Optional
from rapidfuzz import fuzz

# ─── Regex Patterns ───────────────────────────────────────────────────────────

EMAIL_RE = re.compile(
    r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'
)

PHONE_RE = re.compile(
    r'(?:'
    r'\+?91[\s\-]?'       # optional +91 country code
    r')?'
    r'(?:'
    r'0\d{2,4}[\s\-]?\d{6,8}'  # STD: 0532-2234567
    r'|'
    r'[6-9]\d{9}'               # mobile: 9876543210
    r'|'
    r'1[89]00[\s\-]?\d{6,7}'    # toll-free: 1800-xxx
    r')'
)

FAX_RE = re.compile(
    r'[Ff]ax[\s:]+(' + PHONE_RE.pattern + r')'
)

OFFICER_TITLES = [
    r"(?:Secretary|Secy\.?)",
    r"(?:Joint\s+Secretary|JS)",
    r"(?:Additional\s+Secretary|Addl\.\s+Secy\.?)",
    r"(?:Under\s+Secretary|US)",
    r"(?:Director\s+General|DG)",
    r"(?:Director)",
    r"(?:Commissioner)",
    r"(?:Superintendent)",
    r"(?:Collector|District\s+Magistrate|DM)",
    r"(?:Chief\s+Medical\s+Officer|CMO)",
    r"(?:Chief\s+Engineer|CE)",
    r"(?:Executive\s+Engineer|EE)",
    r"(?:Divisional\s+Commissioner)",
    r"(?:Inspector\s+General|IG)",
    r"(?:Deputy\s+Inspector\s+General|DIG)",
    r"(?:Superintendent\s+of\s+Police|SP)",
    r"(?:District\s+Education\s+Officer|DEO)",
    r"(?:Block\s+Education\s+Officer|BEO)",
    r"(?:Chief\s+Development\s+Officer|CDO)",
    r"(?:Project\s+Director)",
    r"(?:Mission\s+Director|MD)",
    r"(?:Managing\s+Director)",
    r"(?:Deputy\s+Commissioner|DC)",
    r"(?:Tehsildar)",
    r"(?:Block\s+Development\s+Officer|BDO)",
]

OFFICER_RE = re.compile(
    r'(?P<title>' + '|'.join(OFFICER_TITLES) + r')'
    r'[\s,:\-–]+(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z\.]+){1,4})'
    r'(?:\s*,\s*(?P<cadre>IAS|IPS|IFS|IAAS|IRTS|IRS))?',
    re.IGNORECASE
)

# ─── Garbage filters ──────────────────────────────────────────────────────────

FAKE_EMAILS = {
    "example@example.com", "test@test.com", "email@email.com",
    "info@example.com", "admin@example.com", "user@domain.com",
    "noreply@noreply.com", "webmaster@website.com",
}

FAKE_PHONES = {"0000000000", "1234567890", "9999999999", "1111111111"}

MIN_CONFIDENCE = 0.3


# ─── Extractors ───────────────────────────────────────────────────────────────

def extract_emails(text: str) -> list[dict]:
    """Extract and validate email addresses from text."""
    results = []
    seen = set()
    for m in EMAIL_RE.finditer(text):
        email = m.group().lower().strip()
        if email in seen or email in FAKE_EMAILS:
            continue
        if not email.endswith((".gov.in", ".nic.in", ".ac.in", ".org.in",
                                ".gov", ".edu", ".org")):
            # Still include but lower confidence
            conf = 0.4
        else:
            conf = 0.9 if ".gov.in" in email or ".nic.in" in email else 0.7

        # Extract label from surrounding context (50 chars before)
        start = max(0, m.start() - 80)
        context = text[start:m.start()].strip()
        label = _extract_label_from_context(context)

        results.append({
            "contact_type": "email",
            "value": email,
            "label": label,
            "confidence": conf,
        })
        seen.add(email)
    return results


def extract_phones(text: str) -> list[dict]:
    """Extract and validate phone numbers from text."""
    results = []
    seen = set()

    for m in PHONE_RE.finditer(text):
        raw = m.group()
        # Normalize: remove spaces, dashes
        normalized = re.sub(r'[\s\-]', '', raw)
        if normalized in seen or normalized in FAKE_PHONES:
            continue
        if len(normalized.replace("+91", "")) < 8:
            continue

        is_toll_free = normalized.startswith(("1800", "1900"))
        is_mobile = bool(re.match(r'^[6-9]\d{9}$', normalized.replace("+91", "").replace("91", "")))

        contact_type = "toll_free" if is_toll_free else "phone"
        conf = 0.85 if is_toll_free else (0.8 if not is_mobile else 0.7)

        # Label from context
        start = max(0, m.start() - 80)
        context = text[start:m.start()].strip()

        # Check if it's preceded by "Fax"
        if re.search(r'[Ff]ax\s*:?\s*$', context):
            contact_type = "fax"
            conf = 0.85

        label = _extract_label_from_context(context)

        results.append({
            "contact_type": contact_type,
            "value": normalized,
            "label": label,
            "confidence": conf,
        })
        seen.add(normalized)
    return results


def extract_officers(text: str) -> list[dict]:
    """Extract officer names and designations."""
    results = []
    seen = set()
    for m in OFFICER_RE.finditer(text):
        name  = m.group("name").strip()
        title = m.group("title").strip()
        cadre = m.group("cadre") if m.group("cadre") else None

        key = (name.lower(), title.lower())
        if key in seen:
            continue

        # Basic sanity: name should have 2+ words
        if len(name.split()) < 2:
            continue

        results.append({
            "name": name,
            "designation": title,
            "cadre": cadre,
        })
        seen.add(key)
    return results


def extract_org_from_page(url: str, title: str, text: str) -> Optional[dict]:
    """
    Infer organization name from page URL, title, and body text.
    Returns {name, org_type, level, confidence}
    """
    domain = urlparse(url).netloc.lower()

    # Level detection from domain / URL
    level = "central"
    state_hints = {
        "up": "Uttar Pradesh", "mh": "Maharashtra", "ka": "Karnataka",
        "tn": "Tamil Nadu", "wb": "West Bengal", "dl": "Delhi",
        "gj": "Gujarat", "rj": "Rajasthan", "mp": "Madhya Pradesh",
        "br": "Bihar", "ap": "Andhra Pradesh", "ts": "Telangana",
        "kl": "Kerala", "hr": "Haryana", "pb": "Punjab",
    }
    detected_state = None
    for code, sname in state_hints.items():
        if f".{code}." in domain or f".{code}gov" in domain:
            level = "state"
            detected_state = sname
            break

    if any(x in url.lower() for x in ["district", "/dist/", "collector", "/dho/", "/deo/"]):
        level = "district"

    # Org type detection
    org_type = "department"
    if any(x in title.lower() for x in ["ministry", "mantralaya"]):
        org_type = "ministry"
    elif any(x in title.lower() for x in ["commission", "board", "authority"]):
        org_type = "commission"
    elif any(x in title.lower() for x in ["corporation", "limited", "ltd"]):
        org_type = "psu"
    elif any(x in title.lower() for x in ["court", "tribunal"]):
        org_type = "court"

    # Name: prefer title, fallback to domain
    name = title.split("|")[0].split("-")[0].strip()
    if not name or len(name) < 5:
        name = domain.replace("www.", "").replace(".gov.in", "").replace(".", " ").title()

    confidence = 0.8 if title else 0.5

    return {
        "name": name,
        "org_type": org_type,
        "level": level,
        "detected_state": detected_state,
        "confidence": confidence,
    }


def classify_category(url: str, title: str, text: str) -> Optional[str]:
    """Return category slug based on keyword matching."""
    haystack = f"{url} {title} {text[:2000]}".lower()

    rules = [
        ("health",       ["health", "hospital", "medical", "cmo", "nhm", "aiims",
                           "dispensary", "nursing", "doctor", "medicine", "ayush"]),
        ("education",    ["education", "school", "college", "university", "deo",
                           "ugc", "cbse", "ncert", "scholarship", "teacher", "vidyalaya"]),
        ("police",       ["police", "superintendent", "sp office", "crime", "cbi",
                           "jail", "prison", "fire brigade"]),
        ("revenue",      ["revenue", "land", "tehsil", "collector", "registrar",
                           "mutation", "khasra", "patwari", "stamp duty"]),
        ("water",        ["water", "jal", "irrigation", "groundwater", "borewell",
                           "phe", "sanitation", "sewage", "drainage"]),
        ("electricity",  ["electricity", "power", "discom", "wbsedcl", "bescom",
                           "uppcl", "transformer", "voltage", "outage"]),
        ("transport",    ["transport", "rto", "road", "highway", "nhai", "bus",
                           "railway", "aviation", "metro", "traffic"]),
        ("agriculture",  ["agriculture", "krishi", "farm", "kisan", "kvk", "nabard",
                           "seed", "fertilizer", "irrigation", "horticulture"]),
        ("social",       ["social welfare", "backward", "sc/st", "obc", "welfare",
                           "pension", "anganwadi", "icds", "tribal"]),
        ("environment",  ["environment", "forest", "pollution", "pcb", "cpcb",
                           "wildlife", "biodiversity", "ecology"]),
        ("labour",       ["labour", "labor", "employment", "esic", "epfo", "pf",
                           "factory", "workmen", "wages"]),
        ("women",        ["women", "child", "wcd", "anganwadi", "icds", "crèche",
                           "beti bachao", "maternity"]),
        ("finance",      ["finance", "treasury", "budget", "rbi", "banking", "loan",
                           "income tax", "gst", "customs"]),
        ("housing",      ["housing", "urban", "municipality", "pmay", "smart city",
                           "town planning", "building plan"]),
        ("disaster",     ["disaster", "ndrf", "sdrf", "flood", "earthquake",
                           "relief", "rescue", "emergency"]),
        ("grievance",    ["grievance", "complaint", "rti", "lokayukta", "ombudsman",
                           "cpgrams", "pgportal"]),
    ]

    scores = {}
    for slug, keywords in rules:
        score = sum(1 for kw in keywords if kw in haystack)
        if score > 0:
            scores[slug] = score

    if not scores:
        return None
    return max(scores, key=scores.get)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _extract_label_from_context(context: str) -> Optional[str]:
    """Pull last meaningful phrase from context before a contact value."""
    # Look for label patterns like "Director:", "Complaint Cell:", etc.
    m = re.search(
        r'(?:^|[\n|,])\s*([A-Za-z][A-Za-z\s/&\(\)]{3,60})\s*[:–\-]?\s*$',
        context.strip()
    )
    if m:
        label = m.group(1).strip(" :-–")
        if 4 <= len(label) <= 80:
            return label
    return None


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def is_valid_gov_email(email: str) -> bool:
    gov_domains = (".gov.in", ".nic.in", ".ac.in", ".edu.in", ".org.in",
                   ".res.in", ".gov", ".edu")
    return any(email.endswith(d) for d in gov_domains)
