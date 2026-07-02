# Remote Rocket — Technical Architecture

> **Personal self-hosted remote job aggregator focused on performance marketing, paid search, and SEM roles.**
> Built for a non-developer to run and maintain via Docker Compose on a cheap VPS.

---

## Project Overview

A personal tool that aggregates remote digital marketing jobs with a strong focus on:
- Performance marketing, paid search, SEM, PPC
- Google Ads, Microsoft Ads, Google Tag Manager, Google Merchant Center
- Fully remote roles, $100k+ salary
- "Hidden" jobs sourced directly from company career pages

**Tech stack:** Python · JobSpy · Crawl4AI · Claude API (Anthropic) · Streamlit · SQLite · Docker Compose

---

## 1. Folder Structure

```
remote-rocket/
│
├── docker-compose.yml          # The only file you need to run everything
├── .env                        # API keys and config (never commit this)
├── .env.example                # Template with placeholder values (safe to commit)
├── README.md
├── ARCHITECTURE.md
│
├── scraper/                    # Job collection service
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                 # Entry point: orchestrates all scrapers
│   ├── jobspy_scraper.py       # JobSpy integration (LinkedIn, Indeed, etc.)
│   ├── career_page_scraper.py  # Crawl4AI company career page crawler
│   ├── llm_extractor.py        # Claude API extraction + scoring
│   ├── deduplicator.py         # Prevents duplicate jobs in DB
│   ├── scheduler.py            # Cron-style scheduling
│   └── config_validator.py     # Validates YAML config on startup
│
├── app/                        # Streamlit web UI
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── Home.py                 # Main entry point (first sidebar nav item)
│   ├── .streamlit/config.toml  # Base dark theme tokens
│   ├── components/theme.py     # Lionheart dark theme CSS (apply_theme)
│   ├── pages/
│   │   ├── 1_Browse_Jobs.py    # Main job board view
│   │   ├── 2_Saved_Jobs.py     # Bookmarked / shortlisted
│   │   ├── 3_Applications.py   # Application tracker
│   │   └── 4_Settings.py       # Companies, keywords, scrape status, logs
│   └── components/
│       ├── job_card.py         # Reusable job card widget
│       ├── filters.py          # Sidebar filter components
│       └── db.py               # Database access layer (shared by all pages)
│
├── db/
│   └── jobs.db                 # SQLite database (auto-created, persisted via volume)
│
├── config/
│   ├── keywords.yml            # Search keywords and role targeting
│   └── companies.yml           # Target company career page URLs
│
└── logs/
    └── scraper.log             # Persisted via volume
```

---

## 2. Database Schema

