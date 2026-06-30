"""
scraper/career_page_scraper.py
Crawls company career pages to find "hidden gem" job listings.

Uses Crawl4AI (AsyncWebCrawler) to render JavaScript-heavy pages and return
clean markdown that Claude can process efficiently.

Guardrails:
- 3–6 second random delay between requests (polite crawling)
- Exponential backoff, max 3 attempts per company (via tenacity)
- Per-company error isolation — one failure never stops the rest
- high_priority companies are always scraped; others rotate every other run

The raw markdown is returned to main.py, which passes it to llm_extractor.py
to pull out individual job listings.
"""

import asyncio
import logging
import os
import random
import sqlite3

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

log = logging.getLogger("remote-rocket.career-pages")

# Polite delay range between page requests (seconds)
MIN_DELAY_SECS = 3
MAX_DELAY_SECS = 6

# Crawl4AI page timeout (seconds)
PAGE_TIMEOUT = 30

# Max content length to pass to the LLM (career pages can be very long)
MAX_CONTENT_CHARS = 12_000


# ── Rotation state ────────────────────────────────────────────────────────────
# Tracks which run number we're on so standard-priority companies are scraped
# every other run without requiring a persistent state file.
# This is reset each container restart, which is acceptable for a personal tool.
_run_counter = 0


def select_companies_for_run(companies: list[dict]) -> list[dict]:
    """
    Decide which companies to scrape this run.
    - high_priority=true  → always included
    - high_priority=false → included on even-numbered runs only

    This halves the load from standard companies while still covering them
    every ~24 hours on a 12-hour scrape interval.
    """
    global _run_counter
    _run_counter += 1

    selected = []
    skipped  = 0

    for company in companies:
        if company.get("high_priority", False):
            selected.append(company)
        elif _run_counter % 2 == 0:
            # Even run — include standard-priority companies
            selected.append(company)
        else:
            skipped += 1

    log.info(
        f"Career pages: {len(selected)} selected for this run "
        f"({skipped} standard-priority skipped — run #{_run_counter})"
    )
    return selected


# ── Retry decorator ───────────────────────────────────────────────────────────

def _make_retry():
    """Build a tenacity retry decorator for page fetches."""
    return retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )


# ── Core scraper ──────────────────────────────────────────────────────────────

async def _fetch_single_page(crawler, company: dict) -> dict | None:
    """
    Fetch one career page and return a result dict.
    Decorated with retry at the call site.
    Returns None on unrecoverable failure.
    """
    # Import here to avoid loading Playwright at module import time
    # (keeps startup fast when Crawl4AI isn't needed yet)
    from crawl4ai import CrawlerRunConfig

    config = CrawlerRunConfig(
        page_timeout=PAGE_TIMEOUT * 1000,   # Crawl4AI uses milliseconds
        wait_for_images=False,              # We only need text
        exclude_external_links=True,
        verbose=False,
    )

    result = await crawler.arun(
        url=company["careers_url"],
        config=config,
    )

    if not result.success:
        raise RuntimeError(
            f"Crawl4AI returned failure for {company['name']}: "
            f"{getattr(result, 'error_message', 'unknown error')}"
        )

    content = result.markdown or result.cleaned_html or ""
    if not content.strip():
        raise RuntimeError(f"Empty content returned for {company['name']}")

    # Trim to keep LLM token cost predictable
    if len(content) > MAX_CONTENT_CHARS:
        content = content[:MAX_CONTENT_CHARS] + "\n[content truncated]"

    return {
        "company":        company["name"],
        "careers_url":    company["careers_url"],
        "source":         "career_page",
        "source_url":     company["careers_url"],
        "is_hidden_gem":  1,
        "raw_content":    content,
        "high_priority":  company.get("high_priority", False),
    }


