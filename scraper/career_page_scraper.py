"""
scraper/career_page_scraper.py
Fetches "hidden gem" jobs directly from company ATS APIs and career pages.

ATS detection order (fully automatic — no manual slug config needed):
  1. Detect ATS type from the careers_url (greenhouse.io, ashbyhq.com, lever.co, workday)
  2. Extract slug from the URL when possible
  3. If slug can't be extracted, probe each API with a best-guess slug derived from
     the company name, trying Greenhouse → Ashby → Lever in order
  4. Fall back to Crawl4AI if all API probes fail or ATS is Workday

The ats/ats_slug fields in companies.yml are still respected when provided,
but are no longer required. Auto-detection handles everything.
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

MIN_DELAY_SECS   = 2
MAX_DELAY_SECS   = 4
PAGE_TIMEOUT     = 30
MAX_CONTENT_CHARS = 12_000
ATS_TIMEOUT_SECS = 15

_run_counter = 0


# ── Company selection ─────────────────────────────────────────────────────────

def select_companies_for_run(companies: list[dict]) -> list[dict]:
    global _run_counter
    _run_counter += 1
    selected, skipped = [], 0
    for company in companies:
        if company.get("high_priority", False):
            selected.append(company)
        elif _run_counter % 2 == 0:
            selected.append(company)
        else:
            skipped += 1
    log.info(f"Career pages: {len(selected)} selected ({skipped} standard skipped — run #{_run_counter})")
    return selected


# ── ATS auto-detection ────────────────────────────────────────────────────────

def _slug_from_name(name: str) -> str:
    """Derive a best-guess API slug from a company display name."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]", "", slug)   # strip spaces, punctuation
    return slug


def detect_ats(company: dict) -> tuple[str, str]:
    """
    Return (ats_type, slug) for a company using this priority:
    1. Explicit ats/ats_slug in companies.yml (backward-compatible)
    2. Pattern-match on careers_url
    3. Slug derived from company name (used for API probing)

    Returns ("crawl4ai", "") when we know no API will work (e.g. Workday).
    Returns ("probe", slug) when we should try each API with the derived slug.
    """
    explicit_ats  = (company.get("ats") or "").lower()
    explicit_slug = company.get("ats_slug") or ""
    careers_url   = company.get("careers_url") or ""
    name          = company.get("name", "")

    # Respect explicit config when provided
    if explicit_ats and explicit_ats != "auto":
        return explicit_ats, explicit_slug

    url = careers_url.lower()

    # Workday — no public API, always Crawl4AI
    if "myworkdayjobs.com" in url or "workday.com" in url:
        log.info(f"  [{name}] Detected Workday — using Crawl4AI")
        return "crawl4ai", ""

    # Greenhouse — extract slug from URL path
    # e.g. https://boards.greenhouse.io/{slug}/jobs/...
    #      https://job-boards.greenhouse.io/{slug}/jobs/...
    m = re.search(r"greenhouse\.io/([^/?#]+)", url)
    if m:
        return "greenhouse", m.group(1)

    # Ashby — extract slug from URL
    # e.g. https://jobs.ashbyhq.com/{slug}/...
    m = re.search(r"ashbyhq\.com/([^/?#]+)", url)
    if m:
        return "ashby", m.group(1)

    # Lever — extract slug from URL
    # e.g. https://jobs.lever.co/{slug}/...
    m = re.search(r"lever\.co/([^/?#]+)", url)
    if m:
        return "lever", m.group(1)

    # Workable — extract slug from URL
    # e.g. https://apply.workable.com/{slug}/
    #      https://{slug}.workable.com/
    m = re.search(r"apply\.workable\.com/([^/?#]+)", url)
    if m:
        return "workable", m.group(1)
    m = re.search(r"([^./]+)\.workable\.com", url)
    if m:
        return "workable", m.group(1)

    # BambooHR — no standard public API
    if "bamboohr.com" in url:
        return "crawl4ai", ""

    # iCIMS — no standard public API
    if "icims.com" in url:
        return "crawl4ai", ""

    # No ATS detected from URL — probe APIs with a derived slug
    return "probe", _slug_from_name(name)


# ── ATS API fetchers ──────────────────────────────────────────────────────────

def _get(url: str) -> requests.Response:
    """Simple GET with a browser-like User-Agent."""
    return requests.get(url, timeout=ATS_TIMEOUT_SECS, headers={"User-Agent": "Mozilla/5.0"})


def fetch_greenhouse(company: dict, slug: str) -> list[dict]:
    url  = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    log.info(f"  [Greenhouse] {company['name']} → {url}")
    resp = _get(url)
    resp.raise_for_status()
    raw_jobs = resp.json().get("jobs", [])
    log.info(f"  [Greenhouse] {company['name']} — {len(raw_jobs)} listings")
    jobs = []
    for raw in raw_jobs:
        title   = (raw.get("title") or "").strip()
        job_url = raw.get("absolute_url") or ""
        if not title or not job_url:
            continue
        jobs.append(_build_job_dict(
            company     = company,
            title       = title,
            location    = (raw.get("location") or {}).get("name", "Remote"),
            url         = job_url,
            external_id = f"greenhouse_{slug}_{raw.get('id', '')}",
            description = _strip_html(raw.get("content") or ""),
        ))
    return jobs