```sql
-- jobs.db (SQLite)

CREATE TABLE jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Core identifiers
    source          TEXT NOT NULL,          -- 'jobspy', 'career_page', 'linkedin', etc.
    external_id     TEXT,                   -- Source's own job ID (for dedup)
    url             TEXT UNIQUE NOT NULL,   -- Apply/listing URL (PRIMARY dedup key)
    source_url      TEXT,                   -- The page the job was found on (career page URL, board URL)

    -- Job details (LLM-extracted)
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    location        TEXT,                   -- Should be "Remote" but keep for reference
    employment_type TEXT,                   -- 'full_time', 'contract', 'part_time'

    -- Salary (extracted + normalized)
    salary_min      INTEGER,                -- Annual, USD
    salary_max      INTEGER,                -- Annual, USD
    salary_raw      TEXT,                   -- Original salary string before any parsing
    salary_currency TEXT DEFAULT 'USD',

    -- Content
    description_raw   TEXT,                 -- Original job description HTML/text
    description_clean TEXT,                 -- Cleaned plain text version
    requirements      TEXT,                 -- JSON array: ["5+ years Google Ads", ...]
    skills_detected   TEXT,                 -- JSON array: ["Google Ads", "Meta Ads", ...]

    -- LLM extraction audit
    raw_llm_response  TEXT,                 -- Full JSON response from Claude (for debugging + re-processing)

    -- Scoring (LLM-assigned)
    relevance_score INTEGER,                -- 1–10: how well it fits the target profile
    salary_score    INTEGER,                -- Derived: salary vs configured threshold

    -- Skill flags (LLM-assigned booleans)
    is_fully_remote INTEGER DEFAULT 0,      -- 1 = confirmed fully remote
    is_hidden_gem   INTEGER DEFAULT 0,      -- 1 = sourced from career page, not a job board
    has_google_ads  INTEGER DEFAULT 0,      -- Google Ads explicitly required
    has_msft_ads    INTEGER DEFAULT 0,      -- Microsoft Ads mentioned
    has_gtm         INTEGER DEFAULT 0,      -- Google Tag Manager
    has_gmc         INTEGER DEFAULT 0,      -- Google Merchant Center
    is_excluded     INTEGER DEFAULT 0,      -- Filtered out by LLM (social media focus, etc.)
    exclusion_reason TEXT,                  -- Why it was excluded

    -- Freshness tracking
    is_active       INTEGER DEFAULT 1,      -- 0 = job no longer appears in scrapes (expired/filled)
    last_seen_at    TEXT,                   -- Timestamp of most recent scrape that found this job
    date_posted     TEXT,                   -- ISO date string from source
    date_scraped    TEXT DEFAULT (datetime('now')),
    date_updated    TEXT,

    -- Phase 2: Resume tailoring (columns exist now, populated later)
    -- tailored_resume TEXT,
    -- cover_letter    TEXT,
    -- resume_version  TEXT,

    UNIQUE(url)
);

CREATE TABLE applications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          INTEGER NOT NULL REFERENCES jobs(id),

    status          TEXT DEFAULT 'saved',
    -- Valid values: 'saved', 'applied', 'phone_screen', 'interview',
    --               'offer', 'rejected', 'withdrawn'

    applied_date    TEXT,
    notes           TEXT,                   -- Free text notes
    follow_up_date  TEXT,                   -- Reminder date
    contact_name    TEXT,                   -- Recruiter or hiring manager name
    contact_email   TEXT,

    -- Phase 2: Generated content
    -- resume_used   TEXT,
    -- cover_letter  TEXT,

    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT
);

-- Scrape run log (powers the Settings page observability panel)
CREATE TABLE scrape_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT,                   -- 'running', 'success', 'partial', 'failed'
    jobs_fetched    INTEGER DEFAULT 0,
    jobs_new        INTEGER DEFAULT 0,
    jobs_excluded   INTEGER DEFAULT 0,
    errors          INTEGER DEFAULT 0,
    error_details   TEXT                    -- JSON array of error messages
);

-- Indexes
CREATE INDEX idx_jobs_salary_min       ON jobs(salary_min);
CREATE INDEX idx_jobs_employment_type  ON jobs(employment_type);
CREATE INDEX idx_jobs_date_posted      ON jobs(date_posted);
CREATE INDEX idx_jobs_relevance_score  ON jobs(relevance_score);
CREATE INDEX idx_jobs_is_excluded      ON jobs(is_excluded);
CREATE INDEX idx_jobs_is_active        ON jobs(is_active);
CREATE INDEX idx_jobs_company          ON jobs(company);
CREATE INDEX idx_jobs_last_seen_at     ON jobs(last_seen_at);
CREATE INDEX idx_applications_status   ON applications(status);
```

### Key Schema Decisions

- **`url` is the primary dedup key.** It's the most stable identifier across all sources.
- **`raw_llm_response`** stores the full Claude JSON output. If the extraction prompt improves in future, you can re-process existing jobs without re-scraping.
- **`is_active` + `last_seen_at`** enable job expiration. A job not seen in 45–60 days gets marked inactive automatically.
- **`scrape_runs` table** powers the Settings page observability panel — last run time, counts, errors — without parsing log files.
- **Phase 2 columns** are commented in-place so the intent is clear and activation is a single `ALTER TABLE`.

---

## 3. Deduplication Strategy

Duplicates are common: the same job may appear on LinkedIn, Indeed, and the company's own careers page.

**Primary key: `url`**
The apply/listing URL is the most reliable unique identifier. The `UNIQUE(url)` constraint handles the simple case.

**Secondary check: normalized title + company**
When URLs differ (e.g. a job board wraps the original URL), a second check catches near-duplicates:

```python
# scraper/deduplicator.py

import re

def normalize(text: str) -> str:
    """Lowercase, strip punctuation and extra whitespace."""
    return re.sub(r'[^a-z0-9 ]', '', text.lower()).strip()

def is_duplicate(db_conn, url: str, title: str, company: str) -> bool:
    # Fast path: exact URL match
    row = db_conn.execute(
        "SELECT id FROM jobs WHERE url = ?", (url,)
    ).fetchone()
    if row:
        return True

    # Slow path: normalized title + company match posted in last 30 days
    norm_title = normalize(title)
    norm_company = normalize(company)
    row = db_conn.execute("""
        SELECT id FROM jobs
        WHERE lower(replace(replace(title, '-', ' '), '_', ' ')) = ?
          AND lower(company) = ?
          AND date_scraped >= date('now', '-30 days')
    """, (norm_title, norm_company)).fetchone()
    return row is not None

def update_last_seen(db_conn, url: str):
    """Called when a job is found again in a subsequent scrape."""
    db_conn.execute(
        "UPDATE jobs SET last_seen_at = datetime('now'), is_active = 1 WHERE url = ?",
        (url,)
    )
```

