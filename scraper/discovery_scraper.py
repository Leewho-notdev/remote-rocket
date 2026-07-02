"""
scraper/discovery_scraper.py
Discovers "hidden gem" job boards by searching Google for ATS URLs
matching paid search / PPC keywords. Extracts company slugs from the
results and pulls all jobs from each board via the ATS API.

This surfaces jobs from companies that never post on LinkedIn or Indeed
and that we'd never think to add to companies.yml manually.

Google scraping strategy:
- 4 site: queries per run (one per ATS platform), keywords combined into one query
- 15-second sleep between queries to stay under Google's radar
- Zero-result monitoring: if Google blocks us, every query returns 0 and we log loudly
- Falls back gracefully — discovery failures never crash the main scrape

Health monitoring signals (visible in the Settings → Scraper Log tab):
- [DISCOVERY] lines show per-query result counts
- WARNING fired if >50% of queries return 0 results (likely CAPTCHA / blocked)
- Summary line at end: boards found, boards already known, jobs fetched
"""

import logging
import os
import re
import time
import random

import requests

log = logging.getLogger("remote-rocket.discovery")

# Seconds to sleep between Google queries. Too fast = CAPTCHA.
GOOGLE_QUERY_DELAY = 15

# Seconds to sleep between ATS API calls after discovery.
ATS_CALL_DELAY = 2

# How many Google results to request per query.
GOOGLE_RESULTS_PER_QUERY = 20

# ATS platforms to search, with URL patterns for slug extraction.
ATS_TARGETS = [
    {
        "ats":     "greenhouse",
        "site":    "boards.greenhouse.io",
        "pattern": r"boards\.greenhouse\.io/([^/?#\s]+)",
    },
    {
        "ats":     "lever",
        "site":    "jobs.lever.co",
        "pattern": r"jobs\.lever\.co/([^/?#\s]+)",
    },
    {
        "ats":     "ashby",
        "site":    "jobs.ashbyhq.com",
        "pattern": r"ashbyhq\.com/([^/?#\s]+)",
    },
    {
        "ats":     "workable",
        "site":    "apply.workable.com",
        "pattern": r"apply\.workable\.com/([^/?#\s]+)",
    },
]

# Keywords combined into one OR query per ATS platform.
KEYWORD_CLAUSE = (
    '"paid search" OR "PPC" OR "paid media" OR "SEM" '
    'OR "performance marketing" OR "biddable media" OR "Google Ads"'
)


SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", "")
SCRAPINGBEE_URL     = "https://app.scrapingbee.com/api/v1/"