def fetch_ashby(company: dict, slug: str) -> list[dict]:
    url  = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    log.info(f"  [Ashby] {company['name']} → {url}")
    resp = _get(url)
    resp.raise_for_status()
    raw_jobs = resp.json().get("jobs", [])
    log.info(f"  [Ashby] {company['name']} — {len(raw_jobs)} listings")
    jobs = []
    for raw in raw_jobs:
        title   = (raw.get("title") or "").strip()
        job_url = raw.get("jobUrl") or raw.get("applyUrl") or ""
        if not title or not job_url:
            continue
        location = raw.get("location") or ("Remote" if raw.get("isRemote") else "Unknown")
        jobs.append(_build_job_dict(
            company     = company,
            title       = title,
            location    = str(location),
            url         = job_url,
            external_id = f"ashby_{slug}_{raw.get('id', '')}",
            description = _strip_html(raw.get("descriptionHtml") or raw.get("description") or ""),
        ))
    return jobs


def fetch_lever(company: dict, slug: str) -> list[dict]:
    url  = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    log.info(f"  [Lever] {company['name']} → {url}")
    resp = _get(url)
    resp.raise_for_status()
    raw_jobs = resp.json()
    if not isinstance(raw_jobs, list):
        raw_jobs = []
    log.info(f"  [Lever] {company['name']} — {len(raw_jobs)} listings")
    jobs = []
    for raw in raw_jobs:
        title   = (raw.get("text") or "").strip()
        job_url = raw.get("hostedUrl") or ""
        if not title or not job_url:
            continue
        cats     = raw.get("categories") or {}
        location = cats.get("location") or cats.get("allLocations") or "Remote"
        if isinstance(location, list):
            location = ", ".join(location)
        jobs.append(_build_job_dict(
            company     = company,
            title       = title,
            location    = str(location),
            url         = job_url,
            external_id = f"lever_{slug}_{raw.get('id', '')}",
            description = (raw.get("descriptionPlain") or _strip_html(raw.get("description") or "")),
        ))
    return jobs


