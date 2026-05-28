-- =============================================================================
-- SAMPARK SETU - Government Contact Database Schema
-- PostgreSQL with full relationships
-- =============================================================================

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- fuzzy text search
CREATE EXTENSION IF NOT EXISTS "unaccent";    -- accent-insensitive search

-- =============================================================================
-- LOOKUP / REFERENCE TABLES
-- =============================================================================

CREATE TABLE IF NOT EXISTS states (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,
    code        VARCHAR(5)   NOT NULL UNIQUE,   -- e.g. MH, UP, KA
    capital     VARCHAR(100),
    region      VARCHAR(50),                    -- North/South/East/West/Central/Northeast
    is_ut       BOOLEAN DEFAULT FALSE,          -- Union Territory flag
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS districts (
    id          SERIAL PRIMARY KEY,
    state_id    INTEGER NOT NULL REFERENCES states(id) ON DELETE CASCADE,
    name        VARCHAR(100) NOT NULL,
    hq_city     VARCHAR(100),                   -- district headquarters city
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE(state_id, name)
);

CREATE TABLE IF NOT EXISTS blocks (
    id          SERIAL PRIMARY KEY,
    district_id INTEGER NOT NULL REFERENCES districts(id) ON DELETE CASCADE,
    name        VARCHAR(100) NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE(district_id, name)
);

CREATE TABLE IF NOT EXISTS categories (
    id          SERIAL PRIMARY KEY,
    slug        VARCHAR(50)  NOT NULL UNIQUE,   -- health, education, police
    name        VARCHAR(100) NOT NULL,
    name_hi     VARCHAR(100),                   -- Hindi name
    icon        VARCHAR(10),                    -- emoji
    description TEXT,
    parent_id   INTEGER REFERENCES categories(id),  -- sub-categories
    created_at  TIMESTAMP DEFAULT NOW()
);

-- =============================================================================
-- CORE ORGANIZATION HIERARCHY
-- =============================================================================

CREATE TABLE IF NOT EXISTS organizations (
    id                  SERIAL PRIMARY KEY,
    name                VARCHAR(300) NOT NULL,
    name_normalized     VARCHAR(300),           -- cleaned/canonical name
    name_hi             VARCHAR(300),           -- Hindi name
    short_name          VARCHAR(50),            -- UGC, AIIMS, CBI
    org_type            VARCHAR(50),            -- ministry/department/board/commission/court/psu
    level               VARCHAR(20) NOT NULL,   -- central/state/district/local
    state_id            INTEGER REFERENCES states(id),
    district_id         INTEGER REFERENCES districts(id),
    parent_org_id       INTEGER REFERENCES organizations(id),  -- hierarchy
    category_id         INTEGER REFERENCES categories(id),
    website             VARCHAR(500),
    address             TEXT,
    pin_code            VARCHAR(10),
    is_active           BOOLEAN DEFAULT TRUE,
    source_url          VARCHAR(500),
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

-- =============================================================================
-- OFFICERS / PERSONS
-- =============================================================================

CREATE TABLE IF NOT EXISTS officers (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    name_hi         VARCHAR(200),
    designation     VARCHAR(300) NOT NULL,
    cadre           VARCHAR(50),                -- IAS/IPS/IFS/State Service
    org_id          INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    state_id        INTEGER REFERENCES states(id),   -- posting state
    district_id     INTEGER REFERENCES districts(id),
    is_current      BOOLEAN DEFAULT TRUE,
    source_url      VARCHAR(500),
    scraped_at      TIMESTAMP DEFAULT NOW(),
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- =============================================================================
-- CONTACTS  (email / phone / fax / address)
-- =============================================================================

CREATE TABLE IF NOT EXISTS contacts (
    id              SERIAL PRIMARY KEY,
    contact_type    VARCHAR(20) NOT NULL,       -- email/phone/fax/whatsapp/toll_free
    value           VARCHAR(300) NOT NULL,
    label           VARCHAR(200),               -- "Complaint Cell", "Director Office"

    -- What this contact belongs to (only one FK will be non-null)
    org_id          INTEGER REFERENCES organizations(id)  ON DELETE CASCADE,
    officer_id      INTEGER REFERENCES officers(id)       ON DELETE CASCADE,

    -- Geographic scope of this contact
    level           VARCHAR(20),                -- central/state/district/local
    state_id        INTEGER REFERENCES states(id),
    district_id     INTEGER REFERENCES districts(id),
    category_id     INTEGER REFERENCES categories(id),

    -- Quality & provenance
    is_active       BOOLEAN DEFAULT TRUE,
    is_verified     BOOLEAN DEFAULT FALSE,
    confidence      FLOAT DEFAULT 0.5,          -- 0.0 - 1.0
    source_url      VARCHAR(500),
    source_type     VARCHAR(20) DEFAULT 'web',  -- web/pdf/pdf_ocr/manual
    page_title      VARCHAR(300),
    domain          VARCHAR(200),
    content_hash    VARCHAR(64),                -- SHA-256 to prevent duplicates

    scraped_at      TIMESTAMP DEFAULT NOW(),
    last_verified   TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),

    -- Prevent exact duplicate contacts for same org
    UNIQUE(contact_type, value, org_id)
);

-- =============================================================================
-- CRAWL TRACKING
-- =============================================================================

CREATE TABLE IF NOT EXISTS crawl_jobs (
    id          SERIAL PRIMARY KEY,
    job_name    VARCHAR(100),
    started_at  TIMESTAMP DEFAULT NOW(),
    finished_at TIMESTAMP,
    status      VARCHAR(20) DEFAULT 'running',  -- running/completed/failed
    urls_total  INTEGER DEFAULT 0,
    urls_done   INTEGER DEFAULT 0,
    contacts_found INTEGER DEFAULT 0,
    error_log   TEXT
);

CREATE TABLE IF NOT EXISTS crawl_urls (
    id              SERIAL PRIMARY KEY,
    job_id          INTEGER REFERENCES crawl_jobs(id) ON DELETE CASCADE,
    url             VARCHAR(1000) NOT NULL UNIQUE,
    domain          VARCHAR(200),
    depth           INTEGER DEFAULT 0,
    priority        INTEGER DEFAULT 50,         -- lower = crawl first
    status          VARCHAR(20) DEFAULT 'pending', -- pending/crawled/failed/skipped
    status_code     INTEGER,
    content_hash    VARCHAR(64),
    contacts_found  INTEGER DEFAULT 0,
    error           TEXT,
    crawled_at      TIMESTAMP,
    added_at        TIMESTAMP DEFAULT NOW()
);

-- =============================================================================
-- SEARCH & ANALYTICS
-- =============================================================================

CREATE TABLE IF NOT EXISTS search_logs (
    id              SERIAL PRIMARY KEY,
    query           VARCHAR(500),
    category_slug   VARCHAR(50),
    state_id        INTEGER REFERENCES states(id),
    district_id     INTEGER REFERENCES districts(id),
    results_count   INTEGER,
    latency_ms      FLOAT,
    user_ip         VARCHAR(50),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contact_feedback (
    id          SERIAL PRIMARY KEY,
    contact_id  INTEGER REFERENCES contacts(id) ON DELETE CASCADE,
    is_working  BOOLEAN,                        -- phone/email still active?
    comment     TEXT,
    reported_by VARCHAR(100),
    created_at  TIMESTAMP DEFAULT NOW()
);

-- =============================================================================
-- INDEXES  (critical for fast lookups)
-- =============================================================================

-- Organizations
CREATE INDEX idx_org_level        ON organizations(level);
CREATE INDEX idx_org_state        ON organizations(state_id);
CREATE INDEX idx_org_district     ON organizations(district_id);
CREATE INDEX idx_org_category     ON organizations(category_id);
CREATE INDEX idx_org_name_trgm    ON organizations USING gin(name_normalized gin_trgm_ops);

-- Officers
CREATE INDEX idx_officer_org      ON officers(org_id);
CREATE INDEX idx_officer_state    ON officers(state_id);
CREATE INDEX idx_officer_district ON officers(district_id);

-- Contacts  (most queried table)
CREATE INDEX idx_contact_type     ON contacts(contact_type);
CREATE INDEX idx_contact_org      ON contacts(org_id);
CREATE INDEX idx_contact_officer  ON contacts(officer_id);
CREATE INDEX idx_contact_level    ON contacts(level);
CREATE INDEX idx_contact_state    ON contacts(state_id);
CREATE INDEX idx_contact_district ON contacts(district_id);
CREATE INDEX idx_contact_category ON contacts(category_id);
CREATE INDEX idx_contact_active   ON contacts(is_active);
CREATE INDEX idx_contact_hash     ON contacts(content_hash);

-- URLs
CREATE INDEX idx_url_status       ON crawl_urls(status);
CREATE INDEX idx_url_domain       ON crawl_urls(domain);
CREATE INDEX idx_url_priority     ON crawl_urls(priority);

-- =============================================================================
-- USEFUL VIEWS
-- =============================================================================

-- Full contact with all context joined
CREATE OR REPLACE VIEW v_contacts_full AS
SELECT
    c.id,
    c.contact_type,
    c.value,
    c.label,
    c.level,
    c.confidence,
    c.is_active,
    c.is_verified,
    c.source_url,
    c.scraped_at,

    -- Organization info
    o.name            AS org_name,
    o.short_name      AS org_short,
    o.org_type,
    o.website         AS org_website,

    -- Officer info
    off.name          AS officer_name,
    off.designation,
    off.cadre,

    -- Geography
    s.name            AS state_name,
    s.code            AS state_code,
    d.name            AS district_name,

    -- Category
    cat.name          AS category_name,
    cat.slug          AS category_slug,
    cat.icon          AS category_icon

FROM contacts c
LEFT JOIN organizations o   ON c.org_id      = o.id
LEFT JOIN officers off      ON c.officer_id  = off.id
LEFT JOIN states s          ON c.state_id    = s.id
LEFT JOIN districts d       ON c.district_id = d.id
LEFT JOIN categories cat    ON c.category_id = cat.id
WHERE c.is_active = TRUE;


-- Org hierarchy view
CREATE OR REPLACE VIEW v_org_hierarchy AS
SELECT
    o.id,
    o.name,
    o.short_name,
    o.org_type,
    o.level,
    o.website,
    p.name            AS parent_name,
    p.level           AS parent_level,
    s.name            AS state_name,
    d.name            AS district_name,
    cat.name          AS category_name,
    cat.slug          AS category_slug,
    (SELECT COUNT(*) FROM contacts WHERE org_id = o.id AND is_active = TRUE) AS contact_count
FROM organizations o
LEFT JOIN organizations p   ON o.parent_org_id = p.id
LEFT JOIN states s          ON o.state_id       = s.id
LEFT JOIN districts d       ON o.district_id    = d.id
LEFT JOIN categories cat    ON o.category_id    = cat.id;