**Job expiration:**
A nightly cleanup step marks jobs inactive if not seen recently:

```python
def expire_stale_jobs(db_conn, days: int = 45):
    db_conn.execute("""
        UPDATE jobs
        SET is_active = 0
        WHERE is_active = 1
          AND last_seen_at < datetime('now', ? || ' days')
          AND id NOT IN (SELECT job_id FROM applications)
    """, (f"-{days}",))
```

Applied jobs are never auto-expired regardless of age.

---

## 4. Scraping Strategy

### 4a. JobSpy (Job Boards — Volume)

JobSpy scrapes LinkedIn, Indeed, Glassdoor, and ZipRecruiter from a single Python call. No API key required.

```python
# scraper/jobspy_scraper.py

from jobspy import scrape_jobs
import logging

log = logging.getLogger("remote-rocket.jobspy")

SEARCH_TERMS = [
    "remote performance marketing manager",
    "remote paid search manager",
    "remote SEM manager",
    "remote Google Ads specialist",
    "remote paid media manager",
    "remote growth marketing manager",
    "remote PPC manager",
    "remote biddable media manager",
]

def run_jobspy_scrape() -> list[dict]:
    all_jobs = []

    for term in SEARCH_TERMS:
        try:
            jobs_df = scrape_jobs(
                site_name=["linkedin", "indeed", "glassdoor", "zip_recruiter"],
                search_term=term,
                location="Remote",
                results_wanted=50,
                hours_old=48,
                country_indeed="USA",
            )
            count = len(jobs_df)
            log.info(f"JobSpy: '{term}' → {count} results")
            all_jobs.extend(jobs_df.to_dict('records'))
        except Exception as e:
            log.error(f"JobSpy failed for term '{term}': {e}")
            # Continue with next term — don't abort the whole run

    return all_jobs
```

### 4b. Crawl4AI (Company Career Pages — Hidden Gems)

This is the highest-value scraper. Companies post on their own careers pages days before job boards — or exclusively there.

**Guardrails:**
- **Rate limiting:** 3–5 second delay between requests
- **Exponential backoff:** Retry up to 3 times on failure
- **Failure isolation:** One failed company never blocks others
- **Respectful crawling:** Only scrape the jobs listing page, not the entire site

```python
# scraper/career_page_scraper.py

import asyncio
import logging
import random
from crawl4ai import AsyncWebCrawler
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger("remote-rocket.career-pages")

# Polite delay range between requests (seconds)
MIN_DELAY = 3
MAX_DELAY = 6

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30)
)
async def scrape_single_page(crawler: AsyncWebCrawler, company: dict) -> dict:
    """Fetch one career page. Retries up to 3 times with backoff."""
    result = await crawler.arun(
        url=company["careers_url"],
        timeout=30,
        wait_for="body",
    )

    if not result.success:
        raise ValueError(f"Crawl failed for {company['name']}: {result.error_message}")

    return {
        "company": company["name"],
        "source_url": company["careers_url"],
        "raw_content": result.markdown,
        "is_hidden_gem": True,
        "is_high_priority": company.get("high_priority", False),
    }

async def run_career_page_scrape(companies: list[dict]) -> list[dict]:
    results = []

    async with AsyncWebCrawler(headless=True) as crawler:
        for company in companies:
            try:
                data = await scrape_single_page(crawler, company)
                results.append(data)
                log.info(f"Career page scraped: {company['name']}")
            except Exception as e:
                log.error(f"Career page failed after retries — {company['name']}: {e}")
                # Record the failure but keep going
            finally:
                # Polite delay between all requests, success or failure
                await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

    return results
```

### Career Page Seed List Strategy

Start with a curated list of 40–80 high-value companies rather than scraping broadly. Quality over quantity.

**Selection criteria for the seed list:**
- Known to hire remote performance marketing roles
- Agencies and large SaaS companies (highest volume of relevant roles)
- Companies that don't always post to LinkedIn/Indeed

