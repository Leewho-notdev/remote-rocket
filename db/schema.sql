-- ============================================================
-- Remote Rocket — Database Schema
-- SQLite database: /app/db/jobs.db
--
-- Run via: python db/init_db.py
-- Or automatically on scraper container startup.
-- ============================================================

-- ============================================================
-- JOBS
-- One row per unique job listing. URL is the primary dedup key.
-- ============================================================
CREATE TABLE IF NOT EXISTS jobs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Source tracking
    source           TEXT NOT NULL,      -- 'jobspy_linkedin', 'jobspy_indeed', 'career_page', etc.
    external_id      TEXT,               -- The source platform's own job ID (if available)
    url              TEXT NOT NULL,      -- Direct apply/listing URL — PRIMARY dedup key
    source_url       TEXT,               -- The page this job was found on (career page URL, board URL)

    -- Core job details (LLM-extracted)
    title            TEXT NOT NULL,
    company          TEXT NOT NULL,
    location         TEXT,               -- Usually "Remote" — kept for reference
    employment_type  TEXT,               -- 'full_time', 'contract', 'part_time'

    -- Salary (normalized to annual USD integers for easy filtering)
    salary_min       INTEGER,            -- Annual USD minimum
    salary_max       INTEGER,            -- Annual USD maximum
    salary_raw       TEXT,               -- Original salary text before normalization
    salary_currency  TEXT DEFAULT 'USD',

    -- Job content
    description_raw  TEXT,              -- Original description (HTML or plain text from source)
    description_clean TEXT,             -- Cleaned plain text version (whitespace/HTML stripped)
    requirements     TEXT,              -- JSON array: ["5+ years Google Ads", "Google Analytics", ...]
    skills_detected  TEXT,              -- JSON array of tool/platform names: ["Google Ads", "GTM", ...]

    -- LLM audit trail
    raw_llm_response TEXT,              -- Full JSON response from Claude (for debugging + re-processing)

    -- Relevance scoring (LLM-assigned, 1–10)
    relevance_score  INTEGER,           -- Overall fit for the target profile (10 = perfect match)
    salary_score     INTEGER,           -- 1–10 derived from salary vs configured threshold

    -- Boolean flags (LLM-assigned, stored as 0/1)
    is_fully_remote  INTEGER DEFAULT 0, -- 1 = confirmed fully remote
    is_hidden_gem    INTEGER DEFAULT 0, -- 1 = found on a career page, not a job board
    has_google_ads   INTEGER DEFAULT 0, -- Google Ads explicitly mentioned
    has_msft_ads     INTEGER DEFAULT 0, -- Microsoft Ads / Bing Ads mentioned
    has_gtm          INTEGER DEFAULT 0, -- Google Tag Manager mentioned
    has_gmc          INTEGER DEFAULT 0, -- Google Merchant Center mentioned
    is_excluded      INTEGER DEFAULT 0, -- 1 = filtered out by LLM (social media, on-site, etc.)
    exclusion_reason TEXT,              -- Human-readable reason for exclusion

    -- Freshness tracking
    is_active        INTEGER DEFAULT 1, -- 0 = not seen in recent scrapes (expired or filled)
    last_seen_at     TEXT,              -- Timestamp of the most recent scrape that found this job
    date_posted      TEXT,              -- ISO 8601 date string from the source
    date_scraped     TEXT DEFAULT (datetime('now')), -- When we first stored this job
    date_updated     TEXT,              -- When any field was last updated
    created_at       TEXT DEFAULT (datetime('now')),

    -- Internal: normalized values used for fallback deduplication
    -- (lowercase, punctuation stripped — not shown in the UI)
    _norm_title      TEXT,
    _norm_company    TEXT,

    -- Phase 2 note: generated resume/cover-letter content is stored per-application
    -- (see the applications table below), not on the job, so the same job can be
    -- re-tailored over time without overwriting history.

    UNIQUE(url)
);

