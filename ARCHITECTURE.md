# Remote Rocket — Technical Architecture

> **Personal self-hosted remote job aggregator focused on performance marketing, paid search, and SEM roles.**
> Built for a non-developer to run and maintain via Docker Compose on a cheap VPS.

---

## Project Overview

A personal tool (similar in concept to Remote Rocketship) that aggregates remote digital marketing jobs, with a strong focus on:
- Performance marketing, paid search, SEM, PPC
- Google Ads, Microsoft Ads, Google Tag Manager, Google Merchant Center
- Fully remote roles, $100k+ salary
- "Hidden" jobs sourced directly from company career pages

**Tech stack:** Python · JobSpy · crawl4ai · Claude API (Anthropic) · Streamlit · SQLite · Docker Compose

---

## 1. Folder Structure

```
remote-rocket/
│
├── docker-compose.yml          # The only file you need to run everything
├── .env                        # Your API keys and config (never commit this)
├── .env.example                # Template with placeholder values (safe to commit)
├── README.md
│
├── scraper/                    # Job collection service
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                 # Entry point: runs all scrapers
│   ├── jobspy_scraper.py       # JobSpy integration (Indeed, LinkedIn, etc.)
│   ├── career_page_scraper.py  # Company career page crawler
│   ├── llm_extractor.py        # Claude API extraction + scoring
│   ├── deduplicator.py         # Prevents duplicate jobs in DB
│   └── scheduler.py            # Cron-style scheduling
│
├── app/                        # Streamlit web UI
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── streamlit_app.py        # Main entry point
│   ├── pages/
│   │   ├── 1_Browse_Jobs.py    # Main job board view
│   │   ├── 2_Saved_Jobs.py     # Bookmarked / shortlisted
│   │   ├── 3_Applications.py   # Application tracker
│   │   └── 4_Settings.py       # Manage target companies, keywords
│   └── components/
│       ├── job_card.py         # Reusable job card widget
│       ├── filters.py          # Sidebar filter components
│       └── db.py               # Database access layer (shared)
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
    url             TEXT UNIQUE NOT NULL,   -- Apply/listing URL (primary dedup key)

    -- Job details (LLM-extracted)
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    location        TEXT,                   -- Should be "Remote" but keep for reference
    employment_type TEXT,                   -- 'full_time', 'contract', 'part_time'

    -- Salary (extracted + normalized)
    salary_min      INTEGER,                -- Annual, USD
    salary_max      INTEGER,                -- Annual, USD
    salary_raw      TEXT,                   -- Original salary string before parsing
    salary_currency TEXT DEFAULT 'USD',

    -- Content
    description_raw  TEXT,                  -- Original job description HTML/text
    description_clean TEXT,                 -- Cleaned plain text version
    requirements     TEXT,                  -- JSON array: ["5+ years Google Ads", ...]
    skills_detected  TEXT,                  -- JSON array: ["Google Ads", "Meta Ads", ...]

    -- Scoring (LLM-assigned, 1-10)
    relevance_score INTEGER,                -- How well it matches your target profile
    salary_score    INTEGER,                -- Derived from salary vs your threshold

    -- Flags (LLM-assigned)
    is_fully_remote INTEGER DEFAULT 0,      -- Boolean: 1 = confirmed fully remote
    is_hidden_gem   INTEGER DEFAULT 0,      -- Boolean: sourced from career page, not a board
    has_google_ads  INTEGER DEFAULT 0,      -- Boolean: explicitly requires Google Ads
    has_msft_ads    INTEGER DEFAULT 0,      -- Boolean: Microsoft Ads mentioned
    has_gtm         INTEGER DEFAULT 0,      -- Boolean: Google Tag Manager
    has_gmc         INTEGER DEFAULT 0,      -- Boolean: Google Merchant Center
    is_excluded     INTEGER DEFAULT 0,      -- Boolean: filtered out (social media focus, etc.)
    exclusion_reason TEXT,                  -- Why it was excluded

    -- Metadata
    date_posted     TEXT,                   -- ISO date string
    date_scraped    TEXT DEFAULT (datetime('now')),
    date_updated    TEXT,

    -- Phase 2: Resume tailoring (columns exist now, populated later)
    -- tailored_resume TEXT,               -- Uncomment in Phase 2
    -- cover_letter    TEXT,               -- Uncomment in Phase 2
    -- resume_version  TEXT,               -- Which base resume was used

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

    -- Phase 2: Will store generated content
    -- resume_used     TEXT,               -- Path or content of tailored resume
    -- cover_letter    TEXT,               -- Generated cover letter

    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT
);

-- Useful indexes
CREATE INDEX idx_jobs_salary_min ON jobs(salary_min);
CREATE INDEX idx_jobs_employment_type ON jobs(employment_type);
CREATE INDEX idx_jobs_date_posted ON jobs(date_posted);
CREATE INDEX idx_jobs_relevance_score ON jobs(relevance_score);
CREATE INDEX idx_jobs_is_excluded ON jobs(is_excluded);
CREATE INDEX idx_applications_status ON applications(status);
```

