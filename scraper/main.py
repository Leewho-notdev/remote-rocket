"""
scraper/main.py
Orchestrates the full Remote Rocket scrape cycle.

Pipeline order:
  1. Load and validate config
  2. Fetch from job boards (JobSpy)
  3. Fetch from company career pages (Crawl4AI)
  4. Deduplicate and insert new jobs
  5. Run LLM extraction on new + unscored jobs
  6. Expire stale jobs
  7. Record run stats

Run manually inside Docker:
    docker exec remote-rocket-scraper python main.py
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from config_validator import load_keywords, load_companies
from database import (
    init_db,
    get_connection,
    insert_job,
    update_job_llm_fields,
    get_unscored_jobs,
    expire_stale_jobs,
    start_scrape_run,
    finish_scrape_run,
)
from deduplicator import check_and_handle_duplicate, should_pre_exclude
from jobspy_scraper import fetch_jobs
from career_page_scraper import run_career_page_scrape, extract_jobs_from_page
from llm_extractor import extract_job_data, should_extract

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE  = "/app/logs/scraper.log"

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


# ── Main entry point ──────────────────────────────────────────────────────────

def run_scrape() -> dict:
    """
    Execute one full scrape cycle. Returns the stats dict.
    Every error is caught per-job/per-source — nothing crashes the whole run.
    """
    log.info("=" * 60)
    log.info("Remote Rocket scrape starting")
    log.info("=" * 60)

    # ── Config ────────────────────────────────────────────────────────────────
    keywords         = load_keywords()
    companies        = load_companies()
    search_terms     = keywords["search_terms"]
    title_exclusions = keywords["title_exclusions"]

    # ── DB + run record ───────────────────────────────────────────────────────
    conn   = get_connection()
    run_id = start_scrape_run(conn)
    log.info(f"Scrape run #{run_id} started")

    stats = {
        "jobs_fetched":   0,
        "jobs_new":       0,
        "jobs_updated":   0,
        "jobs_excluded":  0,
        "jobs_scored":    0,   # Jobs that went through LLM extraction this run
        "errors":         0,
        "error_details":  [],
    }

    # Collect newly inserted job IDs for LLM extraction pass
    new_job_ids: list[tuple[int, dict]] = []   # (db_id, job_dict)

    try:
        # ── Step A: Job board scraping (JobSpy) ───────────────────────────────
        log.info(f"[JobSpy] Fetching from {len(search_terms)} search terms …")
        try:
            board_jobs = fetch_jobs(search_terms)
            stats["jobs_fetched"] += len(board_jobs)
            log.info(f"[JobSpy] {len(board_jobs)} raw listings returned")
        except Exception as e:
            _log_error(stats, f"[JobSpy] Fetch failed entirely: {e}")
            board_jobs = []

        for job in board_jobs:
            _process_raw_job(conn, job, title_exclusions, stats, new_job_ids)

        # ── Step B: Career page scraping (Crawl4AI) ───────────────────────────
        log.info(f"[Career Pages] Starting career page scrape …")
        try:
            page_results = run_career_page_scrape(companies)
        except Exception as e:
            _log_error(stats, f"[Career Pages] Scrape failed entirely: {e}")
            page_results = []

        for page_result in page_results:
            try:
                career_jobs = extract_jobs_from_page(page_result)
                stats["jobs_fetched"] += len(career_jobs)
                for job in career_jobs:
                    _process_raw_job(conn, job, title_exclusions, stats, new_job_ids)
            except Exception as e:
                company = page_result.get("company", "?")
                _log_error(stats, f"[Career Pages] Failed to process {company}: {e}")

        # ── Step C: LLM extraction on new jobs ────────────────────────────────
        log.info(f"[LLM] Running extraction on {len(new_job_ids)} new job(s) …")
        for job_id, job_dict in new_job_ids:
            _run_extraction(conn, job_id, job_dict, stats)

        # ── Step D: Back-fill extraction on any unscored existing jobs ────────
        # This catches jobs inserted in a previous run before extraction existed.
        unscored = get_unscored_jobs(conn, limit=50)
        if unscored:
            log.info(f"[LLM] Back-filling {len(unscored)} previously unscored job(s) …")
            for row in unscored:
                job_id   = row["id"]
                job_dict = dict(row)
                _run_extraction(conn, job_id, job_dict, stats)

        # ── Step E: Expire stale jobs ─────────────────────────────────────────
        expired = expire_stale_jobs(conn)
        if expired:
            log.info(f"[Expiry] Marked {expired} stale job(s) inactive")

    except Exception as e:
        msg = f"Scrape run aborted with unexpected error: {e}"
        log.exception(msg)
        stats["errors"]       += 1
        stats["error_details"].append(msg)

    finally:
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
        f"scored: {stats['jobs_scored']}, "
        f"errors: {stats['errors']}"
    )
    log.info("=" * 60)

    return stats


# ── Per-job processing helpers ────────────────────────────────────────────────

def _process_raw_job(
    conn,
    job: dict,
    title_exclusions: list[str],
    stats: dict,
    new_job_ids: list,
) -> None:
    """
    Deduplicate, optionally pre-exclude, and insert a single raw job.
    Appends (job_id, job_dict) to new_job_ids if inserted successfully.
    Mutates stats in place.
    """
    try:
        # Pre-exclude by title keyword before touching the DB or LLM
        excluded, reason = should_pre_exclude(job, title_exclusions)
        if excluded:
            log.debug(f"Pre-excluded: '{job.get('title')}' — {reason}")
            job["is_excluded"]      = 1
            job["exclusion_reason"] = reason
            stats["jobs_excluded"] += 1

        # Deduplication — updates last_seen_at on URL hits
        is_dup = check_and_handle_duplicate(conn, job)
        if is_dup:
            if not excluded:
                stats["jobs_updated"] += 1
            return

        # New job — insert it
        job_id = insert_job(conn, job)
        if job_id:
            source_label = "💎 career page" if job.get("is_hidden_gem") else "job board"
            log.info(
                f"New job #{job_id} [{source_label}]: "
                f"'{job.get('title')}' @ {job.get('company')}"
                + (f" [EXCLUDED: {reason}]" if excluded else "")
            )
            if not excluded:
                stats["jobs_new"] += 1
                # Queue for LLM extraction (excluded jobs don't need scoring)
                new_job_ids.append((job_id, job))

    except Exception as e:
        _log_error(
            stats,
            f"Failed to process '{job.get('title', '?')}' @ {job.get('company', '?')}: {e}",
        )


def _run_extraction(conn, job_id: int, job_dict: dict, stats: dict) -> None:
    """
    Run LLM extraction on a single job and save the results to the DB.
    Skips jobs that don't need extraction (already scored, pre-excluded by title).
    Mutates stats in place.
    """
    if not should_extract(job_dict):
        return

    try:
        enriched = extract_job_data(job_dict)

        # Only update if we got a relevance score back (extraction succeeded)
        if enriched.get("relevance_score") is not None:
            update_job_llm_fields(conn, job_id, enriched)
            stats["jobs_scored"] += 1

            score   = enriched.get("relevance_score", "?")
            title   = enriched.get("title") or job_dict.get("title", "?")
            company = enriched.get("company") or job_dict.get("company", "?")
            excluded_flag = " [EXCLUDED]" if enriched.get("is_excluded") else ""
            log.info(f"  Scored #{job_id}: '{title}' @ {company} — {score}/10{excluded_flag}")
        else:
            log.warning(
                f"  Extraction returned no score for job #{job_id} "
                f"'{job_dict.get('title', '?')}' — will retry next run"
            )

    except Exception as e:
        _log_error(
            stats,
            f"LLM extraction failed for job #{job_id} "
            f"'{job_dict.get('title', '?')}': {e}",
        )


def _log_error(stats: dict, message: str) -> None:
    """Log an error and record it in the stats dict."""
    log.error(message)
    stats["errors"]       += 1
    stats["error_details"].append(message)


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    run_scrape()
