# 🚀 Remote Rocket

A self-hosted job aggregator built for performance marketers hunting fully remote roles. Scrapes LinkedIn, Indeed, Glassdoor, ZipRecruiter, and direct company career pages — then uses Claude AI to score and filter listings for relevance to paid search, SEM, and digital marketing. No more job board noise.

**Built for:** remote performance marketing, paid search, SEM, PPC, and Google/Microsoft Ads roles at $100k+  
**Deployed on:** any $5–8/mo VPS using Docker Compose

---

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/Leewho-notdev/remote-rocket.git
cd remote-rocket

cp .env.example .env
```

Open `.env` and fill in your Anthropic API key:

```
ANTHROPIC_API_KEY=sk-ant-your-real-key-here
```

Everything else in `.env` works out of the box. Adjust if needed (see [Configuration](#configuration)).

### 2. Start the stack

```bash
docker compose up -d
```

This starts two containers:
- **remote-rocket-scraper** — runs the scrape pipeline immediately, then every 12 hours
- **remote-rocket-app** — Streamlit UI on port 8501

### 3. Open the UI

```
http://localhost:8501
```

On a VPS, replace `localhost` with your server's IP address.

The first scrape runs automatically on startup. Expect 5–15 minutes before jobs appear, depending on your keyword and company lists.

---

## Features

### Browse Jobs (`/Browse Jobs`)

- Filter by salary, employment type (full-time / contract), source, date posted, relevance score, and skill flags (Google Ads, Microsoft Ads, GTM, Merchant Center)
- Jobs scored 1–10 by Claude based on fit for paid search / performance marketing profiles
- Hidden gems from direct company career pages are flagged separately
- Click any job to expand: full description, requirements, skills detected, and one-click save or apply

### Saved Jobs (`/Saved Jobs`)

Quick list of bookmarked listings. Mark as Applied or jump to the full pipeline.

### Applications (`/Applications`)

Kanban board tracking every application through the pipeline:

```
🔖 Saved → ✅ Applied → 📞 Phone Screen → 🎤 Interview → 🎉 Offer
```

Each card supports:
- Inline status changes (move between columns instantly)
- Notes (interview prep, impressions)
- Follow-up date reminders
- Recruiter contact info

Closed applications (Rejected / Withdrawn) are collapsed at the bottom.

### Settings (`/Settings`)

- **Manual trigger** — run a scrape immediately without waiting for the schedule
- **Run history** — last 10 scrape runs with fetched / new / scored / excluded / error counts
- **Config viewer** — live view of your keywords, company list, and environment settings
- **Next run estimate** — countdown to the next scheduled scrape

### My Resume (`/My Resume`)

Set up your resume **once**. Upload a PDF or Word (.docx) file (or paste text) — Claude reads it and automatically organizes it into clean sections (summary, experience, skills, education). You get a read-only preview and a big **Replace / Re-upload** button; nothing to hand-edit. Both the raw text and the structured version are stored, so tailoring has high-quality input.

### Tailor (`/Tailor`) — one tap, from anywhere

Tailor a resume and cover letter to a specific job, powered by Claude (Sonnet). Built to be usable from your phone, in bed, with **no manual editing required**:

- **One tap** — open any job on **Browse Jobs** or the **Applications** board, tap **✨ Tailor resume**, then hit **Generate**. Claude rewrites your resume to the job's priorities and drafts a matching cover letter — using *only* the real experience in your master resume (no invented history).
- **Regenerate with a note** — not quite right? Add a nudge like *"lean into ROAS + Performance Max wins"* and regenerate. Every generation is kept as a version.
- **Version history** — browse and download any past version per job.
- **Export** — download clean, ATS-friendly `.docx` files for the resume and cover letter, or copy the text. Editing is available inline but never necessary.

Tailored documents are versioned per job, so regenerating never overwrites your earlier work.

---

## Configuration

### Search keywords (`config/keywords.yml`)

Controls what gets searched on job boards:

```yaml
search_terms:
  - "remote paid search manager"
  - "remote Google Ads specialist"
  # add more as needed

title_exclusions:
  - "social media"
  - "SEO"
  # jobs matching these title keywords are pre-filtered before hitting the LLM
```

Changes take effect on the next scrape — no rebuild needed.

### Company career pages (`config/companies.yml`)

Direct career page monitoring for "hidden gem" listings not posted on job boards:

```yaml
companies:
  - name: Tinuiti
    careers_url: https://tinuiti.com/careers/
    high_priority: true   # scraped every run

  - name: Wpromote
    careers_url: https://www.wpromote.com/careers
    high_priority: false  # scraped every other run
```

`high_priority: true` companies are scraped every cycle. Standard companies rotate on alternating runs to reduce load.

### Environment (`.env`)

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required)* | Your Anthropic API key |
| `SCRAPE_INTERVAL_HOURS` | `12` | How often to run the full pipeline |
| `JOB_EXPIRY_DAYS` | `45` | Days before unseen jobs are marked inactive |
| `SALARY_MIN_DEFAULT` | `100000` | Default salary filter in the UI |
| `CLAUDE_MODEL` | `claude-haiku-4-5-20251001` | Model used for extraction (haiku is fast and cheap) |
| `RESUME_MODEL` | `claude-sonnet-4-6` | Model used for resume tailoring (quality over cost) |
| `STRUCTURE_MODEL` | `claude-haiku-4-5-20251001` | Model for the one-time resume structuring pass on upload (cheap) |
| `LOG_LEVEL` | `INFO` | Log verbosity (`DEBUG` for per-job detail) |

---

## Manual Scrape

Two ways to trigger a scrape outside the schedule:

**Via the UI:** Go to **Settings → Run Scrape Now**. The scraper picks up the trigger within ~60 seconds.

**Via Docker:**
```bash
docker exec remote-rocket-scraper python main.py
```

---

## Viewing Logs

```bash
# Live scraper output
docker logs -f remote-rocket-scraper

# Persistent log file (also saved to ./logs/scraper.log)
tail -f logs/scraper.log
```

---

## Updating

```bash
git pull
docker compose up -d --build
```

The database is stored in `./db/jobs.db` (a mounted volume) and is never touched by a rebuild.

---

## VPS Deployment

Tested on a $6/mo Hetzner CX11 (2 vCPU, 2GB RAM). Any 1GB+ VPS running Docker works.

```bash
# On your VPS
git clone https://github.com/Leewho-notdev/remote-rocket.git
cd remote-rocket
cp .env.example .env
nano .env   # add your API key
docker compose up -d
```

### Optional: Nginx + SSL

Uncomment the `nginx` block in `docker-compose.yml` and point your domain's A record at the VPS. An example `nginx/nginx.conf` is included in the repo.

---

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full technical design: schema, scraping strategy, LLM extraction approach, and Phase 2 plans (resume tailoring).

---

## Phase 2 (Shipped) ✅

Resume tailoring and cover letter generation per job. Set up a master resume once (**My Resume**), then tailor to any job in one tap (**Tailor**) with versioned history and ATS-friendly `.docx` export. Tuned to be mobile-friendly with no manual editing required.

Prompts live in [`prompts/tailoring_prompts.yml`](prompts/tailoring_prompts.yml) — edit them to change output style without touching code or rebuilding.

Next up: batch tailoring across a shortlist, an interview-prep brief per application, and optional structured resume editing.

