"""
Sampark Setu - FastAPI Backend
Serves government contacts from PostgreSQL to the frontend.

Run: uvicorn api.main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""

import os
import time
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, Query, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from dotenv import load_dotenv

load_dotenv()

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import (
    get_engine, get_session,
    State, District, Category, Organization, Officer, Contact, SearchLog
)

# ─── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Sampark Setu API",
    description="Government Contact Directory — India",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],  # restrict in prod
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = get_engine(os.getenv("DATABASE_URL"))


def get_db():
    session = get_session(engine)
    try:
        yield session
    finally:
        session.close()


# ─── Reference data endpoints ─────────────────────────────────────────────────

@app.get("/states", tags=["Reference"])
def list_states(db: Session = Depends(get_db)):
    """All states and UTs."""
    states = db.query(State).order_by(State.name).all()
    return [{"id": s.id, "name": s.name, "code": s.code,
             "capital": s.capital, "is_ut": s.is_ut} for s in states]


@app.get("/states/{state_id}/districts", tags=["Reference"])
def list_districts(state_id: int, db: Session = Depends(get_db)):
    """Districts for a state."""
    districts = db.query(District).filter_by(state_id=state_id).order_by(District.name).all()
    return [{"id": d.id, "name": d.name} for d in districts]


@app.get("/categories", tags=["Reference"])
def list_categories(db: Session = Depends(get_db)):
    """All contact categories."""
    cats = db.query(Category).order_by(Category.name).all()
    return [{"id": c.id, "slug": c.slug, "name": c.name,
             "name_hi": c.name_hi, "icon": c.icon} for c in cats]


# ─── Main contact search ───────────────────────────────────────────────────────

@app.get("/contacts", tags=["Contacts"])
def search_contacts(
    category:    Optional[str] = Query(None, description="Category slug e.g. health"),
    state_id:    Optional[int] = Query(None),
    district_id: Optional[int] = Query(None),
    level:       Optional[str] = Query(None, description="central/state/district"),
    contact_type:Optional[str] = Query(None, description="email/phone/fax/toll_free"),
    q:           Optional[str] = Query(None, description="Free text search"),
    limit:       int           = Query(50, le=200),
    offset:      int           = Query(0),
    db: Session = Depends(get_db)
):
    """
    Main contact search endpoint.
    Returns contacts with full org, officer, state, district context.
    """
    t0 = time.perf_counter()

    query = db.query(Contact)

    if category:
        cat = db.query(Category).filter_by(slug=category).first()
        if cat:
            query = query.filter(Contact.category_id == cat.id)

    if state_id:
        query = query.filter(Contact.state_id == state_id)

    if district_id:
        query = query.filter(Contact.district_id == district_id)

    if level:
        query = query.filter(Contact.level == level)

    if contact_type:
        query = query.filter(Contact.contact_type == contact_type)

    if q:
        # Simple ILIKE search on value and label
        pattern = f"%{q}%"
        query = query.filter(
            (Contact.value.ilike(pattern)) |
            (Contact.label.ilike(pattern))
        )

    query = query.filter(Contact.is_active == True)
    total = query.count()
    contacts = query.order_by(Contact.confidence.desc()).offset(offset).limit(limit).all()

    latency = (time.perf_counter() - t0) * 1000

    # Log search
    try:
        db.add(SearchLog(
            query=q or category,
            category_slug=category,
            state_id=state_id,
            district_id=district_id,
            results_count=total,
            latency_ms=latency,
        ))
        db.commit()
    except Exception:
        db.rollback()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "latency_ms": round(latency, 1),
        "results": [_format_contact(c, db) for c in contacts]
    }


@app.get("/contacts/by-location", tags=["Contacts"])
def contacts_by_location(
    category:     str = Query(..., description="Category slug e.g. health"),
    state_code:   str = Query(..., description="State code e.g. MH, UP"),
    district_name: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Frontend-friendly endpoint: pass state code + optional district name,
    get back district → state → central contacts in one call.
    """
    state = db.query(State).filter_by(code=state_code.upper()).first()
    if not state:
        raise HTTPException(404, f"State '{state_code}' not found")

    cat = db.query(Category).filter_by(slug=category).first()
    cat_id = cat.id if cat else None

    district = None
    if district_name:
        district = (db.query(District)
                    .filter_by(state_id=state.id, name=district_name)
                    .first())

    def fetch(level, state_id=None, district_id=None):
        q = (db.query(Contact)
             .filter(Contact.is_active == True, Contact.level == level))
        if cat_id:
            q = q.filter(Contact.category_id == cat_id)
        if state_id:
            q = q.filter(Contact.state_id == state_id)
        if district_id:
            q = q.filter(Contact.district_id == district_id)
        return q.order_by(Contact.confidence.desc()).limit(20).all()

    district_contacts = fetch("district", state.id, district.id if district else None)
    state_contacts    = fetch("state",    state.id)
    central_contacts  = fetch("central")

    return {
        "location": {
            "state": state.name,
            "state_code": state.code,
            "district": district.name if district else None,
        },
        "category": {"slug": cat.slug, "name": cat.name, "icon": cat.icon} if cat else None,
        "district_contacts": [_format_contact(c, db) for c in district_contacts],
        "state_contacts":    [_format_contact(c, db) for c in state_contacts],
        "central_contacts":  [_format_contact(c, db) for c in central_contacts],
    }


