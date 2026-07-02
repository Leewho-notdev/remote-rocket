"""
scraper/jobspy_scraper.py
Fetches remote job listings from major job boards using the JobSpy library.
Targets: LinkedIn, Indeed, Glassdoor, ZipRecruiter.

JobSpy handles authentication and scraping for all boards in a single call.
No API keys required.
"""

import logging
import time
from datetime import date

import pandas as pd
from jobspy import scrape_jobs

log = logging.getLogger("remote-rocket.jobspy")

# Boards to search. "google" aggregates smaller boards not on LinkedIn/Indeed.
# Remove any that start causing persistent rate-limit errors.
TARGET_SITES = ["linkedin", "indeed", "glassdoor", "zip_recruiter", "google"]

# How many results to request per site per search term.
# 25 is a safe default — high enough for coverage, low enough to avoid rate limits.
RESULTS_PER_SITE = 25

# Only fetch jobs posted in the last N hours.
# 49 hours (slightly over 2 days) ensures no gaps between 12-hour scrape runs.
HOURS_OLD = 49

# Pause between search terms to be a polite scraper.
DELAY_BETWEEN_TERMS_SECS = 5


def fetch_jobs(search_terms: list[str]) -> list[dict]:
    """
    Run JobSpy for each search term and return a combined list of raw job dicts.
    Each dict represents one job listing. Errors on individual terms are logged
    and skipped — they never abort the full run.
    """
    all_jobs: list[dict] = []
    seen_urls: set[str]  = set()  # In-memory dedup within this scrape session

    for i, term in enumerate(search_terms):
        log.info(f"JobSpy searching: '{term}' ({i + 1}/{len(search_terms)})")

        try:
            df = scrape_jobs(
                site_name=TARGET_SITES,
                search_term=term,
                location="Remote",
                results_wanted=RESULTS_PER_SITE,
                hours_old=HOURS_OLD,
                country_indeed="USA",
                linkedin_fetch_description=True,  # Get full description, not truncated
                verbose=0,                         # Suppress JobSpy's own console output
            )

            if df is None or df.empty:
                log.info(f"  → No results for '{term}'")
                continue

            raw_jobs = df.to_dict("records")
            new_this_term = 0

            for raw in raw_jobs:
                job = _normalize_jobspy_record(raw, term)
                if not job:
                    continue

                # Skip within-session duplicates (same URL seen in an earlier search term)
                url = job.get("url", "")
                if not url or url in seen_urls:
                    continue

                seen_urls.add(url)
                all_jobs.append(job)
                new_this_term += 1

            log.info(f"  → {new_this_term} unique jobs added (total so far: {len(all_jobs)})")

        except Exception as e:
            log.error(f"JobSpy failed for term '{term}': {e}")
            # Continue with next term

        # Polite delay between search terms (skip after the last one)
        if i < len(search_terms) - 1:
            time.sleep(DELAY_BETWEEN_TERMS_SECS)

    log.info(f"JobSpy complete — {len(all_jobs)} unique raw jobs fetched")
    return all_jobs


