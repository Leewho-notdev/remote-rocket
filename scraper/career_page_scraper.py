"""
scraper/career_page_scraper.py
Fetches "hidden gem" jobs directly from company ATS (Applicant Tracking System) APIs
and company career pages.

Priority order per company:
  1. Greenhouse API  — clean JSON, no browser, 100% reliable
  2. Lever API       — clean JSON, no browser, 100% reliable
  3. Crawl4AI        — headless browser fallback for companies without a known ATS

Configure each company's ATS type and slug in config/companies.yml.
"""

import asyncio
import json
import logging
import os
import random
import re
import time

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

log = logging.getLogger("remote-rocket.career-pages")

# Polite delay between requests (seconds)
MIN_DELAY_SECS = 2
MAX_DELAY_SECS = 4

# Crawl4AI page timeout (seconds) — only used for crawl4ai fallback
PAGE_TIMEOUT = 30

# Max content length passed to LLM for crawl4ai fallback
MAX_CONTENT_CHARS = 12_000

# HTTP request timeout for ATS API calls
ATS_TIMEOUT_SECS = 15

# Rotation counter for standard-priority companies
_run_counter = 0


# ── Company selection ─────────────────────────────────────────────────────────

def select_companies_for_run(companies: list[dict]) -> list[dict]:
    """
    Decide which companies to scrape this run.
    high_priority=true → always included
    high_priority=false → included on even-numbered runs only
    """
    global _run_counter
    _run_counter += 1

    selected = []
    skipped  = 0

    for company in companies:
        if company.get("high_priority", False):
            selected.append(company)
        elif _run_counter % 2 == 0:
            selected.append(company)
        else:
            skipped += 1

    log.info(
        f"Career pages: {len(selected)} selected for this run "
        f"({skipped} standard-priority skipped — run #{_run_counter})"
    )
    return selected