---

## 3. Scraping Strategy

### 3a. JobSpy (Job Boards)

JobSpy scrapes LinkedIn, Indeed, Glassdoor, ZipRecruiter, and Google Jobs from a single call. No API key required.

```python
# scraper/jobspy_scraper.py

from jobspy import scrape_jobs

SEARCH_TERMS = [
    "remote performance marketing manager",
    "remote paid search manager",
    "remote SEM manager",
    "remote Google Ads specialist",
    "remote paid media manager",
    "remote growth marketing manager",
    "remote digital marketing manager paid search",
    "remote PPC manager",
    "remote biddable media manager",
]

def run_jobspy_scrape() -> list[dict]:
    all_jobs = []

    for term in SEARCH_TERMS:
        jobs_df = scrape_jobs(
            site_name=["linkedin", "indeed", "glassdoor", "zip_recruiter"],
            search_term=term,
            location="Remote",
            results_wanted=50,      # Per site per search term
            hours_old=48,           # Only last 48 hours (run nightly)
            country_indeed="USA",
        )
        all_jobs.extend(jobs_df.to_dict('records'))

    return all_jobs
```

### 3b. Company Career Page Scraper (The Hidden Gem Engine)

Companies post on their own careers pages days before job boards pick them up — or never post to boards at all. This scraper is the most valuable differentiation of the tool.

**Strategy:** Use `crawl4ai` (an LLM-friendly web crawler) to fetch career pages and pass the content to Claude for extraction. More reliable than brittle CSS selectors.

```python
# scraper/career_page_scraper.py

import asyncio
from crawl4ai import AsyncWebCrawler

async def scrape_career_page(company: dict) -> dict:
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=company["url"])
        return {
            "company": company["name"],
            "source_url": company["url"],
            "raw_content": result.markdown,
            "is_hidden_gem": True
        }

async def run_career_page_scrape(companies: list[dict]) -> list[dict]:
    tasks = [scrape_career_page(c) for c in companies]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if not isinstance(r, Exception)]
```

**Why `crawl4ai`:** Renders JavaScript (many career pages need it), handles anti-bot measures better than `requests`, and outputs clean markdown that Claude handles efficiently.

**Career page list management:** Users add companies to `config/companies.yml` — no code changes needed.

---

## 4. LLM Extraction with Claude API

Every job passes through Claude for structured extraction and scoring. This ensures consistent data quality regardless of source.