def _normalize_jobspy_record(raw: dict, search_term: str) -> dict | None:
    """
    Convert a raw JobSpy DataFrame row (dict) into a clean dict that matches
    the jobs table schema. Returns None if the record is unusable.
    """
    # JobSpy field names vary slightly by version — handle common aliases
    url = (
        _str(raw.get("job_url"))
        or _str(raw.get("url"))
        or _str(raw.get("job_url_direct"))
    )
    title   = _str(raw.get("title"))
    company = _str(raw.get("company"))

    # Skip records that are missing the minimum required fields
    if not url or not title or not company:
        return None

    # Determine source label (e.g. 'jobspy_linkedin', 'jobspy_indeed')
    site = _str(raw.get("site", "unknown")).lower()
    source = f"jobspy_{site}" if site != "unknown" else "jobspy"

    # Salary: JobSpy provides min/max as floats when available
    salary_min = _int(raw.get("min_amount") or raw.get("salary_min"))
    salary_max = _int(raw.get("max_amount") or raw.get("salary_max"))
    salary_raw = _str(raw.get("salary_source") or raw.get("salary"))

    # Normalize salary to annual if JobSpy reports it as hourly or monthly
    interval = _str(raw.get("interval", "yearly")).lower()
    if salary_min and interval == "hourly":
        salary_min = int(salary_min * 2080)   # 40 hrs × 52 weeks
        salary_max = int(salary_max * 2080) if salary_max else None
    elif salary_min and interval == "monthly":
        salary_min = int(salary_min * 12)
        salary_max = int(salary_max * 12) if salary_max else None

    # Employment type: normalize to our schema values
    job_type = _str(raw.get("job_type") or raw.get("employment_type", "")).lower()
    employment_type = _map_employment_type(job_type)

    # Date posted: JobSpy may return a date object or string
    date_posted = _str(raw.get("date_posted") or raw.get("posted_date") or "")
    if hasattr(raw.get("date_posted"), "isoformat"):
        date_posted = raw["date_posted"].isoformat()

    # Description: prefer the full version
    description = (
        _str(raw.get("description"))
        or _str(raw.get("job_description"))
        or ""
    )

    location = _str(raw.get("location", "Remote"))

    # Pre-filter obviously non-US locations before touching the LLM.
    # Ambiguous locations (blank, "Remote") pass through — the LLM handles them.
    is_non_us = not _is_us_or_unknown_location(location)

    return {
        "source":          source,
        "external_id":     _str(raw.get("id") or raw.get("job_id")),
        "url":             url,
        "source_url":      _str(raw.get("job_url_direct") or url),
        "title":           title,
        "company":         company,
        "location":        location,
        "employment_type": employment_type,
        "salary_min":      salary_min,
        "salary_max":      salary_max,
        "salary_raw":      salary_raw,
        "salary_currency": "USD",
        "description_raw": description,
        "description_clean": _clean_text(description),
        # LLM fields: populated in Step 5 (llm_extractor.py)
        # For now these are null — jobs are stored as raw, unscored listings
        "requirements":    None,
        "skills_detected": None,
        "raw_llm_response": None,
        "relevance_score": None,
        "salary_score":    None,
        "is_fully_remote": 1,      # We only search for remote jobs
        "is_hidden_gem":   0,      # JobSpy = job board, not a career page
        "has_google_ads":  0,
        "has_msft_ads":    0,
        "has_gtm":         0,
        "has_gmc":         0,
        "is_excluded":     1 if is_non_us else 0,
        "exclusion_reason": f"Non-US location: {location}" if is_non_us else None,
        "date_posted":     date_posted,
        # Internal metadata for traceability
        "_search_term":    search_term,
    }


def _map_employment_type(raw_type: str) -> str:
    """Map JobSpy's employment type strings to our schema values."""
    if not raw_type:
        return "full_time"  # Default assumption for most roles
    raw_type = raw_type.lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "fulltime":          "full_time",
        "full_time":         "full_time",
        "full time":         "full_time",
        "contract":          "contract",
        "contractor":        "contract",
        "temporary":         "contract",
        "temp":              "contract",
        "freelance":         "contract",
        "consultant":        "contract",
        "parttime":          "part_time",
        "part_time":         "part_time",
        "part time":         "part_time",
        "internship":        "part_time",
    }
    return mapping.get(raw_type, "full_time")


# Country names/patterns that clearly indicate a non-US job.
# "Remote" alone is NOT excluded — most US remote jobs just say "Remote".
_NON_US_LOCATION_PATTERNS = [
    "united kingdom", " uk ", "(uk)", "england", "scotland", "wales",
    "canada", "ontario", "british columbia", "alberta", "toronto", "vancouver",
    "australia", "sydney", "melbourne", "brisbane",
    "new zealand",
    "ireland", "dublin",
    "germany", "berlin", "munich",
    "france", "paris",
    "netherlands", "amsterdam",
    "spain", "madrid", "barcelona",
    "india", "bangalore", "mumbai", "delhi",
    "singapore",
    "philippines",
    "latin america", "latam",
    "europe",
    "emea",
    "apac",
]


def _is_us_or_unknown_location(location: str) -> bool:
    """
    Return True if the location is US-based or ambiguous (e.g. just "Remote").
    Return False only when we can positively identify a non-US location.
    This errs on the side of inclusion — the LLM catches anything we miss.
    """
    if not location:
        return True
    loc = location.lower()
    for pattern in _NON_US_LOCATION_PATTERNS:
        if pattern in loc:
            return False
    return True


def _clean_text(text: str) -> str:
    """Strip HTML tags and collapse whitespace for cleaner display."""
    import re
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _str(value) -> str:
    """Safely convert a value to string, returning empty string for None/NaN."""
    if value is None:
        return ""
    # Pandas NaN check
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _int(value) -> int | None:
    """Safely convert a value to int, returning None on failure."""
    if value is None:
        return None
    try:
        f = float(value)
        return int(f) if f > 0 else None
    except (TypeError, ValueError):
        return None
