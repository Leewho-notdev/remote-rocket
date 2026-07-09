"""
scraper/discovery_scraper.py
Discovers "hidden gem" job boards by searching for ATS URLs matching
paid search / PPC keywords. Extracts company slugs from results and
pulls all jobs from each board via the ATS API.

This surfaces jobs from companies that never post on LinkedIn or Indeed
and that we'd never think to add to companies.yml manually.

Search strategy:
- 4 site: queries per run (one per ATS platform), keywords combined into one query
- Uses Brave Search API (BRAVE_API_KEY) — real REST API, no scraping, free tier
- 2-second sleep between queries (polite, not required)
- Zero-result monitoring: if queries fail, we log loudly
- Falls back gracefully — discovery failures never crash the main scrape

Health monitoring signals (visible in the Settings → Scraper Log tab):
- [DISCOVERY] lines show per-query result counts
- WARNING fired if >50% of queries return 0 results
- Summary line at end: boards found, boards already known, jobs fetched
"""

import logging
import os
import re
import time
import random

import requests

log = logging.getLogger("remote-rocket.discovery")

# Seconds to sleep between search queries.
QUERY_DELAY = 2

# Seconds to sleep between ATS API calls after discovery.
ATS_CALL_DELAY = 2

# How many search results to request per query.
SEARCH_RESULTS_PER_QUERY = 20

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


BRAVE_API_KEY  = os.getenv("BRAVE_API_KEY", "")
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


def _search(query: str, num_results: int = 20) -> list[str]:
    """
    Search via Brave Search API. Returns a list of result URLs.
    Brave API returns up to 20 results per call on the free plan.
    """
    if not BRAVE_API_KEY:
        log.error("[DISCOVERY] BRAVE_API_KEY not set — cannot run discovery.")
        return []
    resp = requests.get(
        BRAVE_SEARCH_URL,
        headers={
            "Accept":               "application/json",
            "Accept-Encoding":      "gzip",
            "X-Subscription-Token": BRAVE_API_KEY,
        },
        params={
            "q":      query,
            "count":  min(num_results, 20),
            "search_lang": "en",
            "country":     "us",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("web", {}).get("results", [])
    return [r["url"] for r in results if r.get("url")]


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

    if not BRAVE_API_KEY:
        log.error("[DISCOVERY] BRAVE_API_KEY not set — skipping discovery.")
        return []
    log.info("[DISCOVERY] Using Brave Search API")

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
            results = _search(query, num_results=SEARCH_RESULTS_PER_QUERY)
        except Exception as e:
            log.warning(f"[DISCOVERY] Search failed for {site}: {e}")
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

        # Polite delay between queries
        if target != ATS_TARGETS[-1]:
            time.sleep(QUERY_DELAY)

    # ── Health check ──────────────────────────────────────────────────────────
    if total_queries > 0 and zero_results / total_queries > 0.5:
        log.warning(
            f"[DISCOVERY] ⚠️  HEALTH WARNING: {zero_results}/{total_queries} queries returned "
            f"0 results. Check BRAVE_API_KEY and account credits at api.search.brave.com."
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