```python
# scraper/llm_extractor.py

import anthropic
import json

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

EXTRACTION_PROMPT = """You are a job listing analyzer for a senior performance marketing professional.
They are looking for fully remote digital marketing roles focused on paid search and performance marketing.

Analyze the following job listing and return a JSON object with these exact fields:

{
  "title": "exact job title",
  "company": "company name",
  "employment_type": "full_time" | "contract" | "part_time",
  "is_fully_remote": true | false,
  "salary_min": integer or null,   // annual USD, normalize if hourly/monthly
  "salary_max": integer or null,
  "salary_raw": "original salary text or null",
  "requirements": ["key requirement 1", "key requirement 2"],  // max 8 items
  "skills_detected": ["Google Ads", "Microsoft Ads"],  // tools/platforms mentioned
  "has_google_ads": true | false,
  "has_msft_ads": true | false,
  "has_gtm": true | false,         // Google Tag Manager
  "has_gmc": true | false,         // Google Merchant Center
  "is_excluded": true | false,
  "exclusion_reason": "string or null",
  "relevance_score": 1-10,         // 10 = perfect fit for paid search/SEM specialist
  "date_posted": "YYYY-MM-DD or null"
}

EXCLUDE (set is_excluded=true) if:
- Role is primarily social media marketing (Facebook/Instagram/TikTok without paid search)
- Role requires being in an office (not fully remote)
- Salary is clearly below $80k/year when stated
- Role is content marketing, SEO only, or email marketing only
- Role is entry level / requires less than 2 years experience

Score 8-10 if the role explicitly requires Google Ads, Microsoft Ads, or paid search management.
Score 5-7 for general digital marketing with some paid component.
Score 1-4 for tangentially related roles.

Job listing:
{job_text}
"""

def extract_job_data(job_text: str, source_metadata: dict) -> dict | None:
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",  # Fast + cheap for extraction
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": EXTRACTION_PROMPT.format(job_text=job_text[:8000])
            }]
        )

        raw_json = message.content[0].text
        raw_json = raw_json.strip().removeprefix("```json").removesuffix("```").strip()
        extracted = json.loads(raw_json)
        extracted.update(source_metadata)
        return extracted

    except Exception as e:
        print(f"Extraction failed: {e}")
        return None
```

**Model choice:** `claude-haiku-4-5` for extraction — fast and cheap (~$0.001/job). Reserve Sonnet for Phase 2 resume tailoring.

**Cost estimate:** ~200 jobs/night × $0.001 = ~$0.20/night = ~$6/month.

---

## 5. Streamlit UI Structure

### Pages

| File | Purpose |
|---|---|
| `streamlit_app.py` | App entry point, page config |
| `pages/1_Browse_Jobs.py` | Main job board with sidebar filters |
| `pages/2_Saved_Jobs.py` | Bookmarked / shortlisted jobs |
| `pages/3_Applications.py` | Kanban-style application tracker |
| `pages/4_Settings.py` | Company list, keyword config, manual scrape trigger |

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
│  ☐ Job boards only  │                                                  │
│  ☑ 💎 Career pages  │                                                  │
│                     │                                                  │
│  Date Posted        │                                                  │
│  Last: [7 days ▼]   │                                                  │
│                     │                                                  │
│  Keywords           │                                                  │
│  [search titles...] │                                                  │
└─────────────────────┴────────────────────────────────────────────────┘
```

### Application Tracker

Kanban-style status board:
```
Saved (12) → Applied (5) → Phone Screen (2) → Interview (1) → Offer (0)
```

---

## 6. Configuration

### `.env` (never commit)
```bash
ANTHROPIC_API_KEY=sk-ant-...
SCRAPE_INTERVAL_HOURS=12
SALARY_MIN_DEFAULT=100000
LOG_LEVEL=INFO
```

### `config/keywords.yml`
```yaml
search_terms:
  - "remote performance marketing manager"
  - "remote paid search manager"
  - "remote SEM manager"
  - "remote Google Ads manager"
  - "remote paid media manager"
  - "remote PPC manager"

title_boost_keywords:
  - "paid search"
  - "SEM"
  - "PPC"
  - "performance marketing"
  - "biddable media"

title_exclusions:
  - "social media manager"
  - "content marketing"
  - "SEO specialist"
  - "email marketing"
  - "community manager"
```

### `config/companies.yml`
```yaml
companies:
  - name: "HubSpot"
    careers_url: "https://www.hubspot.com/careers/jobs"

  - name: "Klaviyo"
    careers_url: "https://www.klaviyo.com/careers"

  - name: "Tinuiti"
    careers_url: "https://tinuiti.com/careers/"

  - name: "Wpromote"
    careers_url: "https://www.wpromote.com/careers"

  - name: "Logical Position"
    careers_url: "https://www.logicalposition.com/careers"
```

---

## 7. Scheduling

```python
# scraper/scheduler.py

import schedule
import time
import os
from main import run_full_scrape

INTERVAL_HOURS = int(os.getenv("SCRAPE_INTERVAL_HOURS", 12))