**Mark high-priority companies** in `companies.yml` — these get scraped on every run. Others can be rotated.

---

## 5. LLM Extraction with Claude API

Every job — from JobSpy or a career page — passes through Claude for structured extraction and scoring. This ensures consistent, queryable data regardless of source.

```python
# scraper/llm_extractor.py

import anthropic
import json
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger("remote-rocket.extractor")
client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

EXTRACTION_PROMPT = """You are a job listing analyzer for a senior performance marketing professional.
They are looking for fully remote digital marketing roles focused on paid search and performance marketing.

Analyze the following job listing and return ONLY a valid JSON object — no markdown, no explanation.

Required fields:
{
  "title": "exact job title",
  "company": "company name",
  "employment_type": "full_time" | "contract" | "part_time",
  "is_fully_remote": true | false,
  "salary_min": integer or null,
  "salary_max": integer or null,
  "salary_raw": "original salary text, or null if not mentioned",
  "requirements": ["requirement 1", "requirement 2"],
  "skills_detected": ["Google Ads", "Microsoft Ads", "GTM"],
  "has_google_ads": true | false,
  "has_msft_ads": true | false,
  "has_gtm": true | false,
  "has_gmc": true | false,
  "is_excluded": true | false,
  "exclusion_reason": "string explaining why, or null",
  "relevance_score": integer 1-10,
  "date_posted": "YYYY-MM-DD or null"
}

SALARY NORMALIZATION:
- Convert all salaries to annual USD integers
- Hourly: multiply by 2080 (40 hrs × 52 weeks)
- Monthly: multiply by 12
- If a range is given, set both salary_min and salary_max
- If only one number, set salary_min and leave salary_max null

RELEVANCE SCORE GUIDE:
- 9–10: Explicitly requires Google Ads or Microsoft Ads management; paid search is the primary function
- 7–8: Strong paid media focus; performance marketing with clear SEM component
- 5–6: General digital marketing with some paid component
- 3–4: Tangentially related (marketing ops, analytics adjacent)
- 1–2: Minimal relevance

SKILL FLAG RULES:
- has_google_ads = true if Google Ads, Google Search Ads, or PPC on Google is mentioned
- has_msft_ads = true if Microsoft Ads, Bing Ads, or MSAN is mentioned
- has_gtm = true if Google Tag Manager or GTM is mentioned
- has_gmc = true if Google Merchant Center or Shopping Feed is mentioned

EXCLUDE (set is_excluded=true) if ANY of these are true:
- Role is primarily social media marketing without a paid search component
- Role requires in-office attendance (hybrid or on-site)
- Salary is explicitly below $80k/year
- Role is content marketing, SEO only, or email marketing only
- Role is clearly entry level (< 2 years experience required)

Job listing:
{job_text}
"""

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=20)
)
def _call_claude(job_text: str) -> str:
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",  # Fast + cheap for high-volume extraction
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": EXTRACTION_PROMPT.format(job_text=job_text[:8000])
        }]
    )
    return message.content[0].text

def extract_job_data(job_text: str, source_metadata: dict) -> dict | None:
    """Extract structured job data via Claude. Returns None on unrecoverable failure."""
    try:
        raw_response = _call_claude(job_text)

        # Strip markdown code fences if Claude wrapped the JSON
        clean = raw_response.strip().removeprefix("```json").removesuffix("```").strip()
        extracted = json.loads(clean)

        # Merge in source metadata
        extracted.update(source_metadata)

        # Store raw LLM response for debugging
        extracted["raw_llm_response"] = raw_response

        return extracted

    except json.JSONDecodeError as e:
        log.error(f"Claude returned invalid JSON: {e}\nRaw: {raw_response[:500]}")
        return None
    except Exception as e:
        log.error(f"LLM extraction failed after retries: {e}")
        return None
```

**Model choice:** `claude-haiku-4-5` for extraction — fast (~1–2s) and cheap (~$0.001/job).
**Cost estimate:** 200 jobs/night × $0.001 = ~$0.20/night = ~$6/month.
**Reserve Sonnet** for Phase 2 resume tailoring where quality matters.

---

## 6. Configuration

### `.env` (never commit)
```bash
ANTHROPIC_API_KEY=sk-ant-your-key-here
SCRAPE_INTERVAL_HOURS=12
SALARY_MIN_DEFAULT=100000
JOB_EXPIRY_DAYS=45
LOG_LEVEL=INFO
```

