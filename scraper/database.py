"""
scraper/database.py
Database access layer for the scraper service.
Handles all write operations: inserting jobs, updating freshness,
recording scrape runs, and expiring stale listings.
"""

import sqlite3
import json
import logging
import os
from datetime import datetime

log = logging.getLogger("remote-rocket.db")

DB_PATH = os.getenv("DB_PATH", "/app/db/jobs.db")

# How many days before a job is marked inactive if not seen again.
# Applied jobs are never expired regardless of this setting.
JOB_EXPIRY_DAYS = int(os.getenv("JOB_EXPIRY_DAYS", 45))


def get_connection() -> sqlite3.Connection:
    """Return a database connection with row_factory set for dict-like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["title"] works
    conn.execute("PRAGMA journal_mode=WAL")  # allows concurrent reads while writing
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """
    Initialize the database by running schema.sql.
    Called automatically when the scraper starts.
    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS.
    """
    schema_path = "/app/db/schema.sql"
    if not os.path.exists(schema_path):
        # Fallback for local development outside Docker
        schema_path = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")

    if not os.path.exists(schema_path):
        raise FileNotFoundError(f"schema.sql not found at {schema_path}")

    with open(schema_path) as f:
        schema = f.read()

    conn = get_connection()
    try:
        conn.executescript(schema)
        # Migration: add jobs_scored if this is an older database
        cols = {row[1] for row in conn.execute("PRAGMA table_info(scrape_runs)")}
        if "jobs_scored" not in cols:
            conn.execute("ALTER TABLE scrape_runs ADD COLUMN jobs_scored INTEGER DEFAULT 0")
            conn.commit()
            log.info("Migration applied: added jobs_scored to scrape_runs")

        # Phase 2 tables (master_resume, tailored_documents) are created by the
        # executescript(schema) call above via CREATE TABLE IF NOT EXISTS — no
        # ALTER migration needed since they're new tables, not new columns.

        conn.commit()
        log.info(f"Database ready at {DB_PATH}")
    finally:
        conn.close()


# ============================================================
# JOB OPERATIONS
# ============================================================

def job_exists_by_url(conn: sqlite3.Connection, url: str) -> bool:
    """Fast path dedup check: does this exact URL already exist?"""
    row = conn.execute("SELECT id FROM jobs WHERE url = ?", (url,)).fetchone()
    return row is not None


def job_exists_by_title_company(conn: sqlite3.Connection, title: str, company: str) -> bool:
    """
    Fallback dedup check: has a job with the same normalized title + company
    been seen in the last 30 days? Catches duplicate postings with different URLs.
    """
    norm_title   = _normalize(title)
    norm_company = _normalize(company)

    row = conn.execute("""
        SELECT id FROM jobs
        WHERE _norm_title   = ?
          AND _norm_company = ?
          AND date_scraped >= date('now', '-30 days')
    """, (norm_title, norm_company)).fetchone()
    return row is not None


def insert_job(conn: sqlite3.Connection, job: dict) -> int | None:
    """
    Insert a new job row. Returns the new row ID, or None if insert was skipped.
    Handles JSON serialization for list fields automatically.
    """
    # Serialize list fields to JSON strings
    requirements    = _to_json(job.get("requirements"))
    skills_detected = _to_json(job.get("skills_detected"))

    now = datetime.utcnow().isoformat()

    try:
        cursor = conn.execute("""
            INSERT INTO jobs (
                source, external_id, url, source_url,
                title, company, location, employment_type,
                salary_min, salary_max, salary_raw, salary_currency,
                description_raw, description_clean, requirements, skills_detected,
                raw_llm_response,
                relevance_score, salary_score,
                is_fully_remote, is_hidden_gem,
                has_google_ads, has_msft_ads, has_gtm, has_gmc,
                is_excluded, exclusion_reason,
                is_active, last_seen_at,
                date_posted, date_scraped, created_at,
                _norm_title, _norm_company
            ) VALUES (
                :source, :external_id, :url, :source_url,
                :title, :company, :location, :employment_type,
                :salary_min, :salary_max, :salary_raw, :salary_currency,
                :description_raw, :description_clean, :requirements, :skills_detected,
                :raw_llm_response,
                :relevance_score, :salary_score,
                :is_fully_remote, :is_hidden_gem,
                :has_google_ads, :has_msft_ads, :has_gtm, :has_gmc,
                :is_excluded, :exclusion_reason,
                1, :now,
                :date_posted, :now, :now,
                :norm_title, :norm_company
            )
        """, {
            **job,
            "requirements":    requirements,
            "skills_detected": skills_detected,
            "now":             now,
            "norm_title":      _normalize(job.get("title", "")),
            "norm_company":    _normalize(job.get("company", "")),
        })
        conn.commit()
        return cursor.lastrowid

    except sqlite3.IntegrityError:
        # URL already exists — not an error, just a duplicate
        return None


def update_last_seen(conn: sqlite3.Connection, url: str) -> None:
    """Mark a job as still active when it appears in a new scrape."""
    conn.execute("""
        UPDATE jobs
        SET last_seen_at = datetime('now'),
            is_active    = 1,
            date_updated = datetime('now')
        WHERE url = ?
    """, (url,))
    conn.commit()


def update_job_llm_fields(conn: sqlite3.Connection, job_id: int, extracted: dict) -> None:
    """
    Update an existing job row with fields returned by LLM extraction.
    Called after extract_job_data() runs on a job that was already inserted.
    Only updates fields that the LLM populates — preserves all source fields.
    """
    conn.execute("""
        UPDATE jobs SET
            employment_type  = COALESCE(:employment_type, employment_type),
            salary_min       = COALESCE(:salary_min, salary_min),
            salary_max       = COALESCE(:salary_max, salary_max),
            salary_raw       = COALESCE(:salary_raw, salary_raw),
            description_clean = COALESCE(:description_clean, description_clean),
            requirements     = COALESCE(:requirements, requirements),
            skills_detected  = COALESCE(:skills_detected, skills_detected),
            raw_llm_response = :raw_llm_response,
            relevance_score  = :relevance_score,
            salary_score     = :salary_score,
            is_fully_remote  = :is_fully_remote,
            has_google_ads   = :has_google_ads,
            has_msft_ads     = :has_msft_ads,
            has_gtm          = :has_gtm,
            has_gmc          = :has_gmc,
            is_excluded      = :is_excluded,
            exclusion_reason = COALESCE(:exclusion_reason, exclusion_reason),
            date_updated     = datetime('now')
        WHERE id = :job_id
    """, {
        "job_id":           job_id,
        "employment_type":  extracted.get("employment_type"),
        "salary_min":       extracted.get("salary_min"),
        "salary_max":       extracted.get("salary_max"),
        "salary_raw":       extracted.get("salary_raw"),
        "description_clean": extracted.get("description_clean"),
        "requirements":     _to_json(extracted.get("requirements")),
        "skills_detected":  _to_json(extracted.get("skills_detected")),
        "raw_llm_response": extracted.get("raw_llm_response"),
        "relevance_score":  extracted.get("relevance_score"),
        "salary_score":     extracted.get("salary_score"),
        "is_fully_remote":  extracted.get("is_fully_remote", 1),
        "has_google_ads":   extracted.get("has_google_ads", 0),
        "has_msft_ads":     extracted.get("has_msft_ads", 0),
        "has_gtm":          extracted.get("has_gtm", 0),
        "has_gmc":          extracted.get("has_gmc", 0),
        "is_excluded":      extracted.get("is_excluded", 0),
        "exclusion_reason": extracted.get("exclusion_reason"),
    })
    conn.commit()


def get_unscored_jobs(conn: sqlite3.Connection, limit: int = 100) -> list:
    """
    Return jobs that haven't been through LLM extraction yet.
    Used to back-fill scores on jobs inserted without extraction.
    """
    rows = conn.execute("""
        SELECT id, title, company, description_raw, description_clean,
               is_hidden_gem, is_excluded, exclusion_reason
        FROM jobs
        WHERE relevance_score IS NULL
          AND is_active = 1
        ORDER BY is_hidden_gem DESC, date_scraped DESC
        LIMIT ?
    """, (limit,)).fetchall()
    return [dict(row) for row in rows]


def expire_stale_jobs(conn: sqlite3.Connection) -> int:
    """
    Mark jobs inactive if they haven't been seen for JOB_EXPIRY_DAYS.
    Jobs that have been applied to are never expired (preserves history).
    Returns the number of jobs marked inactive.
    """
    cursor = conn.execute(f"""
        UPDATE jobs
        SET is_active    = 0,
            date_updated = datetime('now')
        WHERE is_active = 1
          AND last_seen_at < datetime('now', '-{JOB_EXPIRY_DAYS} days')
          AND id NOT IN (SELECT DISTINCT job_id FROM applications)
    """)
    conn.commit()
    count = cursor.rowcount
    if count > 0:
        log.info(f"Expired {count} stale jobs (not seen in {JOB_EXPIRY_DAYS}+ days)")
    return count


# ============================================================
# SCRAPE RUN RECORDING
# ============================================================

def start_scrape_run(conn: sqlite3.Connection) -> int:
    """
    Insert a new scrape_runs row with status='running'.
    Returns the run ID to pass to finish_scrape_run() when done.
    """
    cursor = conn.execute(
        "INSERT INTO scrape_runs (started_at, status) VALUES (datetime('now'), 'running')"
    )
    conn.commit()
    return cursor.lastrowid


def finish_scrape_run(conn: sqlite3.Connection, run_id: int, stats: dict) -> None:
    """
    Update the scrape_runs row with final counts and status.
    stats dict keys: jobs_fetched, jobs_new, jobs_updated, jobs_excluded,
                     jobs_scored, errors, error_details (list)
    """
    status = "success"
    if stats.get("errors", 0) > 0:
        status = "partial" if stats.get("jobs_new", 0) > 0 else "failed"

    conn.execute("""
        UPDATE scrape_runs SET
            finished_at    = datetime('now'),
            duration_secs  = CAST((julianday('now') - julianday(started_at)) * 86400 AS INTEGER),
            status         = :status,
            jobs_fetched   = :jobs_fetched,
            jobs_new       = :jobs_new,
            jobs_updated   = :jobs_updated,
            jobs_excluded  = :jobs_excluded,
            jobs_scored    = :jobs_scored,
            errors         = :errors,
            error_details  = :error_details
        WHERE id = :run_id
    """, {
        "status":        status,
        "jobs_fetched":  stats.get("jobs_fetched",  0),
        "jobs_new":      stats.get("jobs_new",      0),
        "jobs_updated":  stats.get("jobs_updated",  0),
        "jobs_excluded": stats.get("jobs_excluded", 0),
        "jobs_scored":   stats.get("jobs_scored",   0),
        "errors":        stats.get("errors",        0),
        "error_details": json.dumps(stats.get("error_details", [])),
        "run_id":        run_id,
    })
    conn.commit()


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _normalize(text: str) -> str:
    """
    Lowercase, remove punctuation, collapse whitespace.
    Used for the title+company fallback dedup check.
    """
    import re
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _to_json(value) -> str | None:
    """Serialize a list to a JSON string. Pass-through for strings/None."""
    if value is None:
        return None
    if isinstance(value, list):
        return json.dumps(value)
    return value  # already a string
