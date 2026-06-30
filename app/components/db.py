"""
app/components/db.py
Database access layer for the Streamlit UI.
Read-heavy: fetches jobs, applications, and scrape run history.
Write operations are limited to application tracking (status, notes).
"""

import sqlite3
import json
import os

DB_PATH = os.getenv("DB_PATH", "/app/db/jobs.db")


def get_connection() -> sqlite3.Connection:
    """Return a read/write connection with dict-like row access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ============================================================
# JOB QUERIES
# ============================================================

def get_jobs(
    min_salary: int         = 0,
    employment_types: list  = None,
    sources: list           = None,    # ['jobspy', 'career_page'] or None for all
    days_posted: int        = None,    # None = no date filter
    min_score: int          = 0,
    keywords: str           = "",      # searched in title + company
    has_google_ads: bool    = False,
    has_msft_ads: bool      = False,
    has_gtm: bool           = False,
    has_gmc: bool           = False,
    include_excluded: bool  = False,
    include_inactive: bool  = False,
    sort_by: str            = "relevance_score",
    limit: int              = 200,
) -> list:
    """
    Fetch jobs with optional filters. All filters are additive (AND logic).
    Returns a list of dicts, one per job.
    """
    conn = get_connection()
    conditions = []
    params     = []

    # Active / excluded guards (on by default)
    if not include_inactive:
        conditions.append("j.is_active = 1")
    if not include_excluded:
        conditions.append("j.is_excluded = 0")

    # Salary
    if min_salary > 0:
        conditions.append("(j.salary_min IS NULL OR j.salary_min >= ?)")
        params.append(min_salary)

    # Employment type
    if employment_types:
        placeholders = ",".join("?" * len(employment_types))
        conditions.append(f"j.employment_type IN ({placeholders})")
        params.extend(employment_types)

    # Source
    if sources:
        if "career_page" in sources and "jobspy" not in sources:
            conditions.append("j.is_hidden_gem = 1")
        elif "jobspy" in sources and "career_page" not in sources:
            conditions.append("j.is_hidden_gem = 0")
        # Both selected = no filter

    # Date posted
    if days_posted:
        conditions.append("j.date_posted >= date('now', ?)")
        params.append(f"-{days_posted} days")

    # Relevance score
    if min_score > 0:
        conditions.append("j.relevance_score >= ?")
        params.append(min_score)

    # Keyword search in title + company
    if keywords.strip():
        conditions.append("(j.title LIKE ? OR j.company LIKE ?)")
        kw = f"%{keywords.strip()}%"
        params.extend([kw, kw])

    # Skill flags
    if has_google_ads:
        conditions.append("j.has_google_ads = 1")
    if has_msft_ads:
        conditions.append("j.has_msft_ads = 1")
    if has_gtm:
        conditions.append("j.has_gtm = 1")
    if has_gmc:
        conditions.append("j.has_gmc = 1")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Whitelist sort columns to prevent SQL injection
    safe_sorts = {"relevance_score", "date_posted", "salary_min", "date_scraped", "company"}
    order_col  = sort_by if sort_by in safe_sorts else "relevance_score"

    query = f"""
        SELECT
            j.*,
            a.status AS application_status,
            a.id     AS application_id
        FROM jobs j
        LEFT JOIN applications a ON a.job_id = j.id
        {where}
        ORDER BY j.{order_col} DESC
        LIMIT ?
    """
    params.append(limit)

    try:
        rows = conn.execute(query, params).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def get_job_by_id(job_id: int) -> dict:
    """Fetch a single job by its database ID."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def get_job_counts() -> dict:
    """Return aggregate counts for the UI header."""
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT
                COUNT(*)                                             AS total,
                SUM(CASE WHEN is_active = 1
                         AND is_excluded = 0 THEN 1 END)            AS active,
                SUM(CASE WHEN is_hidden_gem = 1
                         AND is_active = 1
                         AND is_excluded = 0 THEN 1 END)            AS hidden_gems,
                SUM(CASE WHEN has_google_ads = 1
                         AND is_active = 1
                         AND is_excluded = 0 THEN 1 END)            AS google_ads_roles
            FROM jobs
        """).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


# ============================================================
# APPLICATION TRACKING
# ============================================================

def get_applications(status: str = None) -> list:
    """
    Fetch applications joined with job details.
    Pass a status string to filter (e.g. 'applied'), or None for all.
    """
    conn  = get_connection()
    where  = "WHERE a.status = ?" if status else ""
    params = [status] if status else []
    try:
        rows = conn.execute(f"""
            SELECT
                a.*,
                j.title, j.company, j.url,
                j.salary_min, j.salary_max,
                j.employment_type, j.relevance_score
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            {where}
            ORDER BY a.updated_at DESC
        """, params).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def upsert_application(job_id: int, status: str, notes: str = "") -> int:
    """
    Create or update an application for a job.
    Returns the application ID.
    """
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE applications
                SET status = ?, notes = ?, updated_at = datetime('now')
                WHERE job_id = ?
            """, (status, notes, job_id))
            app_id = existing["id"]
        else:
            cursor = conn.execute("""
                INSERT INTO applications (job_id, status, notes)
                VALUES (?, ?, ?)
            """, (job_id, status, notes))
            app_id = cursor.lastrowid

        conn.commit()
        return app_id
    finally:
        conn.close()


def update_application_field(app_id: int, field: str, value: str) -> None:
    """Update a single field on an application row."""
    safe_fields = {"status", "notes", "applied_date", "follow_up_date",
                   "contact_name", "contact_email"}
    if field not in safe_fields:
        raise ValueError(f"Cannot update field: {field}")
    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE applications SET {field} = ?, updated_at = datetime('now') WHERE id = ?",
            (value, app_id)
        )
        conn.commit()
    finally:
        conn.close()


# ============================================================
# SCRAPE HISTORY (for Settings page)
# ============================================================

def get_recent_scrape_runs(limit: int = 10) -> list:
    """Return the most recent scrape runs for the Settings page dashboard."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT * FROM scrape_runs
            ORDER BY started_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        results = []
        for row in rows:
            d = _row_to_dict(row)
            if d.get("error_details"):
                try:
                    d["error_details"] = json.loads(d["error_details"])
                except (json.JSONDecodeError, TypeError):
                    d["error_details"] = []
            results.append(d)
        return results
    finally:
        conn.close()


def get_last_successful_run() -> dict:
    """Return the most recent successful scrape run, or None."""
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT * FROM scrape_runs
            WHERE status = 'success'
            ORDER BY started_at DESC
            LIMIT 1
        """).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain dict, deserializing JSON list fields."""
    if row is None:
        return None
    d = dict(row)
    for field in ("requirements", "skills_detected"):
        if d.get(field) and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = []
    return d
