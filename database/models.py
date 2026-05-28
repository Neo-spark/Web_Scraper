"""
SQLAlchemy ORM models mirroring the PostgreSQL schema.
Handles all relationships and provides helper methods.
"""

from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, Float,
    Text, DateTime, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
import os
from dotenv import load_dotenv

load_dotenv()

Base = declarative_base()


# ─── Lookup Tables ────────────────────────────────────────────────────────────

class State(Base):
    __tablename__ = "states"

    id         = Column(Integer, primary_key=True)
    name       = Column(String(100), nullable=False, unique=True)
    code       = Column(String(5),   nullable=False, unique=True)
    capital    = Column(String(100))
    region     = Column(String(50))
    is_ut      = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    districts     = relationship("District",     back_populates="state")
    organizations = relationship("Organization", back_populates="state")
    officers      = relationship("Officer",      back_populates="state")
    contacts      = relationship("Contact",      back_populates="state")

    def __repr__(self):
        return f"<State {self.code}: {self.name}>"


class District(Base):
    __tablename__ = "districts"

    id          = Column(Integer, primary_key=True)
    state_id    = Column(Integer, ForeignKey("states.id", ondelete="CASCADE"), nullable=False)
    name        = Column(String(100), nullable=False)
    hq_city     = Column(String(100))
    created_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("state_id", "name"),)

    state         = relationship("State",        back_populates="districts")
    blocks        = relationship("Block",        back_populates="district")
    organizations = relationship("Organization", back_populates="district")
    contacts      = relationship("Contact",      back_populates="district")

    def __repr__(self):
        return f"<District {self.name}>"


class Block(Base):
    __tablename__ = "blocks"

    id          = Column(Integer, primary_key=True)
    district_id = Column(Integer, ForeignKey("districts.id", ondelete="CASCADE"), nullable=False)
    name        = Column(String(100), nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("district_id", "name"),)

    district = relationship("District", back_populates="blocks")


class Category(Base):
    __tablename__ = "categories"

    id          = Column(Integer, primary_key=True)
    slug        = Column(String(50),  nullable=False, unique=True)
    name        = Column(String(100), nullable=False)
    name_hi     = Column(String(100))
    icon        = Column(String(10))
    description = Column(Text)
    parent_id   = Column(Integer, ForeignKey("categories.id"))
    created_at  = Column(DateTime, default=datetime.utcnow)

    parent        = relationship("Category", remote_side=[id])
    organizations = relationship("Organization", back_populates="category")
    contacts      = relationship("Contact",      back_populates="category")


# ─── Core Tables ──────────────────────────────────────────────────────────────

class Organization(Base):
    __tablename__ = "organizations"

    id               = Column(Integer, primary_key=True)
    name             = Column(String(300), nullable=False)
    name_normalized  = Column(String(300))
    name_hi          = Column(String(300))
    short_name       = Column(String(50))
    org_type         = Column(String(50))   # ministry/department/board/commission/psu
    level            = Column(String(20), nullable=False)  # central/state/district/local
    state_id         = Column(Integer, ForeignKey("states.id"))
    district_id      = Column(Integer, ForeignKey("districts.id"))
    parent_org_id    = Column(Integer, ForeignKey("organizations.id"))
    category_id      = Column(Integer, ForeignKey("categories.id"))
    website          = Column(String(500))
    address          = Column(Text)
    pin_code         = Column(String(10))
    is_active        = Column(Boolean, default=True)
    source_url       = Column(String(500))
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    state       = relationship("State",    back_populates="organizations")
    district    = relationship("District", back_populates="organizations")
    category    = relationship("Category", back_populates="organizations")
    parent      = relationship("Organization", remote_side=[id], backref="children")
    officers    = relationship("Officer",  back_populates="org")
    contacts    = relationship("Contact",  back_populates="org")

    def __repr__(self):
        return f"<Org [{self.level}] {self.name}>"


class Officer(Base):
    __tablename__ = "officers"

    id          = Column(Integer, primary_key=True)
    name        = Column(String(200), nullable=False)
    name_hi     = Column(String(200))
    designation = Column(String(300), nullable=False)
    cadre       = Column(String(50))   # IAS/IPS/IFS/State
    org_id      = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"))
    state_id    = Column(Integer, ForeignKey("states.id"))
    district_id = Column(Integer, ForeignKey("districts.id"))
    is_current  = Column(Boolean, default=True)
    source_url  = Column(String(500))
    scraped_at  = Column(DateTime, default=datetime.utcnow)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    org      = relationship("Organization", back_populates="officers")
    state    = relationship("State",    back_populates="officers")
    district = relationship("District")
    contacts = relationship("Contact",  back_populates="officer")

    def __repr__(self):
        return f"<Officer {self.name} - {self.designation}>"