def main():
    run_full_scrape()  # Run immediately on startup
    schedule.every(INTERVAL_HOURS).hours.do(run_full_scrape)

    while True:
        schedule.run_pending()
        time.sleep(60)
```

---

## 8. Docker Compose & VPS Deployment

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
# Fresh Ubuntu 22.04 VPS
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

git clone https://github.com/YOUR_USERNAME/remote-rocket.git
cd remote-rocket
cp .env.example .env
nano .env  # Add ANTHROPIC_API_KEY

docker compose up -d
```

**VPS recommendation:** Hetzner CX22 (2 vCPU, 4GB RAM, ~$4/mo) or DigitalOcean Basic ($6/mo). Chromium for career page scraping needs ~1GB RAM minimum.

---

## 9. Error Handling & Logging

```python
import logging

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("/app/logs/scraper.log"),
        logging.StreamHandler()
    ]
)
```

**Retry strategy for Claude API:**
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def extract_job_data_with_retry(job_text, metadata):
    return extract_job_data(job_text, metadata)
```

**Key principle:** Each job is processed independently. One failure never stops the rest of the scrape run.

---

## 10. Key Libraries

| Library | Purpose | Why |
|---|---|---|
| `jobspy` | Scrape LinkedIn, Indeed, Glassdoor, ZipRecruiter | Single call, no API keys, actively maintained |
| `crawl4ai` | Fetch JS-rendered career pages | LLM-native markdown output, handles anti-bot |
| `anthropic` | Claude API | Structured extraction + Phase 2 resume generation |
| `streamlit` | Web UI | Zero frontend code, Python-only |
| `schedule` | Cron-style scheduling | Simpler than system cron, no extra dependencies |
| `tenacity` | Retry logic | Clean decorator-based retries for API calls |
| `pyyaml` | Read YAML config | Human-editable without JSON's strict syntax |
| `sqlite3` | Database | Built into Python, zero setup |

**Deliberately excluded:** SQLAlchemy, Celery/Redis, FastAPI, Alembic — all overkill for a personal tool.

---

## 11. Phase 1 vs Phase 2

### Phase 1 — Build Now
- [x] JobSpy scraping (job boards)
- [x] crawl4ai career page scraping
- [x] Claude extraction pipeline
- [x] SQLite database with full schema
- [x] Streamlit UI with filters
- [x] Application tracker
- [x] Docker Compose deployment
- [x] Scheduled scraping every 12 hours

### Phase 2 — Architecture Ready, Implement Later

**What's already scaffolded for Phase 2:**
- `jobs` table has commented-out `tailored_resume` and `cover_letter` columns
- `applications` table has commented-out `resume_used` and `cover_letter` columns
- Claude API already wired in — Phase 2 just needs a new prompt function
- `relevance_score` per job already exists for prioritizing tailoring

**What Phase 2 adds:**
```
app/pages/5_Resume_Workshop.py      # Upload base resume, manage versions
app/components/resume_generator.py  # Calls Claude: job + resume → tailored output
scraper/resume_tailor.py            # Core function: (job_id, resume_text) → tailored_resume, cover_letter
```

**Phase 2 Claude prompt sketch:**
```python
TAILORING_PROMPT = """
You are an expert resume writer for performance marketing professionals.

BASE RESUME:
{resume_text}

TARGET JOB:
Title: {job_title}
Company: {company}
Key Requirements: {requirements}
Skills Needed: {skills}

Rewrite the resume to:
1. Mirror the exact language from the job description for ATS optimization
2. Elevate the most relevant experience to the top of each role
3. Add quantified impact statements aligned with this company's metrics
4. Keep it truthful — only reorganize and reframe, never fabricate

Return JSON: {{"resume": "full resume text", "cover_letter": "cover letter text", "changes_summary": "3 bullet points"}}
"""
```

---

## First-Time Setup Checklist

1. `git clone` the repo onto your VPS
2. `cp .env.example .env` — add your `ANTHROPIC_API_KEY`
3. Edit `config/companies.yml` — add target companies
4. Edit `config/keywords.yml` — tune search terms
5. `docker compose up -d`
6. Wait ~5 minutes for first scrape
7. Open `http://your-vps-ip:8501`

The system is then self-maintaining. New jobs appear automatically every 12 hours.