### `config/keywords.yml`
```yaml
# Job board search terms (used by JobSpy)
search_terms:
  - "remote performance marketing manager"
  - "remote paid search manager"
  - "remote SEM manager"
  - "remote Google Ads manager"
  - "remote paid media manager"
  - "remote PPC manager"
  - "remote growth marketing paid search"
  - "remote biddable media manager"

# Keywords that boost relevance in job titles
title_boost_keywords:
  - "paid search"
  - "SEM"
  - "PPC"
  - "performance marketing"
  - "biddable media"
  - "search advertising"

# Jobs with these in the title are auto-excluded before LLM extraction
# (saves API cost on obvious non-matches)
title_exclusions:
  - "social media manager"
  - "content marketing"
  - "SEO specialist"
  - "email marketing"
  - "community manager"
  - "influencer marketing"
```

### `config/companies.yml`
```yaml
# Career pages to scrape directly
# high_priority: true = scraped on every run
# high_priority: false (default) = scraped every other run

companies:

  # Agencies (highest volume of relevant roles)
  - name: "Tinuiti"
    careers_url: "https://tinuiti.com/careers/"
    high_priority: true

  - name: "Wpromote"
    careers_url: "https://www.wpromote.com/careers"
    high_priority: true

  - name: "Logical Position"
    careers_url: "https://www.logicalposition.com/careers"
    high_priority: true

  - name: "Jellyfish"
    careers_url: "https://www.jellyfish.com/en-us/careers"
    high_priority: true

  - name: "PMG"
    careers_url: "https://www.pmg.com/careers/"
    high_priority: true

  # SaaS / Tech companies with strong marketing teams
  - name: "HubSpot"
    careers_url: "https://www.hubspot.com/careers/jobs"
    high_priority: false

  - name: "Klaviyo"
    careers_url: "https://www.klaviyo.com/careers"
    high_priority: false

  - name: "Semrush"
    careers_url: "https://www.semrush.com/careers/"
    high_priority: false

  - name: "Bazaarvoice"
    careers_url: "https://www.bazaarvoice.com/careers/"
    high_priority: false

  # Add more companies here — no code changes needed
```

### Configuration Validation

On startup, the scraper validates both YAML files before running:

```python
# scraper/config_validator.py

import yaml
import sys
import logging

log = logging.getLogger("remote-rocket.config")

REQUIRED_KEYWORDS_KEYS = ["search_terms", "title_boost_keywords", "title_exclusions"]
REQUIRED_COMPANY_KEYS  = ["name", "careers_url"]

def load_and_validate_keywords(path: str) -> dict:
    with open(path) as f:
        config = yaml.safe_load(f)

    for key in REQUIRED_KEYWORDS_KEYS:
        if key not in config:
            log.error(f"keywords.yml is missing required key: '{key}'")
            sys.exit(1)
        if not isinstance(config[key], list):
            log.error(f"keywords.yml: '{key}' must be a list")
            sys.exit(1)

    if not config["search_terms"]:
        log.error("keywords.yml: 'search_terms' cannot be empty")
        sys.exit(1)

    log.info(f"keywords.yml loaded: {len(config['search_terms'])} search terms")
    return config

def load_and_validate_companies(path: str) -> list[dict]:
    with open(path) as f:
        config = yaml.safe_load(f)

    companies = config.get("companies", [])
    if not companies:
        log.error("companies.yml: 'companies' list is empty or missing")
        sys.exit(1)

    for i, company in enumerate(companies):
        for key in REQUIRED_COMPANY_KEYS:
            if key not in company:
                log.error(f"companies.yml: entry #{i+1} is missing required key: '{key}'")
                sys.exit(1)

    log.info(f"companies.yml loaded: {len(companies)} companies")
    return companies
```

The scraper exits with a clear error message if config is malformed — before wasting any API calls.

---

## 7. Streamlit UI Structure

### Pages

| File | Purpose |
|---|---|
| `Home.py` | App entry point, page config |
| `components/theme.py` | Lionheart dark theme (fonts, colors, CSS) |
| `pages/1_Browse_Jobs.py` | Main job board with sidebar filters |
| `pages/2_Saved_Jobs.py` | Bookmarked / shortlisted jobs |
| `pages/3_Applications.py` | Kanban-style application tracker |
| `pages/4_Settings.py` | Company list, keyword config, scrape status, logs |

### Browse Jobs Layout

