"""
scraper/main.py
Orchestrates the full Remote Rocket scrape cycle.

Phase 1 (Steps 3–4): JobSpy only — no LLM extraction yet.
Phase 1 (Step 5):    Adds Crawl4AI + Claude extraction.
Phase 1 (Step 6):    Adds scheduler integration.

Run manually inside Docker:
    docker exec remote-rocket-scraper python main.py

Or from the repo root (requires local Python env with dependencies):
    cd scraper && python main.py
"""

import logging
import os
import sys

# Ensure the scraper directory is on the path when running directly
sys.path.insert(0, os.path.dirname(__file__))

from config_validator import load_keywords, load_companies
from database import (
    init_db,
    get_connection,
    insert_job,
    expire_stale_jobs,
    start_scrape_run,
    finish_scrape_run,
)
from deduplicator import check_and_handle_duplicate, should_pre_exclude
from jobspy_scraper import fetch_jobs

# ── Logging ─────────────────────────────────────────────────────────────────
# Writes to both the log file (for persistence) and stdout (for docker logs).
LOG_LEVEL  = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE   = "/app/logs/scraper.log"

os.makedirs("/app/logs", exist_ok=True)

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("remote-rocket.main")


# ── Main entry point ─────────────────────────────────────────────────────────

def run_scrape() -> dict:
    """
    Execute one full scrape cycle:
      1. Validate config
      2. Fetch jobs from job boards (JobSpy)
      3. Deduplicate and insert new jobs
      4. Pre-exclude obvious non-matches by title
      5. Expire stale jobs
      6. Record the run in scrape_runs

    Returns the stats dict (useful for the scheduler to log summaries).
    """
    log.info("=" * 60)
    log.info("Remote Rocket scrape starting")
    log.info("=" * 60)

    # ── 1. Load and validate config ───────────────────────────────────────────
    keywords  = load_keywords()
    companies = load_companies()  # Loaded here; used in Step 5 for career pages

    search_terms      = keywords["search_terms"]
    title_exclusions  = keywords["title_exclusions"]

    # ── 2. Open DB and start run record ───────────────────────────────────────
    conn   = get_connection()
    run_id = start_scrape_run(conn)
    log.info(f"Scrape run #{run_id} started")

    stats = {
        "jobs_fetched":  0,
        "jobs_new":      0,
        "jobs_updated":  0,   # = last_seen_at refreshed (URL duplicate found again)
        "jobs_excluded": 0,   # = pre-excluded by title keyword
        "errors":        0,
        "error_details": [],
    }

    try:
        # ── 3. Fetch from job boards ──────────────────────────────────────────
        log.info(f"Fetching from job boards ({len(search_terms)} search terms) …")
        raw_jobs = fetch_jobs(search_terms)
        stats["jobs_fetched"] = len(raw_jobs)
        log.info(f"Fetched {len(raw_jobs)} raw listings from job boards")

        # ── 4. Process each job ───────────────────────────────────────────────
        for job in raw_jobs:
            try:
                _process_job(conn, job, title_exclusions, stats)
            except Exception as e:
                msg = f"Failed to process job '{job.get('title', '?')}' @ {job.get('company', '?')}: {e}"
                log.error(msg)
                stats["errors"]        += 1
                stats["error_details"].append(msg)

        # ── 5. Expire stale jobs ──────────────────────────────────────────────
        expired = expire_stale_jobs(conn)
        if expired:
            log.info(f"Marked {expired} stale jobs inactive")

    except Exception as e:
        # Catch-all for unexpected failures (e.g. DB offline, config load crash)
        msg = f"Scrape run aborted: {e}"
        log.exception(msg)
        stats["errors"]        += 1
        stats["error_details"].append(msg)

    finally:
        # Always record the run outcome, even if we crashed mid-way
        finish_scrape_run(conn, run_id, stats)
        conn.close()

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("=" * 60)
    log.info(
        f"Run #{run_id} complete — "
        f"fetched: {stats['jobs_fetched']}, "
        f"new: {stats['jobs_new']}, "
        f"refreshed: {stats['jobs_updated']}, "
        f"excluded: {stats['jobs_excluded']}, "
        f"errors: {stats['errors']}"
    )
    log.info("=" * 60)

    return stats


def _process_job(
    conn,
    job: dict,
    title_exclusions: list[str],
    stats: dict,
) -> None:
    """
    Process a single raw job dict:
      - Pre-exclude by title keyword
      - Deduplicate
      - Insert if new

    Mutates stats in place. Raises on unexpected errors (caller handles).
    """
    # Pre-exclude by title keyword (saves LLM cost in Step 5)
    excluded, reason = should_pre_exclude(job, title_exclusions)
    if excluded:
        log.debug(f"Pre-excluded: '{job['title']}' — {reason}")
        # Still insert excluded jobs so they're visible in the DB
        # with is_excluded=1, rather than being silently dropped.
        job["is_excluded"]     = 1
        job["exclusion_reason"] = reason
        stats["jobs_excluded"] += 1

    # Deduplication — handles URL refresh internally
    is_dup = check_and_handle_duplicate(conn, job)
    if is_dup:
        if not excluded:
            # URL duplicate means we refreshed last_seen_at
            stats["jobs_updated"] += 1
        return  # don't insert again

    # New job — insert it
    job_id = insert_job(conn, job)
    if job_id:
        log.info(
            f"New job #{job_id}: '{job['title']}' @ {job['company']}"
            + (f" [EXCLUDED: {reason}]" if excluded else "")
        )
        if not excluded:
            stats["jobs_new"] += 1
    # If job_id is None, the UNIQUE constraint caught a race condition — ignore


# ── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Initialize the database (safe to call even if already initialized)
    init_db()
    run_scrape()