def fetch_workable(company: dict, slug: str) -> list[dict]:
    # Workable deprecated /api/v1/widget/listings/{slug}; the replacement is the
    # public jobs.md table exposed at /{slug}/jobs.md (no auth required).
    url = f"https://apply.workable.com/{slug}/jobs.md"
    log.info(f"  [Workable] {company['name']} → {url}")
    resp = _get(url)
    resp.raise_for_status()
    text = resp.text

    jobs = []
    # Parse the markdown table: | Title | Department | Location | Type | Salary | Posted | Details |
    # Rows look like: | Some Title | Dept | Location | Full-time | USD ... | 2026-01-01 | [View](url) |
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or line.startswith("| Title") or line.startswith("|---"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 7:
            continue
        title    = cols[0]
        location = cols[2]
        # Extract job URL from [View](url)
        m = re.search(r'\[View\]\(([^)]+)\)', cols[6])
        if not title or not m:
            continue
        job_url = m.group(1)
        # Derive a stable external_id from the shortcode in the URL
        shortcode_m = re.search(r'/view/([^./]+)', job_url)
        shortcode = shortcode_m.group(1) if shortcode_m else title.lower().replace(" ", "-")
        jobs.append(_build_job_dict(
            company     = company,
            title       = title,
            location    = location or "Remote",
            url         = job_url.replace(".md", ""),
            external_id = f"workable_{slug}_{shortcode}",
            description = "",
        ))

    log.info(f"  [Workable] {company['name']} — {len(jobs)} listings")
    return jobs


def probe_ats_apis(company: dict, slug: str) -> tuple[list[dict], str]:
    """
    Try Greenhouse → Ashby → Lever in order with the given slug.
    Returns (jobs, ats_name_that_worked) or ([], "crawl4ai") if all fail.
    """
    name = company.get("name", "")
    for ats_name, fetcher in [
        ("greenhouse", fetch_greenhouse),
        ("ashby",      fetch_ashby),
        ("lever",      fetch_lever),
        ("workable",   fetch_workable),
    ]:
        try:
            jobs = fetcher(company, slug)
            if jobs is not None:   # even an empty list means the API responded
                log.info(f"  [{name}] Auto-detected ATS: {ats_name} (slug: {slug})")
                return jobs, ats_name
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                log.debug(f"  [{name}] {ats_name}/{slug} → 404, trying next")
            else:
                log.warning(f"  [{name}] {ats_name}/{slug} error: {e}")
        except Exception as e:
            log.debug(f"  [{name}] {ats_name}/{slug} failed: {e}")
    log.info(f"  [{name}] No ATS API found — falling back to Crawl4AI")
    return [], "crawl4ai"


# ── Main entry point ──────────────────────────────────────────────────────────

def run_career_page_scrape(companies: list[dict]) -> list[dict]:
    selected = select_companies_for_run(companies)
    if not selected:
        log.info("No career pages selected for this run")
        return []

    ats_jobs       = []
    crawl4ai_queue = []

    for company in selected:
        name = company.get("name", "Unknown")
        ats_type, slug = detect_ats(company)

        try:
            if ats_type == "greenhouse":
                jobs = fetch_greenhouse(company, slug)
                log.info(f"  → {name}: {len(jobs)} jobs via Greenhouse")
                ats_jobs.extend(jobs)

            elif ats_type == "ashby":
                jobs = fetch_ashby(company, slug)
                log.info(f"  → {name}: {len(jobs)} jobs via Ashby")
                ats_jobs.extend(jobs)

            elif ats_type == "lever":
                jobs = fetch_lever(company, slug)
                log.info(f"  → {name}: {len(jobs)} jobs via Lever")
                ats_jobs.extend(jobs)

            elif ats_type == "workable":
                jobs = fetch_workable(company, slug)
                log.info(f"  → {name}: {len(jobs)} jobs via Workable")
                ats_jobs.extend(jobs)

            elif ats_type == "probe":
                jobs, found_ats = probe_ats_apis(company, slug)
                if found_ats != "crawl4ai":
                    log.info(f"  → {name}: {len(jobs)} jobs via {found_ats} (auto-detected)")
                    ats_jobs.extend(jobs)
                else:
                    crawl4ai_queue.append(company)

            else:
                crawl4ai_queue.append(company)

        except Exception as e:
            log.error(f"  ATS fetch failed for {name} ({ats_type}/{slug}): {e} — falling back to Crawl4AI")
            crawl4ai_queue.append(company)

        time.sleep(random.uniform(MIN_DELAY_SECS, MAX_DELAY_SECS))

    crawl4ai_results = []
    if crawl4ai_queue:
        log.info(f"[Crawl4AI] Running for {len(crawl4ai_queue)} companies ...")
        crawl4ai_results = asyncio.run(_run_crawl4ai_batch(crawl4ai_queue))

    log.info(
        f"Career pages complete — "
        f"{len(ats_jobs)} jobs via ATS APIs, "
        f"{len(crawl4ai_queue)} companies via Crawl4AI"
    )

    wrapped_ats = [{"_ats_job": True, "_job_dict": job} for job in ats_jobs]
    return wrapped_ats + crawl4ai_results


# ── Crawl4AI fallback ─────────────────────────────────────────────────────────

async def _fetch_crawl4ai(crawler, company: dict) -> dict | None:
    from crawl4ai import CrawlerRunConfig
    config = CrawlerRunConfig(
        page_timeout=PAGE_TIMEOUT * 1000,
        wait_for_images=False,
        exclude_external_links=True,
        verbose=False,
    )
    result = await crawler.arun(url=company["careers_url"], config=config)
    if not result.success:
        raise RuntimeError(f"Crawl4AI failure for {company['name']}: {getattr(result, 'error_message', 'unknown')}")
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
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig
    except ImportError:
        log.error("crawl4ai not installed — Crawl4AI fallback unavailable")
        return []
    results = []
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False)) as crawler:
        for i, company in enumerate(companies):
            name = company.get("name", "Unknown")
            try:
                log.info(f"  [Crawl4AI] {name}")
                page = await _fetch_crawl4ai(crawler, company)
                if page:
                    results.append(page)
                    log.info(f"    ✓ {name} — {len(page['raw_content'])} chars")
            except Exception as e:
                log.error(f"    ✗ {name} failed: {e}")
            finally:
                if i < len(companies) - 1:
                    await asyncio.sleep(random.uniform(MIN_DELAY_SECS, MAX_DELAY_SECS))
    return results


def extract_jobs_from_page(page_result: dict) -> list[dict]:
    """LLM-based job extraction for Crawl4AI results."""
    from llm_extractor import _get_client, MAX_DESCRIPTION_CHARS, MODEL
    company     = page_result["company"]
    careers_url = page_result["careers_url"]
    raw_content = page_result["raw_content"]

    prompt = f"""You are parsing a company careers page to find remote marketing job listings.

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
        message  = client.messages.create(model=MODEL, max_tokens=2048,
                       messages=[{"role": "user", "content": prompt}])
        raw_text = message.content[0].text
    except Exception as e:
        log.error(f"LLM scan failed for {company}: {e}")
        return []

    text = re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
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


# ── Shared helpers ────────────────────────────────────────────────────────────

def _build_job_dict(company: dict, title: str, location: str, url: str,
                    external_id: str | None, description: str) -> dict:
    return {
        "source":           "career_page",
        "external_id":      external_id,
        "url":              url,
        "source_url":       company.get("careers_url", url),
        "title":            title,
        "company":          company["name"],
        "location":         location,
        "employment_type":  None,
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
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_CONTENT_CHARS]
