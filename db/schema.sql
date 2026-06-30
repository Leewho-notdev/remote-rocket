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

    -- Phase 2: Resume tailoring (columns reserved — activate with ALTER TABLE when needed)
    -- tailored_resume  TEXT,
    -- cover_letter     TEXT,
    -- resume_version   TEXT,

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

    -- Phase 2: Generated content (activate with ALTER TABLE when needed)
    -- resume_used    TEXT,             -- Which resume version was used
    -- cover_letter   TEXT,             -- Generated cover letter text

    created_at     TEXT DEFAULT (datetime('now')),
    updated_at     TEXT DEFAULT (datetime('now'))
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

    -- Error tracking
    errors         INTEGER DEFAULT 0,  -- Count of individual errors during the run
    error_details  TEXT                -- JSON array of error message strings
);

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
CREATE INDEX IF NOT EXISTS idx_jobs_norm_dedup      ON jobs(_norm_title, _norm_company, date_scraped);
