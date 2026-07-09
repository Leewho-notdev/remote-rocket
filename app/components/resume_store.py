"""
app/components/resume_store.py
Phase 2 data layer for resume tailoring.

Two concerns:
  1. The single master resume (`master_resume`, upserted at id = 1).
  2. Versioned tailored documents per job (`tailored_documents`).

Reuses the shared connection + DB_PATH from components.db. Includes a
self-healing schema check so the feature works even if the scraper container
hasn't restarted to run its own migration yet.
"""

from components.db import get_connection

_schema_ready = False


def ensure_phase2_schema() -> None:
    """
    Idempotently create the Phase 2 tables. Mirrors db/schema.sql so the app is
    self-sufficient even before the scraper container restarts.
    """
    global _schema_ready
    if _schema_ready:
        return

    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS master_resume (
                id              INTEGER PRIMARY KEY,
                raw_text        TEXT NOT NULL,
                structured_json TEXT,
                source_filename TEXT,
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            )
        """)
        # Migration for any dev DB created before structured_json existed.
        mr_cols = {row[1] for row in conn.execute("PRAGMA table_info(master_resume)")}
        if "structured_json" not in mr_cols:
            conn.execute("ALTER TABLE master_resume ADD COLUMN structured_json TEXT")
        if "master_docx" not in mr_cols:
            conn.execute("ALTER TABLE master_resume ADD COLUMN master_docx BLOB")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tailored_documents (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id           INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                version          INTEGER NOT NULL,
                resume_md        TEXT,
                cover_letter_md  TEXT,
                notes            TEXT,
                created_at       TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tailored_job "
            "ON tailored_documents(job_id, version)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS followup_emails (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id        INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                followup_num  INTEGER NOT NULL,
                draft_text    TEXT,
                contact_email TEXT,
                sent_at       TEXT,
                created_at    TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_followup_job "
            "ON followup_emails(job_id)"
        )
        conn.commit()
        _schema_ready = True
    finally:
        conn.close()


# ── Follow-up email history ────────────────────────────────────────────────────

def save_followup(job_id: int, followup_num: int, draft_text: str,
                  contact_email: str = "") -> int:
    ensure_phase2_schema()
    conn = get_connection()
    try:
        cur = conn.execute("""
            INSERT INTO followup_emails (job_id, followup_num, draft_text, contact_email)
            VALUES (?, ?, ?, ?)
        """, (job_id, followup_num, draft_text, contact_email))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_followups(job_id: int) -> list:
    ensure_phase2_schema()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT id, followup_num, draft_text, contact_email, sent_at, created_at
            FROM followup_emails
            WHERE job_id = ?
            ORDER BY followup_num ASC
        """, (job_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def followup_count_by_job(job_ids: list) -> dict:
    """Return {job_id: count} for a list of job ids."""
    if not job_ids:
        return {}
    ensure_phase2_schema()
    conn = get_connection()
    try:
        placeholders = ",".join("?" * len(job_ids))
        rows = conn.execute(
            f"SELECT job_id, COUNT(*) FROM followup_emails WHERE job_id IN ({placeholders}) GROUP BY job_id",
            job_ids,
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        conn.close()


# ── Master resume ──────────────────────────────────────────────────────────────

def get_master_resume() -> dict | None:
    """Return the master resume row, or None if not set up yet."""
    ensure_phase2_schema()
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM master_resume WHERE id = 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def has_master_resume() -> bool:
    m = get_master_resume()
    return bool(m and (m.get("raw_text") or "").strip())


def save_master_resume(raw_text: str, structured_json: str | None = None,
                       source_filename: str | None = None,
                       master_docx: bytes | None = None) -> None:
    """Upsert the single master resume row (id = 1)."""
    ensure_phase2_schema()
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO master_resume (id, raw_text, structured_json, source_filename, master_docx)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                raw_text        = excluded.raw_text,
                structured_json = excluded.structured_json,
                source_filename = excluded.source_filename,
                master_docx     = COALESCE(excluded.master_docx, master_resume.master_docx),
                updated_at      = datetime('now')
        """, (raw_text, structured_json, source_filename, master_docx))
        conn.commit()
    finally:
        conn.close()


# ── Tailored documents (versioned per job) ─────────────────────────────────────

def add_tailored_version(job_id: int, resume_md: str, cover_letter_md: str,
                         notes: str = "") -> int:
    """
    Save a new tailored version for a job. Version numbers auto-increment
    per job. Returns the new version number.
    """
    ensure_phase2_schema()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM tailored_documents WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        next_version = (row[0] or 0) + 1
        conn.execute("""
            INSERT INTO tailored_documents
                (job_id, version, resume_md, cover_letter_md, notes)
            VALUES (?, ?, ?, ?, ?)
        """, (job_id, next_version, resume_md, cover_letter_md, notes))
        conn.commit()
        return next_version
    finally:
        conn.close()


def get_latest_tailored(job_id: int) -> dict | None:
    """Return the newest tailored version for a job, or None."""
    ensure_phase2_schema()
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT * FROM tailored_documents
            WHERE job_id = ?
            ORDER BY version DESC
            LIMIT 1
        """, (job_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_tailored_versions(job_id: int) -> list:
    """Return all tailored versions for a job, newest first."""
    ensure_phase2_schema()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT id, version, resume_md, cover_letter_md, notes, created_at
            FROM tailored_documents
            WHERE job_id = ?
            ORDER BY version DESC
        """, (job_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_tailored_content(doc_id: int, resume_md: str, cover_letter_md: str) -> None:
    """Persist inline edits to an existing tailored version (no new version)."""
    ensure_phase2_schema()
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE tailored_documents
            SET resume_md = ?, cover_letter_md = ?
            WHERE id = ?
        """, (resume_md, cover_letter_md, doc_id))
        conn.commit()
    finally:
        conn.close()


def jobs_with_tailoring() -> set:
    """Return the set of job_ids that have at least one tailored version."""
    ensure_phase2_schema()
    conn = get_connection()
    try:
        rows = conn.execute("SELECT DISTINCT job_id FROM tailored_documents").fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()