# ── Greenhouse API ────────────────────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=3, max=20),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def fetch_greenhouse(company: dict) -> list[dict]:
    """
    Fetch job listings from the Greenhouse boards API.
    Returns a list of normalized job dicts ready for the main pipeline.

    API docs: https://developers.greenhouse.io/job-board.html
    Verify slug: https://boards.greenhouse.io/{slug}/jobs
    """
    slug = company["ats_slug"]
    url  = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"

    log.info(f"  [Greenhouse] {company['name']} — {url}")
    resp = requests.get(url, timeout=ATS_TIMEOUT_SECS, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    raw_jobs = resp.json().get("jobs", [])
    log.info(f"  [Greenhouse] {company['name']} — {len(raw_jobs)} total listings found")

    jobs = []
    for raw in raw_jobs:
        title    = (raw.get("title") or "").strip()
        location = (raw.get("location") or {}).get("name", "Remote")
        job_url  = raw.get("absolute_url") or ""
        job_id   = str(raw.get("id") or "")

        # Extract description text from HTML content field
        content_html = raw.get("content") or ""
        description  = _strip_html(content_html)

        if not title or not job_url:
            continue

        jobs.append(_build_job_dict(
            company     = company,
            title       = title,
            location    = location,
            url         = job_url,
            external_id = f"greenhouse_{slug}_{job_id}",
            description = description,
        ))

    return jobs


# ── Ashby API ────────────────────────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=3, max=20),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def fetch_ashby(company: dict) -> list[dict]:
    """
    Fetch job listings from the Ashby job board API.
    Returns a list of normalized job dicts ready for the main pipeline.

    API docs: https://developers.ashbyhq.com/docs/job-board-api
    Verify slug: https://jobs.ashbyhq.com/{slug}
    """
    slug = company["ats_slug"]
    url  = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"

    log.info(f"  [Ashby] {company['name']} — {url}")
    resp = requests.get(url, timeout=ATS_TIMEOUT_SECS, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    data     = resp.json()
    raw_jobs = data.get("jobs", [])
    log.info(f"  [Ashby] {company['name']} — {len(raw_jobs)} total listings found")

    jobs = []
    for raw in raw_jobs:
        title    = (raw.get("title") or "").strip()
        job_url  = raw.get("jobUrl") or raw.get("applyUrl") or ""
        job_id   = str(raw.get("id") or "")
        location = raw.get("location") or ("Remote" if raw.get("isRemote") else "Unknown")

        content_html = raw.get("descriptionHtml") or raw.get("description") or ""
        description  = _strip_html(content_html)

        if not title or not job_url:
            continue

        jobs.append(_build_job_dict(
            company     = company,
            title       = title,
            location    = str(location),
            url         = job_url,
            external_id = f"ashby_{slug}_{job_id}",
            description = description,
        ))

    return jobs


# ── Lever API ─────────────────────────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=3, max=20),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def fetch_lever(company: dict) -> list[dict]:
    """
    Fetch job listings from the Lever postings API.
    Returns a list of normalized job dicts ready for the main pipeline.

    API docs: https://hire.lever.co/developer/postings
    Verify slug: https://jobs.lever.co/{slug}
    """
    slug = company["ats_slug"]
    url  = f"https://api.lever.co/v0/postings/{slug}?mode=json"

    log.info(f"  [Lever] {company['name']} — {url}")
    resp = requests.get(url, timeout=ATS_TIMEOUT_SECS, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    raw_jobs = resp.json()
    if not isinstance(raw_jobs, list):
        raw_jobs = []

    log.info(f"  [Lever] {company['name']} — {len(raw_jobs)} total listings found")

    jobs = []
    for raw in raw_jobs:
        title    = (raw.get("text") or "").strip()
        job_url  = raw.get("hostedUrl") or ""
        job_id   = raw.get("id") or ""

        cats     = raw.get("categories") or {}
        location = cats.get("location") or cats.get("allLocations") or "Remote"
        if isinstance(location, list):
            location = ", ".join(location)

        description = (
            raw.get("descriptionPlain")
            or _strip_html(raw.get("description") or "")
        )

        if not title or not job_url:
            continue

        jobs.append(_build_job_dict(
            company     = company,
            title       = title,
            location    = str(location),
            url         = job_url,
            external_id = f"lever_{slug}_{job_id}",
            description = description,
        ))

    return jobs


# ── Crawl4AI fallback ─────────────────────────────────────────────────────────

async def _fetch_crawl4ai(crawler, company: dict) -> dict | None:
    """Fetch a single career page via Crawl4AI headless browser."""
    from crawl4ai import CrawlerRunConfig

    config = CrawlerRunConfig(
        page_timeout=PAGE_TIMEOUT * 1000,
        wait_for_images=False,
        exclude_external_links=True,
        verbose=False,
    )

    result = await crawler.arun(url=company["careers_url"], config=config)

    if not result.success:
        raise RuntimeError(
            f"Crawl4AI failure for {company['name']}: "
            f"{getattr(result, 'error_message', 'unknown error')}"
        )

    content = result.markdown or result.cleaned_html or ""
    if not content.strip():
        raise RuntimeError(f"Empty content for {company['name']}")

    if len(content) > MAX_CONTENT_CHARS:
        content = content[:MAX_CONTENT_CHARS] + "\n[content truncated]"

    return {
        "company":       company["name"],
        "careers_url":   company["careers_url"],
        "source":        "career_page",
        "source_url":    company["careers_url"],
        "is_hidden_gem": 1,
        "raw_content":   content,
        "high_priority": company.get("high_priority", False),
    }


async def _run_crawl4ai_batch(companies: list[dict]) -> list[dict]:
    """Run Crawl4AI for a list of companies. Returns page result dicts."""
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig
    except ImportError:
        log.error("crawl4ai not installed — Crawl4AI fallback unavailable")
        return []

    results = []
    browser_config = BrowserConfig(headless=True, verbose=False)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        for i, company in enumerate(companies):
            name = company.get("name", "Unknown")
            try:
                log.info(f"  [Crawl4AI] {company['name']}")
                page = await _fetch_crawl4ai(crawler, company)
                if page:
                    results.append(page)
                    log.info(f"    ✓ {name} — {len(page['raw_content'])} chars")
            except Exception as e:
                log.error(f"    ✗ {name} failed: {e}")
            finally:
                if i < len(companies) - 1:
                    delay = random.uniform(MIN_DELAY_SECS, MAX_DELAY_SECS)
                    await asyncio.sleep(delay)

    return results


def extract_jobs_from_page(page_result: dict) -> list[dict]:
    """
    Given a Crawl4AI page result, ask Claude to identify job listings.
    Only used for companies that fall back to Crawl4AI.
    """
    from llm_extractor import _get_client, MAX_DESCRIPTION_CHARS, MODEL

    company     = page_result["company"]
    careers_url = page_result["careers_url"]
    raw_content = page_result["raw_content"]

    listing_prompt = f"""You are parsing a company careers page to find remote marketing job listings.

Company: {company}
Careers URL: {careers_url}

Below is the page content as markdown. Your task:
1. Identify all individual job listings on this page
2. For each job, extract: title, location/remote status, job URL (if present), and a brief description snippet
3. Only include jobs that could be relevant to performance marketing, paid search, SEM, PPC, or digital marketing
4. Ignore engineering, design, sales, finance, and clearly unrelated roles
5. Return a JSON array. If no relevant jobs are found, return an empty array [].

Format:
[
  {{
    "title": "job title",
    "location": "Remote" or location string,
    "url": "full URL or null",
    "snippet": "brief description or requirements snippet (2-3 sentences max)"
  }}
]

Return ONLY the JSON array, no other text.

PAGE CONTENT:
{raw_content[:MAX_DESCRIPTION_CHARS]}
"""

    client = _get_client()
    try:
        message  = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": listing_prompt}],
        )
        raw_text = message.content[0].text
        log.debug(
            f"Crawl4AI LLM scan — in: {message.usage.input_tokens}, "
            f"out: {message.usage.output_tokens} | {company}"
        )
    except Exception as e:
        log.error(f"LLM scan failed for {company}: {e}")
        return []

    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    try:
        listings = json.loads(text)
        if not isinstance(listings, list):
            return []
    except json.JSONDecodeError:
        log.error(f"Could not parse listings JSON for {company}")
        return []

    if not listings:
        log.info(f"No relevant jobs found on {company} career page")
        return []

    log.info(f"Found {len(listings)} potential jobs on {company} Crawl4AI page")

    jobs = []
    for listing in listings:
        title = (listing.get("title") or "").strip()
        if not title:
            continue
        url = (listing.get("url") or "").strip() or careers_url
        if any(j["url"] == url for j in jobs):
            continue

        jobs.append(_build_job_dict(
            company     = {"name": company, "careers_url": careers_url},
            title       = title,
            location    = listing.get("location", "Remote"),
            url         = url,
            external_id = None,
            description = listing.get("snippet", ""),
        ))

    return jobs


# ── Main entry point ──────────────────────────────────────────────────────────

def run_career_page_scrape(companies: list[dict]) -> list[dict]:
    """
    Scrape all selected companies using the best available method per company.
    Returns a list of page_result dicts compatible with extract_jobs_from_page(),
    PLUS inserts ATS-sourced jobs directly (they don't need the LLM page-scan step).

    Returns (ats_jobs, crawl4ai_page_results) — caller handles each differently.
    Actually returns a unified list for compatibility: ATS jobs are wrapped as
    pre-extracted page results that skip the LLM listing scan.
    """
    selected = select_companies_for_run(companies)
    if not selected:
        log.info("No career pages selected for this run")
        return []

    ats_jobs        = []   # Jobs fetched directly via ATS API
    crawl4ai_queue  = []   # Companies falling back to Crawl4AI

    for company in selected:
        ats  = (company.get("ats") or "crawl4ai").lower()
        slug = company.get("ats_slug") or ""
        name = company.get("name", "Unknown")

        try:
            if ats == "greenhouse" and slug:
                jobs = fetch_greenhouse(company)
                log.info(f"  → {name}: {len(jobs)} jobs via Greenhouse")
                ats_jobs.extend(jobs)

            elif ats == "ashby" and slug:
                jobs = fetch_ashby(company)
                log.info(f"  → {name}: {len(jobs)} jobs via Ashby")
                ats_jobs.extend(jobs)

            elif ats == "lever" and slug:
                jobs = fetch_lever(company)
                log.info(f"  → {name}: {len(jobs)} jobs via Lever")
                ats_jobs.extend(jobs)

            else:
                if ats not in ("crawl4ai", ""):
                    log.warning(f"  Unknown ATS type '{ats}' for {name} — falling back to Crawl4AI")
                crawl4ai_queue.append(company)

        except Exception as e:
            log.error(f"  ATS fetch failed for {name} ({ats}/{slug}): {e} — falling back to Crawl4AI")
            crawl4ai_queue.append(company)

        # Polite delay between companies
        time.sleep(random.uniform(MIN_DELAY_SECS, MAX_DELAY_SECS))

    # Run Crawl4AI for any companies that need it
    crawl4ai_results = []
    if crawl4ai_queue:
        log.info(f"[Crawl4AI] Running for {len(crawl4ai_queue)} companies ...")
        crawl4ai_results = asyncio.run(_run_crawl4ai_batch(crawl4ai_queue))

    log.info(
        f"Career pages complete — "
        f"{len(ats_jobs)} jobs via ATS APIs, "
        f"{len(crawl4ai_queue)} companies via Crawl4AI"
    )

    # Return ATS jobs wrapped so main.py can handle them uniformly.
    # ATS jobs are pre-extracted — they skip the LLM listing scan and go
    # straight into _process_raw_job().
    # Crawl4AI results still need extract_jobs_from_page() called on them.
    # We encode the difference via a flag on the result dict.
    wrapped_ats = [{"_ats_job": True, "_job_dict": job} for job in ats_jobs]
    return wrapped_ats + crawl4ai_results


# ── Shared helpers ────────────────────────────────────────────────────────────

def _build_job_dict(
    company: dict,
    title: str,
    location: str,
    url: str,
    external_id: str | None,
    description: str,
) -> dict:
    """Build a normalized job dict compatible with the main pipeline schema."""
    return {
        "source":           "career_page",
        "external_id":      external_id,
        "url":              url,
        "source_url":       company.get("careers_url", url),
        "title":            title,
        "company":          company["name"],
        "location":         location,
        "employment_type":  None,    # LLM extraction fills this in
        "salary_min":       None,
        "salary_max":       None,
        "salary_raw":       None,
        "salary_currency":  "USD",
        "description_raw":  description,
        "description_clean": description,
        "requirements":     None,
        "skills_detected":  None,
        "raw_llm_response": None,
        "relevance_score":  None,
        "salary_score":     None,
        "is_fully_remote":  1,
        "is_hidden_gem":    1,
        "has_google_ads":   0,
        "has_msft_ads":     0,
        "has_gtm":          0,
        "has_gmc":          0,
        "is_excluded":      0,
        "exclusion_reason": None,
        "date_posted":      None,
    }


def _strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_CONTENT_CHARS]