```
┌─────────────────────┬────────────────────────────────────────────────┐
│  FILTERS            │  147 jobs found  (sorted by: Relevance ▼)      │
│                     │                                                  │
│  Salary             │  ┌────────────────────────────────────────────┐ │
│  [$100k] ──────     │  │ 🟢 Sr. Paid Search Manager                 │ │
│                     │  │    Klaviyo · Remote · Full-time             │ │
│  Employment Type    │  │    $120k–$150k · Score: 9/10               │ │
│  ☑ Full-time        │  │    ✓ Google Ads  ✓ Microsoft Ads            │ │
│  ☑ Contract         │  │    Posted: 2 days ago · 💎 Career Page      │ │
│  ☐ Part-time        │  │    [View Details]  [Save]  [Mark Applied]   │ │
│                     │  └────────────────────────────────────────────┘ │
│  Skills Required    │                                                  │
│  ☑ Google Ads       │                                                  │
│  ☑ Microsoft Ads    │                                                  │
│  ☐ GTM              │                                                  │
│  ☐ Google Merchant  │                                                  │
│                     │                                                  │
│  Source             │                                                  │
│  ☑ Job boards       │                                                  │
│  ☑ 💎 Career pages  │                                                  │
│                     │                                                  │
│  Date Posted        │                                                  │
│  Last: [7 days ▼]   │                                                  │
│                     │                                                  │
│  Show inactive      │                                                  │
│  ☐ Include expired  │                                                  │
│                     │                                                  │
│  Keywords           │                                                  │
│  [search titles...] │                                                  │
└─────────────────────┴────────────────────────────────────────────────┘
```

### Settings Page — Observability Panel

```
┌─────────────────────────────────────────────────────────────┐
│  SCRAPER STATUS                                              │
│                                                              │
│  Last successful run:  2026-06-30 02:14 AM                  │
│  Status:               ✅ Success                            │
│  Jobs fetched:         312   New:  47   Excluded:  89        │
│  Errors:               2  [Show details ▼]                   │
│                                                              │
│  Next scheduled run:   2026-06-30 02:14 PM                  │
│                                                              │
│  [▶ Run Now]                                                 │
└─────────────────────────────────────────────────────────────┘
```

The Settings page reads from the `scrape_runs` table — no log file parsing needed.

### Application Tracker

Kanban-style status columns:
```
Saved (12) → Applied (5) → Phone Screen (2) → Interview (1) → Offer (0)
```
Each card shows: company, title, applied date, follow-up date, notes.

---

## 8. Scheduling

```python
# scraper/scheduler.py

import schedule
import time
import os
import logging
from main import run_full_scrape

log = logging.getLogger("remote-rocket.scheduler")
INTERVAL_HOURS = int(os.getenv("SCRAPE_INTERVAL_HOURS", 12))

def main():
    log.info(f"Scheduler started. Scraping every {INTERVAL_HOURS} hours.")
    run_full_scrape()  # Run immediately on startup
    schedule.every(INTERVAL_HOURS).hours.do(run_full_scrape)

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
```

---

## 9. Error Handling & Logging