class Contact(Base):
    __tablename__ = "contacts"

    id           = Column(Integer, primary_key=True)
    contact_type = Column(String(20), nullable=False)   # email/phone/fax/toll_free
    value        = Column(String(300), nullable=False)
    label        = Column(String(200))

    org_id      = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"))
    officer_id  = Column(Integer, ForeignKey("officers.id",      ondelete="CASCADE"))

    level       = Column(String(20))   # central/state/district/local
    state_id    = Column(Integer, ForeignKey("states.id"))
    district_id = Column(Integer, ForeignKey("districts.id"))
    category_id = Column(Integer, ForeignKey("categories.id"))

    is_active    = Column(Boolean, default=True)
    is_verified  = Column(Boolean, default=False)
    confidence   = Column(Float,   default=0.5)
    source_url   = Column(String(500))
    source_type  = Column(String(20), default="web")
    page_title   = Column(String(300))
    domain       = Column(String(200))
    content_hash = Column(String(64))

    scraped_at    = Column(DateTime, default=datetime.utcnow)
    last_verified = Column(DateTime)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("contact_type", "value", "org_id"),)

    org      = relationship("Organization", back_populates="contacts")
    officer  = relationship("Officer",      back_populates="contacts")
    state    = relationship("State",        back_populates="contacts")
    district = relationship("District",     back_populates="contacts")
    category = relationship("Category",     back_populates="contacts")
    feedback = relationship("ContactFeedback", back_populates="contact")

    def __repr__(self):
        return f"<Contact [{self.contact_type}] {self.value}>"


# ─── Crawl Tracking ───────────────────────────────────────────────────────────

class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id             = Column(Integer, primary_key=True)
    job_name       = Column(String(100))
    started_at     = Column(DateTime, default=datetime.utcnow)
    finished_at    = Column(DateTime)
    status         = Column(String(20), default="running")
    urls_total     = Column(Integer, default=0)
    urls_done      = Column(Integer, default=0)
    contacts_found = Column(Integer, default=0)
    error_log      = Column(Text)

    urls = relationship("CrawlURL", back_populates="job")


class CrawlURL(Base):
    __tablename__ = "crawl_urls"

    id             = Column(Integer, primary_key=True)
    job_id         = Column(Integer, ForeignKey("crawl_jobs.id", ondelete="CASCADE"))
    url            = Column(String(1000), nullable=False, unique=True)
    domain         = Column(String(200))
    depth          = Column(Integer, default=0)
    priority       = Column(Integer, default=50)
    status         = Column(String(20), default="pending")
    status_code    = Column(Integer)
    content_hash   = Column(String(64))
    contacts_found = Column(Integer, default=0)
    error          = Column(Text)
    crawled_at     = Column(DateTime)
    added_at       = Column(DateTime, default=datetime.utcnow)

    job = relationship("CrawlJob", back_populates="urls")


# ─── Analytics ────────────────────────────────────────────────────────────────

class SearchLog(Base):
    __tablename__ = "search_logs"

    id            = Column(Integer, primary_key=True)
    query         = Column(String(500))
    category_slug = Column(String(50))
    state_id      = Column(Integer, ForeignKey("states.id"))
    district_id   = Column(Integer, ForeignKey("districts.id"))
    results_count = Column(Integer)
    latency_ms    = Column(Float)
    user_ip       = Column(String(50))
    created_at    = Column(DateTime, default=datetime.utcnow)


class ContactFeedback(Base):
    __tablename__ = "contact_feedback"

    id          = Column(Integer, primary_key=True)
    contact_id  = Column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"))
    is_working  = Column(Boolean)
    comment     = Column(Text)
    reported_by = Column(String(100))
    created_at  = Column(DateTime, default=datetime.utcnow)

    contact = relationship("Contact", back_populates="feedback")


# ─── DB Setup ─────────────────────────────────────────────────────────────────

def get_engine(db_url: str = None):
    url = db_url or os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/govcontacts")
    return create_engine(url, pool_size=10, max_overflow=20, echo=False)


def create_all(engine):
    Base.metadata.create_all(engine)
    print("✅ All tables created.")


def get_session(engine):
    Session = sessionmaker(bind=engine)
    return Session()


if __name__ == "__main__":
    engine = get_engine()
    create_all(engine)
