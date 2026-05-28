# 🇮🇳 Sampark Setu — Government Contact Scraper & Database

> Automatically crawl Indian government websites, extract contacts (email, phone, fax),
> officers, and organizations, then store them in PostgreSQL with full relationships.

---

## 📁 Project Structure

```
gov_scraper/
├── database/
│   ├── schema.sql        ← Raw SQL schema (tables, indexes, views)
│   ├── models.py         ← SQLAlchemy ORM models + relationships
│   └── seed.py           ← Seed states, districts, categories
│
├── extractors/
│   └── extractors.py     ← Regex extractors: email, phone, officers, orgs, categories
│
├── scrapers/
│   ├── crawler.py        ← Main async crawler (aiohttp, 12 workers)
│   └── pdf_scraper.py    ← PDF extractor (pdfplumber + Tesseract OCR)
│
├── api/
│   └── main.py           ← FastAPI REST API (serves contacts to frontend)
│
├── seeds/
│   └── gov_seeds.txt     ← 100+ government seed URLs
│
├── setup.py              ← One-command setup script
├── requirements.txt      ← Python dependencies
├── docker-compose.yml    ← PostgreSQL + pgAdmin containers
└── .env.example          ← Environment config template
```

---

## 🗄️ Database Schema (Relationships)

```
states (36 rows)
  └── districts (600+ rows)
        └── blocks

categories (16 rows: health, education, police...)

organizations
  ├── belongs to: state, district, category
  ├── has parent: organization (hierarchy)
  └── has many: contacts, officers

officers
  ├── belongs to: organization, state, district
  └── has many: contacts

contacts  ← MAIN TABLE
  ├── belongs to: organization OR officer
  ├── belongs to: state, district, category
  └── has many: feedback

crawl_jobs → crawl_urls  (tracking)
search_logs               (analytics)
contact_feedback          (crowd verification)
```

---

## ⚡ Quick Start

### Step 1 — Prerequisites

Install:
- Python 3.11+
- Docker Desktop (for PostgreSQL)
- Git

### Step 2 — Clone & Setup

```bash
# Unzip the project
cd gov_scraper

# Start PostgreSQL + pgAdmin
docker-compose up -d

# Wait ~10 seconds, then run setup
python setup.py
```

`setup.py` automatically:
- Installs all Python dependencies
- Creates `.env` from `.env.example`
- Waits for PostgreSQL to be ready
- Creates all database tables
- Seeds all 36 states, 600+ districts, 16 categories

### Step 3 — Edit .env

Open `.env` and confirm your database password matches `docker-compose.yml`:
```
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/govcontacts
```

### Step 4 — Run the Crawler

```bash
# Start small (200 pages) to test
python scrapers/crawler.py --max-pages 200

# Full crawl (1000 pages, takes ~30 min)
python scrapers/crawler.py --max-pages 1000 --concurrency 12

# Custom seed file
python scrapers/crawler.py --seed seeds/gov_seeds.txt --max-pages 500
```

**What the crawler does per page:**
1. Checks if URL already visited (dedup by SHA-256 hash)
2. Respects `robots.txt` delay (0.3s between requests per domain)
3. Extracts: emails, phones, officer names, organization name, state, category
4. Saves to PostgreSQL with all foreign key relationships
5. Discovers new links and enqueues with priority scoring

### Step 5 — Start the API

```bash
uvicorn api.main:app --reload --port 8000
```

Open **http://localhost:8000/docs** for interactive API docs.

---

## 🔌 API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /contacts/by-location` | Main endpoint — district+state+central contacts |
| `GET /contacts` | Search with filters |
| `GET /states` | All 36 states/UTs |
| `GET /states/{id}/districts` | Districts for a state |
| `GET /categories` | All 16 categories |
| `GET /organizations` | Search organizations |
| `GET /stats` | Platform statistics |
| `GET /health` | Health check |

### Example API Calls

```bash
# Health contacts for Pune, Maharashtra
curl "http://localhost:8000/contacts/by-location?category=health&state_code=MH&district_name=Pune"

# All phone numbers in UP for education
curl "http://localhost:8000/contacts?category=education&state_id=26&contact_type=phone"

# Central government police contacts
curl "http://localhost:8000/contacts?level=central&category=police"

# Platform stats
curl "http://localhost:8000/stats"
```