```python
# scraper/main.py — orchestrates the full scrape run

import logging
import os
import sqlite3
import json
from datetime import datetime

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("/app/logs/scraper.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("remote-rocket")

def run_full_scrape():
    started_at = datetime.now().isoformat()
    stats = {"fetched": 0, "new": 0, "excluded": 0, "errors": 0, "error_details": []}
    log.info(f"=== Scrape started at {started_at} ===")

    db = sqlite3.connect("/app/db/jobs.db")

    # Record run start
    run_id = db.execute(
        "INSERT INTO scrape_runs (started_at, status) VALUES (?, 'running')",
        (started_at,)
    ).lastrowid
    db.commit()

    # 1. JobSpy
    try:
        board_jobs = run_jobspy_scrape()
        stats["fetched"] += len(board_jobs)
    except Exception as e:
        log.error(f"JobSpy scrape failed: {e}")
        stats["errors"] += 1
        stats["error_details"].append(f"JobSpy: {str(e)}")
        board_jobs = []

    # 2. Career pages
    try:
        career_jobs = asyncio.run(run_career_page_scrape(companies))
        stats["fetched"] += len(career_jobs)
    except Exception as e:
        log.error(f"Career page scrape failed: {e}")
        stats["errors"] += 1
        stats["error_details"].append(f"Career pages: {str(e)}")
        career_jobs = []

    # 3. Extract + save (each job isolated — one failure never blocks others)
    for raw_job in board_jobs + career_jobs:
        try:
            if is_duplicate(db, raw_job.get("url", ""), raw_job.get("title", ""), raw_job.get("company", "")):
                update_last_seen(db, raw_job.get("url", ""))
                continue

            extracted = extract_job_data(raw_job.get("description", ""), raw_job)
            if extracted is None:
                stats["errors"] += 1
                continue

            save_job(db, extracted)

            if extracted.get("is_excluded"):
                stats["excluded"] += 1
            else:
                stats["new"] += 1
                log.info(f"New: {extracted['title']} @ {extracted['company']} (score: {extracted.get('relevance_score')})")

        except Exception as e:
            log.error(f"Failed to process job: {e}")
            stats["errors"] += 1
            stats["error_details"].append(str(e))

    # 4. Expire stale jobs
    expire_stale_jobs(db, days=int(os.getenv("JOB_EXPIRY_DAYS", 45)))

    # 5. Record run completion
    finished_at = datetime.now().isoformat()
    status = "success" if stats["errors"] == 0 else ("partial" if stats["new"] > 0 else "failed")
    db.execute("""
        UPDATE scrape_runs
        SET finished_at=?, status=?, jobs_fetched=?, jobs_new=?, jobs_excluded=?, errors=?, error_details=?
        WHERE id=?
    """, (finished_at, status, stats["fetched"], stats["new"], stats["excluded"],
          stats["errors"], json.dumps(stats["error_details"]), run_id))
    db.commit()
    db.close()

    log.info(f"=== Scrape done. New: {stats['new']}, Excluded: {stats['excluded']}, Errors: {stats['errors']} ===")
```

**Logging philosophy:**
- `INFO`: New jobs found, scrape summaries, startup messages
- `WARNING`: Retried operations, unexpected but recoverable conditions
- `ERROR`: Failed jobs, failed scrapers — logged but never crash the run
- `DEBUG`: Per-job details, raw API responses (enable via `LOG_LEVEL=DEBUG` in `.env`)

---

## 10. Docker Compose & VPS Deployment

### `docker-compose.yml`
```yaml
version: "3.9"

services:
  scraper:
    build: ./scraper
    container_name: remote-rocket-scraper
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./db:/app/db
      - ./logs:/app/logs
      - ./config:/app/config

  app:
    build: ./app
    container_name: remote-rocket-app
    restart: unless-stopped
    env_file: .env
    ports:
      - "8501:8501"
    volumes:
      - ./db:/app/db
      - ./config:/app/config
    depends_on:
      - scraper

  nginx:
    image: nginx:alpine
    container_name: remote-rocket-nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/certs:/etc/nginx/certs:ro
    depends_on:
      - app
```

### VPS Setup (one-time, ~10 minutes)
```bash
# Fresh Ubuntu 22.04 — Hetzner CX22 (~$4/mo) or DigitalOcean Basic ($6/mo)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

git clone https://github.com/Leewho-notdev/remote-rocket.git
cd remote-rocket
cp .env.example .env
nano .env  # Add ANTHROPIC_API_KEY

docker compose up -d
docker compose logs -f scraper  # Watch first run
```

After that: **zero maintenance required.** Containers restart automatically. New jobs appear every 12 hours.

**VPS recommendation:** Hetzner CX22 (2 vCPU, 4GB RAM) at ~$4/mo. Chromium (used by Crawl4AI) needs at least 1GB RAM; 4GB gives comfortable headroom.

---

## 11. Key Libraries

| Library | Purpose | Why |
|---|---|---|
| `jobspy` | Scrape LinkedIn, Indeed, Glassdoor, ZipRecruiter | Single call, no API keys, actively maintained |
| `crawl4ai` | Fetch JS-rendered career pages | LLM-native markdown output, built-in anti-bot handling |
| `anthropic` | Claude API client | Structured extraction + Phase 2 resume generation |
| `streamlit` | Web UI | Zero frontend code, Python-only, perfect for non-developers |
| `schedule` | Cron-style scheduling in Python | Simpler than system cron, no extra infrastructure |
| `tenacity` | Retry logic | Clean decorator-based retries for API calls and scraping |
| `pyyaml` | Read YAML config | Human-editable without JSON's strict syntax |
| `sqlite3` | Database | Built into Python, zero setup, inspectable with DB Browser |

**Deliberately excluded:** SQLAlchemy, Celery/Redis, FastAPI, Alembic — all overkill for a personal tool.

---

