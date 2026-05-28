"""
Reset the crawler logs and scraped data tables in the database.
This deletes all crawled URLs, crawl jobs, contacts, officers, organizations, and logs,
allowing the crawler to start completely from scratch.
Static reference tables (states, districts, categories) are kept.
"""

from database.models import get_engine
from sqlalchemy import text
import os
from dotenv import load_dotenv

load_dotenv()

def reset_database():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ DATABASE_URL not set in environment.")
        return
        
    print("Connecting to database...")
    engine = get_engine(db_url)
    
    # We truncate all scraper-related tables, using CASCADE to handle foreign keys
    tables = [
        "contact_feedback",
        "contacts",
        "officers",
        "organizations",
        "crawl_urls",
        "crawl_jobs",
        "search_logs"
    ]
    
    query = text(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE;")
    
    try:
        with engine.begin() as conn:
            print("Resetting tables (truncating)...")
            conn.execute(query)
        print("✅ Database tables successfully reset! Visited URL logs and scraped data have been cleared.")
    except Exception as e:
        print(f"❌ Failed to reset database: {e}")

if __name__ == "__main__":
    reset_database()
