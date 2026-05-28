"""
setup.py — One-command project initializer
Run: python setup.py

What it does:
  1. Creates all directories
  2. Copies .env.example -> .env (if not exists)
  3. Waits for PostgreSQL to be ready
  4. Creates all database tables
  5. Seeds reference data (states, districts, categories)
  6. Prints next steps
"""

import os
import sys
import time
import subprocess
from pathlib import Path


def banner(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print('='*60)


def run(cmd, check=True):
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True)
    if check and result.returncode != 0:
        print(f"  ❌ Command failed: {cmd}")
        sys.exit(1)
    return result.returncode == 0


def wait_for_postgres(db_url: str, retries: int = 15):
    """Poll until PostgreSQL is accepting connections."""
    import psycopg2
    print("\n⏳ Waiting for PostgreSQL...")
    for i in range(retries):
        try:
            conn = psycopg2.connect(db_url)
            conn.close()
            print("  ✅ PostgreSQL is ready!")
            return True
        except Exception as e:
            print(f"  [{i+1}/{retries}] Not ready yet... ({e})")
            time.sleep(3)
    print("  ❌ Could not connect to PostgreSQL.")
    return False


def main():
    banner("Sampark Setu — Setup")

    # 1. Create directories
    dirs = ["logs", "pdfs", "reports", "datasets", "api"]
    for d in dirs:
        Path(d).mkdir(exist_ok=True)
    print("✅ Directories created.")

    # 2. Copy .env
    if not Path(".env").exists():
        if Path(".env.example").exists():
            import shutil
            shutil.copy(".env.example", ".env")
            print("✅ .env created from .env.example — edit it with your DB password!")
        else:
            print("⚠  No .env.example found. Create .env manually.")
    else:
        print("✅ .env already exists.")

    # 3. Load env
    from dotenv import load_dotenv
    load_dotenv()
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:yourpassword@localhost:5432/govcontacts")

    # 4. Install deps check
    banner("Checking Python dependencies")
    run(f"{sys.executable} -m pip install -r requirements.txt -q")
    print("✅ Dependencies installed.")

    # 5. Wait for DB
    if not wait_for_postgres(db_url):
        print("\n💡 Tip: Start PostgreSQL with:  docker-compose up -d postgres")
        print("   Then re-run: python setup.py")
        sys.exit(1)

    # 6. Create tables + seed
    banner("Creating database tables")
    sys.path.insert(0, str(Path(__file__).parent))
    from database.models import get_engine, create_all
    engine = get_engine(db_url)
    create_all(engine)

    # Enable pg_trgm extension for fuzzy search
    try:
        with engine.connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
            conn.execute("CREATE EXTENSION IF NOT EXISTS unaccent;")
            conn.commit()
    except Exception as e:
        print(f"  ⚠ Extensions (non-fatal): {e}")

    banner("Seeding reference data")
    from database.seed import seed_all
    seed_all(db_url)

    banner("✅ Setup Complete!")
    print("""
Next steps:
──────────────────────────────────────────────────
1. Run the crawler (start small):
     python scrapers/crawler.py --max-pages 200

2. Start the API:
     uvicorn api.main:app --reload --port 8000
     Open: http://localhost:8000/docs

3. Check stats:
     curl http://localhost:8000/stats

4. Query contacts (example):
     curl "http://localhost:8000/contacts/by-location?category=health&state_code=MH&district_name=Pune"

5. Process PDFs (optional):
     python scrapers/pdf_scraper.py --folder pdfs/

──────────────────────────────────────────────────
pgAdmin (if using Docker):  http://localhost:5050
  Email:    admin@samparksetu.in
  Password: admin123
──────────────────────────────────────────────────
    """)


if __name__ == "__main__":
    main()
