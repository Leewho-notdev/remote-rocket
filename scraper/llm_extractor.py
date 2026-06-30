"""
scraper/llm_extractor.py
Claude API extraction and relevance scoring for Remote Rocket.

Every job — from JobSpy or a career page — passes through this module
to get structured fields, relevance scores, and skill flags.

Model: claude-haiku-4-5 (fast, cheap, ~$0.001/job)
Retries: up to 3 attempts with exponential backoff via tenacity
Token logging: input/output tokens logged at DEBUG level for cost monitoring
"""

import json
import logging
import os
import re

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

log = logging.getLogger("remote-rocket.llm")

# Haiku is fast (~1–2s) and cheap (~$0.001/job).
# Switch to claude-sonnet-4-6 here for higher quality if needed.
MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# Truncate descriptions at this length before sending to Claude.
# Keeps tokens predictable and cost low. Most JDs are well under 6000 chars.
MAX_DESCRIPTION_CHARS = 6000

# ── Claude client ─────────────────────────────────────────────────────────────
# Reads ANTHROPIC_API_KEY from environment automatically.
_client = None

def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


# ── Extraction prompt ─────────────────────────────────────────────────────────
# Explicit scoring rules and flag definitions are included so Claude's
# output is consistent across job sources and description lengths.

EXTRACTION_PROMPT = """You are analyzing a job listing for a senior performance marketing professional seeking fully remote roles in paid search and digital marketing.

Analyze the listing below and return ONLY a valid JSON object — no markdown fences, no explanation, just the JSON.

Required JSON fields:
{{
  "title": "exact job title from listing",
  "company": "company name",
  "employment_type": "full_time" or "contract" or "part_time",
  "is_fully_remote": true or false,
  "salary_min": integer (annual USD) or null,
  "salary_max": integer (annual USD) or null,
  "salary_raw": "original salary text from listing, or null",
  "requirements": ["key requirement 1", "key requirement 2"],
  "skills_detected": ["tool or platform name 1", "tool or platform name 2"],
  "has_google_ads": true or false,
  "has_msft_ads": true or false,
  "has_gtm": true or false,
  "has_gmc": true or false,
  "is_excluded": true or false,
  "exclusion_reason": "plain English reason, or null",
  "relevance_score": integer 1 to 10,
  "salary_score": integer 1 to 10,
  "date_posted": "YYYY-MM-DD or null"
}}

--- SALARY NORMALIZATION ---
Always normalize salary to annual USD integers.
- Hourly rate: multiply by 2080 (40 hrs × 52 weeks)
- Monthly rate: multiply by 12
- If a range is given, populate both salary_min and salary_max
- If only one number, set salary_min and leave salary_max null
- If no salary mentioned, set both to null and salary_raw to null

--- SKILL FLAG RULES ---
has_google_ads  = true if Google Ads, Google Search Ads, Google PPC, or SEM on Google is mentioned
has_msft_ads    = true if Microsoft Ads, Bing Ads, MSAN, or Microsoft Search is mentioned
has_gtm         = true if Google Tag Manager or GTM is mentioned
has_gmc         = true if Google Merchant Center, Shopping Feed, or Product Feed is mentioned

--- RELEVANCE SCORE GUIDE (1–10) ---
9–10: Paid search / SEM is the PRIMARY function. Google Ads or Microsoft Ads explicitly required.
7–8:  Strong performance marketing focus. Paid media is a major component even if not the only one.
5–6:  General digital marketing with a meaningful paid channel component.
3–4:  Marketing role with some budget management but paid search is minor.
1–2:  Tangentially related (analytics, marketing ops, brand) with no clear paid search component.

--- SALARY SCORE GUIDE (1–10) ---
10: $150k+ / year
8:  $120k–$149k
6:  $100k–$119k
4:  $80k–$99k
2:  Below $80k
1:  Salary not listed (null)

--- EXCLUSION RULES ---
Set is_excluded = true (and populate exclusion_reason) if ANY of the following apply:
- Role is primarily social media marketing (Instagram, TikTok, Facebook organic) with no paid search component
- Role requires in-office or hybrid attendance (not fully remote)
- Salary is explicitly stated and clearly below $70k/year
- Role is purely content marketing, SEO only, email marketing only, or PR
- Role is clearly entry-level or explicitly requires fewer than 2 years of experience
- Role is a software engineering, data science, or non-marketing position

Do NOT exclude a role just because it mentions social media — only exclude if social media is the PRIMARY focus.

--- REQUIREMENTS FIELD ---
Extract up to 8 key requirements as short bullet strings.
Focus on: years of experience, specific platforms, certifications, and measurable outcomes.

--- JOB LISTING ---
{job_text}
"""


# ── Retry wrapper ─────────────────────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIConnectionError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def _call_claude(job_text: str) -> anthropic.types.Message:
    """Call the Claude API with retry on rate limit and connection errors."""
    return _get_client().messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": EXTRACTION_PROMPT.format(job_text=job_text),
        }],
    )