## 12. Phase 1 vs Phase 2

### Phase 1 — Build Now ✅
- [x] JobSpy scraping (job boards)
- [x] Crawl4AI career page scraping with rate limiting + retries
- [x] Curated seed list of 40–80 companies with high-priority flagging
- [x] Claude extraction pipeline with structured prompt
- [x] SQLite database with full schema
- [x] Deduplication (URL primary + normalized title/company secondary)
- [x] Job freshness tracking (`is_active`, `last_seen_at`, auto-expiry at 45 days)
- [x] Streamlit UI with all filters
- [x] Application tracker with status pipeline
- [x] Settings page with scrape observability (`scrape_runs` table)
- [x] Config validation on startup
- [x] Docker Compose deployment
- [x] Scheduled scraping every 12 hours

### Phase 2 — Shipped ✅

Resume tailoring + cover letter generation, triggered from any job (Browse Jobs or the Applications board). Designed mobile-first with a one-tap flow and no required manual editing.

**What shipped:**
```
app/pages/5_My_Resume.py             # Upload PDF/DOCX (or paste) → Claude structuring pass → read-only preview
app/pages/6_Tailor.py                # One-tap tailoring: generate, regenerate-with-note, versions, .docx export
app/components/resume_generator.py   # Claude: structuring pass (Haiku) + tailoring (Sonnet) + structured→markdown
app/components/resume_store.py        # master_resume + tailored_documents data layer; self-healing schema
app/components/resume_files.py        # PDF/DOCX text extraction (in) + markdown→.docx export (out)
prompts/tailoring_prompts.yml        # Structuring + tailoring prompts, editable without a rebuild (mounted volume)
```

**Data model:**
- `master_resume` — a single upserted row (id = 1) holding `raw_text`, `structured_json`, and source filename. On upload the text is extracted, then a lightweight Claude pass structures it into sections (contact, summary, experience, skills, education, certifications). Both raw and structured forms are stored; if structuring fails, `structured_json` is NULL and everything falls back to raw text.
- `tailored_documents` — versioned generations **keyed by `job_id`** (`version`, `resume_md`, `cover_letter_md`, `notes`, `created_at`). Keying on the job (not the application) means a job can be tailored straight from Browse Jobs before it's ever saved. Regenerating adds a new version rather than overwriting.
- Both are new tables, so no `ALTER` migration is needed — `CREATE TABLE IF NOT EXISTS` in `schema.sql` covers fresh + existing DBs. The app also self-heals the schema on load (`ensure_phase2_schema`, including an `ADD COLUMN structured_json` guard) so it works before the scraper container restarts.

**Models:** tailoring uses `claude-sonnet-4-6` (`RESUME_MODEL`) — quality matters for a document you send to employers. The one-time structuring pass uses cheap `claude-haiku-4-5` (`STRUCTURE_MODEL`). Tailoring feeds Claude the clean structured render (`resume_text_for_tailoring`), falling back to raw text. Generation runs in the **app** container (interactive), not the scraper, so `anthropic`, `pypdf`, and `python-docx` are app dependencies.

**Output:** editable markdown in the UI (edit optional), exported as ATS-friendly `.docx` for both resume and cover letter, plus copy-to-clipboard.

**Design notes / deviations from the original briefs:**
- The original architecture sketched a `scraper/resume_tailor.py` core, but tailoring is user-triggered and interactive, so it lives in the app container, not the batch scraper.
- A product brief proposed a hand-edited structured master resume (`st.data_editor` experience table). We keep the **structured data** (Claude structures the resume on upload and stores it as `structured_json`, which improves tailoring and powers the read-only preview) but **dropped the manual editing** — hand-editing a table on a phone conflicts with the dead-simple, mobile, no-editing priority. Setup is upload → auto-structure → read-only preview + Replace.

### Phase 3 — Ideas 🔜
- Batch tailoring across a shortlist
- Per-application interview-prep brief
- Optional OCR fallback for image-only PDF resumes
- Optional structured resume editing for power users

---

## First-Time Setup Checklist

1. Clone the repo onto your VPS
2. `cp .env.example .env` — add `ANTHROPIC_API_KEY`
3. Edit `config/companies.yml` — add target companies
4. Edit `config/keywords.yml` — tune search terms if needed
5. `docker compose up -d`
6. `docker compose logs -f scraper` — watch the first scrape run
7. Open `http://your-vps-ip:8501`

The system is then self-maintaining. New jobs appear every 12 hours automatically.