def _google_search(query: str, num_results: int = 20) -> list[str]:
    """
    Search Google via ScrapingBee (if key set) or googlesearch-python fallback.
    Returns a list of result URLs.
    """
    if SCRAPINGBEE_API_KEY:
        # ScrapingBee scrapes a URL — pass the Google search URL directly
        google_url = (
            "https://www.google.com/search?q="
            + requests.utils.quote(query)
            + f"&num={num_results}&hl=en&gl=us"
        )
        resp = requests.get(
            SCRAPINGBEE_URL,
            params={
                "api_key": SCRAPINGBEE_API_KEY,
                "url":     google_url,
                "extract_rules": '{"urls":{"selector":"a[href]","type":"list","output":"@href"}}',
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        raw_urls = data.get("urls", []) or []
        # Keep only external result links — drop Google navigation and internal URLs
        return [u for u in raw_urls if u.startswith("http") and "google.com" not in u]
    else:
        try:
            from googlesearch import search as google_search
            return list(google_search(query, num_results=num_results, sleep_interval=2))
        except ImportError:
            log.error("[DISCOVERY] No search backend available. Set SCRAPINGBEE_API_KEY or install googlesearch-python.")
            return []


def run_discovery(existing_slugs: dict | None = None) -> list[dict]:
    """
    Main entry point. Searches Google for ATS job board URLs matching
    paid search keywords, then fetches all jobs from each discovered board.

    existing_slugs: dict of {ats_type: set(slug)} already covered by
    companies.yml — used for logging "already known" vs "newly discovered".
    Returns a flat list of job dicts ready for the main pipeline.

    Never raises — all errors are caught and logged.
    """
    if existing_slugs is None:
        existing_slugs = {}

    if SCRAPINGBEE_API_KEY:
        log.info("[DISCOVERY] Using ScrapingBee for Google searches")
    else:
        log.warning("[DISCOVERY] SCRAPINGBEE_API_KEY not set — using googlesearch-python (may be blocked by VPS IP)")

    all_jobs      = []
    total_queries = 0
    zero_results  = 0
    boards_found  = set()

    for target in ATS_TARGETS:
        ats     = target["ats"]
        site    = target["site"]
        pattern = target["pattern"]
        query   = f'site:{site} {KEYWORD_CLAUSE} remote'

        log.info(f"[DISCOVERY] Searching Google: {query}")
        total_queries += 1

        try:
            results = _google_search(query, num_results=GOOGLE_RESULTS_PER_QUERY)
        except Exception as e:
            log.warning(f"[DISCOVERY] Google search failed for {site}: {e}")
            results = []

        if not results:
            zero_results += 1
            log.warning(
                f"[DISCOVERY] 0 results for {site} — "
                f"Google may be rate-limiting or blocking this query."
            )
        else:
            log.info(f"[DISCOVERY] {site} → {len(results)} URLs returned")

        # Extract unique slugs from result URLs
        slugs_this_query = set()
        for url in results:
            m = re.search(pattern, url, re.IGNORECASE)
            if m:
                slug = m.group(1).lower().strip("/")
                # Skip generic/noise slugs
                if slug and slug not in ("jobs", "careers", "apply", "j", "o"):
                    slugs_this_query.add(slug)

        log.info(f"[DISCOVERY] {site} → {len(slugs_this_query)} unique board slugs extracted")

        # Fetch jobs from each newly discovered board
        for slug in slugs_this_query:
            key = (ats, slug)
            if key in boards_found:
                continue   # already fetched this board in a previous query
            boards_found.add(key)

            known = slug in existing_slugs.get(ats, set())
            label = "known" if known else "NEW"
            log.info(f"[DISCOVERY]   [{label}] {ats}/{slug}")

            try:
                jobs = _fetch_board(ats, slug)
                if jobs:
                    log.info(f"[DISCOVERY]   → {len(jobs)} jobs fetched from {ats}/{slug}")
                    all_jobs.extend(jobs)
                else:
                    log.info(f"[DISCOVERY]   → 0 jobs from {ats}/{slug} (empty or filtered)")
                time.sleep(ATS_CALL_DELAY)
            except Exception as e:
                log.warning(f"[DISCOVERY]   → Failed to fetch {ats}/{slug}: {e}")

        # Polite delay between Google queries (skip after last one)
        if target != ATS_TARGETS[-1]:
            delay = GOOGLE_QUERY_DELAY + random.uniform(0, 5)
            log.info(f"[DISCOVERY] Waiting {delay:.0f}s before next Google query …")
            time.sleep(delay)

    # ── Health check ──────────────────────────────────────────────────────────
    if total_queries > 0 and zero_results / total_queries > 0.5:
        log.warning(
            f"[DISCOVERY] ⚠️  HEALTH WARNING: {zero_results}/{total_queries} queries returned "
            f"0 results. Google is likely rate-limiting or CAPTCHAing requests. "
            f"Consider switching to ScrapingBee (set SCRAPINGBEE_API_KEY in .env)."
        )
    else:
        log.info(
            f"[DISCOVERY] Complete — {len(boards_found)} boards found across "
            f"{total_queries} queries, {len(all_jobs)} total jobs fetched."
        )

    return all_jobs


def _fetch_board(ats: str, slug: str) -> list[dict]:
    """
    Fetch all jobs from a single ATS board.
    Returns job dicts compatible with the main pipeline.
    Imports career_page_scraper fetchers to avoid code duplication.
    """
    from career_page_scraper import (
        fetch_greenhouse, fetch_lever, fetch_ashby, fetch_workable,
    )

    # Minimal company dict — name will be overridden by LLM extraction
    company = {"name": slug, "careers_url": f"https://{ats}/{slug}"}

    if ats == "greenhouse":
        return fetch_greenhouse(company, slug)
    elif ats == "lever":
        return fetch_lever(company, slug)
    elif ats == "ashby":
        return fetch_ashby(company, slug)
    elif ats == "workable":
        return fetch_workable(company, slug)
    return []


def build_existing_slugs(companies: list[dict]) -> dict:
    """
    Build a {ats_type: set(slug)} map from the companies.yml watchlist
    so discovery can log which boards are already known vs newly found.
    """
    from career_page_scraper import detect_ats
    result = {}
    for company in companies:
        ats_type, slug = detect_ats(company)
        if slug:
            result.setdefault(ats_type, set()).add(slug.lower())
    return result