-- ============================================================
-- APPLICATIONS
-- Tracks the user's personal application pipeline for jobs.
-- ============================================================
CREATE TABLE IF NOT EXISTS applications (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,

    -- Pipeline status
    status         TEXT NOT NULL DEFAULT 'saved',
    -- Valid values (in order):
    --   'saved'        → shortlisted, not yet applied
    --   'applied'      → application submitted
    --   'phone_screen' → initial recruiter/HR call scheduled or done
    --   'interview'    → technical or hiring manager interview
    --   'offer'        → offer received
    --   'rejected'     → passed or rejected
    --   'withdrawn'    → you withdrew your application

    applied_date   TEXT,                -- ISO date when you submitted the application
    follow_up_date TEXT,                -- Optional reminder date for following up
    contact_name   TEXT,                -- Recruiter or hiring manager name
    contact_email  TEXT,                -- Recruiter or hiring manager email
    notes          TEXT,                -- Free-text notes (interview prep, impressions, etc.)

    -- Phase 2 note: tailored resumes / cover letters are stored per-job in the
    -- tailored_documents table below (versioned), not on the application row.

    created_at     TEXT DEFAULT (datetime('now')),
    updated_at     TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- MASTER RESUME  (Phase 2)
-- The user's single source-of-truth resume. Set up once (upload a
-- PDF/DOCX or paste text); every tailoring run reads from it.
-- Single logical row — we upsert id = 1.
-- ============================================================
CREATE TABLE IF NOT EXISTS master_resume (
    id              INTEGER PRIMARY KEY,           -- always 1
    raw_text        TEXT NOT NULL,                 -- resume text (extracted or pasted)
    structured_json TEXT,                          -- Claude-structured sections (JSON); NULL if structuring failed
    source_filename TEXT,                          -- original filename if uploaded, else NULL
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- TAILORED DOCUMENTS  (Phase 2)
-- Version history of generated resume + cover letter per job.
-- Each row is one generation; the newest version per job is "current".
-- Keyed by job_id so a job can be tailored from Browse Jobs before it
-- ever becomes a tracked application.
-- ============================================================
CREATE TABLE IF NOT EXISTS tailored_documents (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id           INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    version          INTEGER NOT NULL,             -- 1, 2, 3… per job
    resume_md        TEXT,                         -- tailored resume (markdown)
    cover_letter_md  TEXT,                         -- tailored cover letter (markdown)
    notes            TEXT,                         -- regeneration guidance used for this version
    created_at       TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- SCRAPE RUNS
-- One row per scrape cycle. Powers the Settings page dashboard.
-- ============================================================
CREATE TABLE IF NOT EXISTS scrape_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,

    started_at     TEXT NOT NULL,       -- ISO 8601 timestamp when the run began
    finished_at    TEXT,                -- ISO 8601 timestamp when the run completed
    duration_secs  INTEGER,             -- Wall-clock seconds (finished_at - started_at)

    -- Run outcome
    status         TEXT DEFAULT 'running',
    -- Valid values:
    --   'running'  → in progress
    --   'success'  → completed with zero errors
    --   'partial'  → completed but some sources/jobs failed
    --   'failed'   → run aborted or produced no results

    -- Counters
    jobs_fetched   INTEGER DEFAULT 0,  -- Total raw listings retrieved (before dedup/extraction)
    jobs_new       INTEGER DEFAULT 0,  -- New jobs added to the database
    jobs_updated   INTEGER DEFAULT 0,  -- Existing jobs refreshed (last_seen_at updated)
    jobs_excluded  INTEGER DEFAULT 0,  -- Jobs filtered out by LLM exclusion rules
    jobs_scored    INTEGER DEFAULT 0,  -- Jobs that went through LLM extraction this run

    -- Error tracking
    errors         INTEGER DEFAULT 0,  -- Count of individual errors during the run
    error_details  TEXT                -- JSON array of error message strings
);

-- Migration: add jobs_scored to existing databases that pre-date this column.
-- SQLite ignores this if the column already exists via the IF NOT EXISTS trick
-- (we use a no-op: the ADD COLUMN only runs when the column is absent).
-- Safe to re-run on any existing DB.
CREATE TABLE IF NOT EXISTS _migrations (id INTEGER PRIMARY KEY, name TEXT UNIQUE);
INSERT OR IGNORE INTO _migrations (name) VALUES ('add_jobs_scored_to_scrape_runs');
-- The actual migration is run by init_db.py / database.py on startup.

-- ============================================================
-- INDEXES
-- Covering the most common filter and sort operations in the UI.
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_jobs_is_active       ON jobs(is_active);
CREATE INDEX IF NOT EXISTS idx_jobs_last_seen_at    ON jobs(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_jobs_company         ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_date_posted     ON jobs(date_posted);
CREATE INDEX IF NOT EXISTS idx_jobs_relevance_score ON jobs(relevance_score);
CREATE INDEX IF NOT EXISTS idx_jobs_salary_min      ON jobs(salary_min);
CREATE INDEX IF NOT EXISTS idx_jobs_employment_type ON jobs(employment_type);
CREATE INDEX IF NOT EXISTS idx_jobs_is_excluded     ON jobs(is_excluded);
CREATE INDEX IF NOT EXISTS idx_jobs_source          ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_applications_job_id  ON applications(job_id);
CREATE INDEX IF NOT EXISTS idx_applications_status  ON applications(status);
CREATE INDEX IF NOT EXISTS idx_scrape_runs_started  ON scrape_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_tailored_job          ON tailored_documents(job_id, version);
CREATE INDEX IF NOT EXISTS idx_jobs_norm_dedup      ON jobs(_norm_title, _norm_company, date_scraped);
