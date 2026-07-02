"""
app/components/job_fetcher.py
Fetch a job posting URL and extract structured fields via Claude.
Used by the Add Job page to pull in external listings manually.
"""

import json
import os
import re

import anthropic
import requests
from bs4 import BeautifulSoup

SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", "")
SCRAPINGBEE_URL     = "https://app.scrapingbee.com/api/v1/"
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
MODEL               = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
MAX_CHARS           = 6000

EXTRACTION_PROMPT = """You are analyzing a job listing for a senior performance marketing professional seeking fully remote roles in paid search and digital marketing.

Analyze the listing below and return ONLY a valid JSON object — no markdown fences, no explanation, just the JSON.

Required JSON fields:
{{
  "title": "exact job title from listing",
  "company": "company name",
  "location": "location string from listing, or 'Remote'",
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
  "is_excluded": false,
  "exclusion_reason": null,
  "relevance_score": integer 1 to 10,
  "salary_score": integer 1 to 10,
  "date_posted": "YYYY-MM-DD or null"
}}

--- SALARY NORMALIZATION ---
Always normalize salary to annual USD integers.
- Hourly rate: multiply by 2080
- Monthly rate: multiply by 12
- If a range is given, populate both salary_min and salary_max
- If only one number, set salary_min and leave salary_max null
- If no salary mentioned, set both to null

--- SKILL FLAG RULES ---
has_google_ads = true if Google Ads, Google Search Ads, Google PPC, or SEM on Google is mentioned
has_msft_ads   = true if Microsoft Ads, Bing Ads, MSAN, or Microsoft Search is mentioned
has_gtm        = true if Google Tag Manager or GTM is mentioned
has_gmc        = true if Google Merchant Center, Shopping Feed, or Product Feed is mentioned

--- RELEVANCE SCORE GUIDE (1–10) ---
9–10: Paid search / SEM is the PRIMARY function.
7–8:  Strong performance marketing focus.
5–6:  General digital marketing with meaningful paid channel component.
3–4:  Marketing role with minor paid search component.
1–2:  Tangentially related with no clear paid search component.

--- SALARY SCORE GUIDE (1–10) ---
10: $150k+  8: $120k–$149k  6: $100k–$119k  4: $80k–$99k  2: Below $80k  1: Not listed

--- JOB LISTING ---
{job_text}
"""


def fetch_url(url: str) -> str:
    """Fetch raw HTML from a URL. Uses ScrapingBee if key is set, else plain requests."""
    if SCRAPINGBEE_API_KEY:
        resp = requests.get(
            SCRAPINGBEE_URL,
            params={"api_key": SCRAPINGBEE_API_KEY, "url": url, "render_js": "true"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.text
    else:
        resp = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
        )
        resp.raise_for_status()
        return resp.text


def html_to_text(html: str) -> str:
    """Strip HTML tags and return readable plain text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_job(url: str, raw_text: str) -> dict:
    """Send page text to Claude and return a structured job dict."""
    job_text = raw_text[:MAX_CHARS]
    if len(raw_text) > MAX_CHARS:
        job_text += "\n[description truncated]"

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(job_text=job_text)}],
    )
    text = message.content[0].text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    data = json.loads(text)
    data = _coerce(data)
    data["url"]             = url
    data["source_url"]      = url
    data["source"]          = "manual"
    data["external_id"]     = f"manual_{abs(hash(url))}"
    data["description_raw"] = raw_text
    data["description_clean"] = raw_text[:MAX_CHARS]
    data["is_hidden_gem"]   = 0
    data["salary_currency"] = "USD"
    data["raw_llm_response"] = text
    return data


def _coerce(data: dict) -> dict:
    for f in ["salary_min", "salary_max", "relevance_score", "salary_score"]:
        v = data.get(f)
        if v is not None:
            try:
                data[f] = int(float(str(v)))
            except (TypeError, ValueError):
                data[f] = None
    for f in ["is_fully_remote", "is_hidden_gem", "has_google_ads",
              "has_msft_ads", "has_gtm", "has_gmc", "is_excluded"]:
        v = data.get(f)
        if isinstance(v, bool):
            data[f] = 1 if v else 0
        elif isinstance(v, str):
            data[f] = 1 if v.lower() in ("true", "1", "yes") else 0
        else:
            data[f] = 1 if v else 0
    for f in ["requirements", "skills_detected"]:
        if not isinstance(data.get(f), list):
            data[f] = []
    return data