async def scrape_career_pages(companies: list[dict]) -> list[dict]:
    """
    Fetch all selected career pages sequentially with polite delays.
    Returns a list of result dicts for pages that succeeded.

    Sequential (not concurrent) to avoid hammering servers and to respect
    the per-request delay. Career pages are a supplemental source — speed
    matters less than reliability and politeness.
    """
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig
    except ImportError:
        log.error("crawl4ai is not installed. Career page scraping will be skipped.")
        return []

    results = []
    retry_fetch = _make_retry()

    browser_config = BrowserConfig(
        headless=True,
        verbose=False,
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        for i, company in enumerate(companies):
            name = company.get("name", "Unknown")

            try:
                log.info(f"Career page [{i + 1}/{len(companies)}]: {name}")

                # Apply retry decorator dynamically
                fetch_with_retry = retry_fetch(_fetch_single_page)
                page_result = await fetch_with_retry(crawler, company)

                if page_result:
                    results.append(page_result)
                    log.info(
                        f"  ✓ {name} — {len(page_result['raw_content'])} chars"
                    )

            except Exception as e:
                # Per-company isolation: log and continue, never raise
                log.error(f"  ✗ {name} failed after all retries: {e}")

            finally:
                # Polite delay after every request (success or failure),
                # except after the last company
                if i < len(companies) - 1:
                    delay = random.uniform(MIN_DELAY_SECS, MAX_DELAY_SECS)
                    log.debug(f"  Waiting {delay:.1f}s before next request …")
                    await asyncio.sleep(delay)

    log.info(f"Career pages complete: {len(results)}/{len(companies)} succeeded")
    return results


def run_career_page_scrape(companies: list[dict]) -> list[dict]:
    """
    Synchronous entry point for career page scraping.
    Selects companies based on priority/rotation, then runs the async scraper.
    Called from main.py's synchronous run_scrape() function.
    """
    selected = select_companies_for_run(companies)
    if not selected:
        log.info("No career pages selected for this run")
        return []

    return asyncio.run(scrape_career_pages(selected))


# ── Job extraction from career page content ───────────────────────────────────

def extract_jobs_from_page(page_result: dict) -> list[dict]:
    """
    Given a crawled career page result, ask Claude to identify and extract
    individual job listings from the markdown content.

    Returns a list of job dicts (may be empty if no relevant jobs found).
    This function uses a different prompt strategy than extract_job_data():
    it first finds job listings on the page, then processes each one.
    """
    from llm_extractor import _get_client, _parse_response, MAX_DESCRIPTION_CHARS, MODEL

    company      = page_result["company"]
    careers_url  = page_result["careers_url"]
    raw_content  = page_result["raw_content"]

    # Step 1: Ask Claude to identify job listings on the page
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
        message = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": listing_prompt}],
        )
        raw_text = message.content[0].text
        log.debug(
            f"Career page listing scan — in: {message.usage.input_tokens}, "
            f"out: {message.usage.output_tokens} tokens | {company}"
        )

    except Exception as e:
        log.error(f"Failed to scan career page for {company}: {e}")
        return []

    # Parse the listings array
    import re, json
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    try:
        listings = json.loads(text)
        if not isinstance(listings, list):
            log.warning(f"Unexpected response format for {company} career page")
            return []
    except json.JSONDecodeError:
        log.error(f"Could not parse job listings JSON for {company}")
        log.debug(f"Raw: {raw_text[:300]}")
        return []

    if not listings:
        log.info(f"No relevant jobs found on {company} career page")
        return []

    log.info(f"Found {len(listings)} potential jobs on {company} career page")

    # Step 2: Convert each listing to a job dict for the main pipeline
    # The main pipeline will run full extraction via extract_job_data()
    jobs = []
    for listing in listings:
        title = listing.get("title", "").strip()
        if not title:
            continue

        # Build a URL: use the listing URL if found, otherwise the careers page URL
        url = listing.get("url", "").strip() or careers_url

        # Deduplicate within this page (same URL appearing twice)
        if any(j["url"] == url for j in jobs):
            continue

        jobs.append({
            "source":           "career_page",
            "external_id":      None,
            "url":              url,
            "source_url":       careers_url,
            "title":            title,
            "company":          company,
            "location":         listing.get("location", "Remote"),
            "employment_type":  None,   # LLM extraction will fill this in
            "salary_min":       None,
            "salary_max":       None,
            "salary_raw":       None,
            "salary_currency":  "USD",
            "description_raw":  listing.get("snippet", ""),
            "description_clean": listing.get("snippet", ""),
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
        })

    return jobs