### Response Format

```json
{
  "district_contacts": [
    {
      "id": 1,
      "contact_type": "phone",
      "value": "05322234567",
      "label": "CMO Office",
      "level": "district",
      "confidence": 0.85,
      "organization": {
        "name": "Chief Medical Officer, Pune",
        "org_type": "department",
        "website": "https://arogya.maharashtra.gov.in"
      },
      "officer": {
        "name": "Dr. R.K. Sharma",
        "designation": "Chief Medical Officer",
        "cadre": "IAS"
      },
      "state": { "name": "Maharashtra", "code": "MH" },
      "district": { "name": "Pune" },
      "category": { "slug": "health", "name": "Health & Medical", "icon": "🏥" }
    }
  ],
  "state_contacts": [...],
  "central_contacts": [...]
}
```

---

## 🌐 Connect to Your Frontend (React)

```javascript
// Fetch contacts by location + category
const res = await fetch(
  `http://localhost:8000/contacts/by-location?category=health&state_code=MH&district_name=Pune`
);
const data = await res.json();

// data.district_contacts → local contacts
// data.state_contacts    → state level contacts
// data.central_contacts  → central govt contacts
```

---

## 📄 PDF Processing

The PDF scraper handles government phone directories and circulars:

```bash
# Process a single PDF URL
python scrapers/pdf_scraper.py --url https://mohfw.gov.in/directory.pdf

# Process all PDFs in a folder
python scrapers/pdf_scraper.py --folder pdfs/
```

For scanned PDFs, install Tesseract:
- **Windows:** https://github.com/UB-Mannheim/tesseract/wiki
- **Ubuntu:** `sudo apt install tesseract-ocr tesseract-ocr-hin`
- **Mac:** `brew install tesseract`

---

## 🔍 pgAdmin (Visual Database Browser)

1. Open **http://localhost:5050**
2. Login: `admin@samparksetu.in` / `admin123`
3. Add Server:
   - Host: `postgres`
   - Port: `5432`
   - Database: `govcontacts`
   - Username: `postgres`
   - Password: `yourpassword`

Useful queries in pgAdmin:

```sql
-- All contacts with full context
SELECT * FROM v_contacts_full LIMIT 100;

-- Contacts by state + category
SELECT * FROM v_contacts_full
WHERE state_name = 'Maharashtra' AND category_slug = 'health'
ORDER BY level, confidence DESC;

-- Organization hierarchy
SELECT * FROM v_org_hierarchy WHERE level = 'central';

-- Top organizations by contact count
SELECT org_name, COUNT(*) as contacts
FROM v_contacts_full
GROUP BY org_name
ORDER BY contacts DESC
LIMIT 20;
```

---

## ⚙️ Configuration

Edit `.env`:

```env
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/govcontacts
MAX_PAGES=1000          # pages per crawl run
CONCURRENCY=12          # parallel workers (reduce if slow internet)
REQUEST_DELAY=0.3       # seconds between requests per domain
MAX_DEPTH=3             # link-follow depth from seed URL
```

---

## 🔧 Troubleshooting

| Problem | Fix |
|---------|-----|
| `psycopg2.OperationalError` | PostgreSQL not running — `docker-compose up -d` |
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` |
| Crawler finds 0 contacts | Try URLs with `/contact` in path, check `logs/crawler.log` |
| PDF OCR not working | Install Tesseract (see PDF section above) |
| Slow crawl | Reduce `--concurrency` to 5–6 on slow networks |

---

## 📈 Scaling

| Scale | Action |
|-------|--------|
| 10k contacts | Default setup, pickle cache |
| 100k contacts | Add pgvector for semantic search |
| 1M contacts | Add Celery workers, Redis queue |
| 10M+ | Kubernetes + Kafka streaming |

---

## 🛡️ Security Notes (for production)

- Change DB password from `yourpassword` to a strong random string
- Restrict CORS in `api/main.py` to your domain only
- Add rate limiting with `slowapi`
- Put API behind nginx with HTTPS
- Never commit `.env` to git

---

## 📜 License

MIT License — Free to use, modify, and deploy.