# ── Public interface ──────────────────────────────────────────────────────────

def extract_job_data(job: dict) -> dict:
    """
    Send a job's description through Claude and return a dict of extracted fields.
    Merges extracted fields back into the original job dict.

    On failure, returns the original job dict unchanged (no crash, no data loss).
    The job will remain in the DB with null scores — it can be re-processed later.
    """
    description = (
        job.get("description_clean")
        or job.get("description_raw")
        or ""
    ).strip()

    title   = job.get("title", "")
    company = job.get("company", "")

    # Build the text block Claude receives
    job_text = _build_job_text(title, company, description)

    if not job_text.strip():
        log.warning(f"Skipping LLM extraction — no content for '{title}' @ {company}")
        return job

    try:
        message  = _call_claude(job_text)
        raw_text = message.content[0].text

        # Log token usage at DEBUG level for cost monitoring
        usage = message.usage
        log.debug(
            f"Claude tokens — in: {usage.input_tokens}, out: {usage.output_tokens} "
            f"| '{title}' @ {company}"
        )

        extracted = _parse_response(raw_text)
        if extracted is None:
            log.error(f"Could not parse Claude response for '{title}' @ {company}")
            log.debug(f"Raw response: {raw_text[:500]}")
            return job

        # Store the raw response for debugging / re-processing
        extracted["raw_llm_response"] = raw_text

        # Merge extracted fields into the job dict
        # Extracted values take precedence over raw scraper values for these fields
        merged = {**job, **extracted}
        return merged

    except anthropic.AuthenticationError:
        # Bad API key — this will never succeed, log loudly and bail
        log.error("Claude API authentication failed. Check ANTHROPIC_API_KEY in .env")
        return job

    except Exception as e:
        log.error(f"LLM extraction failed for '{title}' @ {company}: {e}")
        return job


def should_extract(job: dict) -> bool:
    """
    Return True if this job should be sent to Claude for extraction.

    Skip if:
    - Already has a relevance_score (previously extracted)
    - Already marked is_excluded=1 by pre-screening (saves API cost)

    Jobs from career pages always get extracted (is_hidden_gem=1)
    even if they somehow already have a score, because the content
    may be richer than a board-scraped description.
    """
    # Always extract career page jobs — they're the hidden gems
    if job.get("is_hidden_gem"):
        return True

    # Skip if already scored
    if job.get("relevance_score") is not None:
        return False

    # Skip if pre-excluded by title keyword (no useful signal for LLM)
    if job.get("is_excluded") and job.get("exclusion_reason", "").startswith("Title contains"):
        return False

    return True


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_job_text(title: str, company: str, description: str) -> str:
    """
    Assemble the text block sent to Claude.
    Includes title and company at the top so Claude has context
    even if the description doesn't repeat them.
    """
    parts = []
    if title:
        parts.append(f"JOB TITLE: {title}")
    if company:
        parts.append(f"COMPANY: {company}")
    if description:
        # Truncate long descriptions to control token cost
        truncated = description[:MAX_DESCRIPTION_CHARS]
        if len(description) > MAX_DESCRIPTION_CHARS:
            truncated += "\n[description truncated]"
        parts.append(f"\nDESCRIPTION:\n{truncated}")
    return "\n".join(parts)


def _parse_response(raw_text: str) -> dict | None:
    """
    Parse Claude's text response into a Python dict.
    Handles markdown code fences that Claude occasionally adds.
    Returns None if the response can't be parsed as valid JSON.
    """
    # Strip markdown code fences if present
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try extracting the first JSON object from the response
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                return None
        else:
            return None

    # Coerce types to match schema expectations
    return _coerce_types(data)


def _coerce_types(data: dict) -> dict:
    """
    Ensure extracted fields have the right Python types for SQLite insertion.
    Claude occasionally returns strings where we expect ints or bools.
    """
    int_fields  = ["salary_min", "salary_max", "relevance_score", "salary_score"]
    bool_fields = [
        "is_fully_remote", "is_hidden_gem",
        "has_google_ads", "has_msft_ads", "has_gtm", "has_gmc",
        "is_excluded",
    ]
    list_fields = ["requirements", "skills_detected"]

    for field in int_fields:
        val = data.get(field)
        if val is not None:
            try:
                data[field] = int(float(str(val)))
            except (TypeError, ValueError):
                data[field] = None

    for field in bool_fields:
        val = data.get(field)
        if isinstance(val, bool):
            data[field] = 1 if val else 0
        elif isinstance(val, int):
            data[field] = 1 if val else 0
        elif isinstance(val, str):
            data[field] = 1 if val.lower() in ("true", "1", "yes") else 0
        else:
            data[field] = 0

    for field in list_fields:
        val = data.get(field)
        if val is None:
            data[field] = []
        elif isinstance(val, str):
            # Claude returned a string instead of a list — wrap it
            data[field] = [val] if val.strip() else []

    return data
