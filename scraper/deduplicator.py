"""
scraper/deduplicator.py
Deduplication logic for the scraper pipeline.

Strategy (two-pass, in order):
  1. URL match       — exact match on the job's apply/listing URL (fast, indexed)
  2. Title + company — normalized text match within the last 30 days (catches
                       the same job posted with different URLs across boards)

If either check hits, the job is a duplicate. If it's a URL duplicate, we call
update_last_seen() to refresh its freshness timestamp. Title+company duplicates
are simply skipped — we already have the job from a different source.
"""

import logging
import sqlite3

from database import (
    job_exists_by_url,
    job_exists_by_title_company,
    update_last_seen,
)

log = logging.getLogger("remote-rocket.dedup")


def check_and_handle_duplicate(conn: sqlite3.Connection, job: dict) -> bool:
    """
    Check whether a job is a duplicate. Updates freshness if it is.
    Returns True if the job should be SKIPPED (it's a duplicate).
    Returns False if the job is NEW and should be inserted.
    """
    url     = job.get("url", "")
    title   = job.get("title", "")
    company = job.get("company", "")

    # --- Pass 1: Exact URL match ---
    if url and job_exists_by_url(conn, url):
        log.debug(f"Duplicate URL — refreshing freshness: {url[:80]}")
        update_last_seen(conn, url)
        return True   # skip insert

    # --- Pass 2: Normalized title + company (30-day window) ---
    if title and company and job_exists_by_title_company(conn, title, company):
        log.debug(f"Duplicate title+company — skipping: '{title}' @ {company}")
        return True   # skip insert

    return False  # new job — proceed with insert


def should_pre_exclude(job: dict, title_exclusions: list[str]) -> tuple[bool, str]:
    """
    Pre-screen a job against title exclusion keywords BEFORE sending to the LLM.
    This saves Claude API cost on obvious non-matches (social media, SEO-only, etc.).

    Returns (should_exclude: bool, reason: str).
    """
    title_lower = job.get("title", "").lower()

    for phrase in title_exclusions:
        if phrase.lower() in title_lower:
            return True, f"Title contains excluded phrase: '{phrase}'"

    return False, ""