@app.get("/contacts/{contact_id}", tags=["Contacts"])
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    c = db.query(Contact).filter_by(id=contact_id).first()
    if not c:
        raise HTTPException(404, "Contact not found")
    return _format_contact(c, db)


# ─── Organizations ────────────────────────────────────────────────────────────

@app.get("/organizations", tags=["Organizations"])
def list_organizations(
    level:       Optional[str] = Query(None),
    state_id:    Optional[int] = Query(None),
    category:    Optional[str] = Query(None),
    q:           Optional[str] = Query(None),
    limit:       int = Query(50, le=200),
    db: Session = Depends(get_db)
):
    query = db.query(Organization).filter(Organization.is_active == True)
    if level:
        query = query.filter(Organization.level == level)
    if state_id:
        query = query.filter(Organization.state_id == state_id)
    if category:
        cat = db.query(Category).filter_by(slug=category).first()
        if cat:
            query = query.filter(Organization.category_id == cat.id)
    if q:
        query = query.filter(Organization.name.ilike(f"%{q}%"))

    orgs = query.limit(limit).all()
    return [{"id": o.id, "name": o.name, "short_name": o.short_name,
             "org_type": o.org_type, "level": o.level, "website": o.website,
             "contact_count": len(o.contacts)} for o in orgs]


# ─── Stats ────────────────────────────────────────────────────────────────────

@app.get("/stats", tags=["Stats"])
def stats(db: Session = Depends(get_db)):
    """Platform-wide statistics."""
    return {
        "total_contacts":     db.query(Contact).filter_by(is_active=True).count(),
        "total_orgs":         db.query(Organization).count(),
        "total_officers":     db.query(Officer).count(),
        "total_states":       db.query(State).count(),
        "total_districts":    db.query(District).count(),
        "emails":             db.query(Contact).filter_by(contact_type="email",  is_active=True).count(),
        "phones":             db.query(Contact).filter_by(contact_type="phone",  is_active=True).count(),
        "toll_free":          db.query(Contact).filter_by(contact_type="toll_free", is_active=True).count(),
        "central_contacts":   db.query(Contact).filter_by(level="central",  is_active=True).count(),
        "state_contacts":     db.query(Contact).filter_by(level="state",    is_active=True).count(),
        "district_contacts":  db.query(Contact).filter_by(level="district", is_active=True).count(),
    }


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ─── Helper ───────────────────────────────────────────────────────────────────

def _format_contact(c: Contact, db: Session) -> dict:
    org      = db.get(Organization, c.org_id)      if c.org_id      else None
    officer  = db.get(Officer,      c.officer_id)   if c.officer_id  else None
    state    = db.get(State,        c.state_id)     if c.state_id    else None
    district = db.get(District,     c.district_id)  if c.district_id else None
    category = db.get(Category,     c.category_id)  if c.category_id else None

    return {
        "id":           c.id,
        "contact_type": c.contact_type,
        "value":        c.value,
        "label":        c.label,
        "level":        c.level,
        "confidence":   c.confidence,
        "is_verified":  c.is_verified,
        "source_url":   c.source_url,
        "scraped_at":   c.scraped_at.isoformat() if c.scraped_at else None,
        "organization": {
            "id":        org.id,
            "name":      org.name,
            "short_name":org.short_name,
            "org_type":  org.org_type,
            "website":   org.website,
        } if org else None,
        "officer": {
            "name":        officer.name,
            "designation": officer.designation,
            "cadre":       officer.cadre,
        } if officer else None,
        "state":    {"id": state.id,    "name": state.name,    "code": state.code}    if state    else None,
        "district": {"id": district.id, "name": district.name}                         if district else None,
        "category": {"slug": category.slug, "name": category.name, "icon": category.icon} if category else None,
    }
