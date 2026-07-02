# Remote Rocket - Project Summary & History

**Project Name:** Remote Rocket  
**Goal:** A personal, self-hosted remote job aggregator focused on high-quality remote digital marketing / paid search / SEM / performance marketing roles ($100k+).  
**Started:** June 30, 2026  
**Current Phase:** Phase 2 shipped (resume + cover letter tailoring live). Phase 1 complete. Deployed and reachable at `rocket.lionheartsearch.com`.

---

## 1. Project Overview & Requirements

**Core Purpose**  
Build a free, personal alternative to Remote Rocketship that:
- Aggregates remote jobs in digital marketing, growth marketing, paid ads, SEM, and performance marketing.
- Strongly prioritizes roles involving **Google Ads, Microsoft Ads, Google Tag Manager, and Google Merchant Center**.
- Explicitly excludes social media marketing roles.
- Filters for $100k+ salary and Full-time vs Contract/Part-time.
- Emphasizes discovering "hidden" jobs directly from company career pages.

**Key Constraints from User**
- Zero Python knowledge → Everything must be runnable via Docker Compose with clear instructions.
- Wants to host on personal domain (`rocket.lionheartsearch.com`).
- Prefers cheap VPS (~$5–14/month).
- Wants to use Claude for code generation where possible.
- Wants the tool to eventually support resume + cover letter tailoring (Phase 2).

---

## 2. Key Architecture & Design Decisions

### Tech Stack (Final)

| Component          | Choice                          | Reason |
|--------------------|----------------------------------|--------|
| **Language/Runtime** | Python + Docker                | User has zero Python experience → Docker makes it manageable |
| **Web Framework**   | Streamlit                      | Zero frontend work, fast to build usable UI |
| **Database**        | SQLite                         | Simple, zero-config, sufficient for personal use |
| **Scraping**        | JobSpy + Crawl4AI              | JobSpy for volume on job boards; Crawl4AI for JS-heavy career pages |
| **LLM**             | Claude: Haiku for extraction/structuring, Sonnet for tailoring | Haiku is cheap for high-volume parsing; Sonnet quality matters for documents sent to employers |
| **Tunnel / Exposure** | Cloudflare Tunnel            | Easiest secure exposure without opening ports |
| **Scheduling**      | systemd + `cloudflared` service | Simple, reliable background running |
| **Deployment**      | Docker Compose on DigitalOcean | Cheap, reliable, easy for non-dev |

### Major Decisions & Rationale

- **Phased Approach (Phase 1 vs Phase 2)**: Core job discovery first, resume/cover letter tailoring later. This kept scope manageable.
- **Hybrid AI workflow**: Grok leads architecture, practicality, and deployment. Claude generates clean code. This played to each model's strengths.
- **Docker-first from day one**: Non-negotiable because user has zero Python experience.
- **YAML-based configuration** (`keywords.yml` + `companies.yml`): Allows user to modify targeting without touching code.
- **Two-pass deduplication** (URL first, then normalized title+company within 30 days): Robust against duplicates across sources.
- **Job freshness logic** (`is_active` + `last_seen_at` + `JOB_EXPIRY_DAYS`): Prevents stale jobs from cluttering results. Applied jobs are protected from auto-expiry.
- **Observability via `scrape_runs` table**: Important for a nomadic user who needs to monitor scraper health remotely.
- **Cloudflare Tunnel over opening ports**: Much safer and easier, especially on a cheap VPS.

### Phase 2 Decisions & Rationale (resume + cover letter tailoring)

- **Model split: Sonnet for tailoring, Haiku for the one-time structuring pass.** The tailored resume and cover letter are documents the user sends to employers, so quality wins over cost. The structuring pass (turning an uploaded resume into clean sections) is a cheap parsing task where Haiku is plenty. Both are overridable via `RESUME_MODEL` and `STRUCTURE_MODEL`.
- **Dropped the structured `st.data_editor` hand-editing that an early brief proposed.** The user's north star was "do it from bed on my phone, no manual editing." Hand-editing an experience table on mobile contradicts that. We still run the structuring pass and store the structured JSON (it improves tailoring quality and powers a read-only preview), but the user never edits it by hand. Setup is upload, auto-organize, read-only preview, big Replace button.
- **Tailoring runs in the app container, not the scraper.** It is user-triggered and interactive, so it belongs with the UI, not the batch scraper (an early sketch put it in a `scraper/resume_tailor.py`).
- **Versioned `tailored_documents`, keyed by `job_id` (not by application).** Keying on the job lets the user tailor straight from Browse Jobs before a job is ever saved, and "regenerate with a note" adds a new version instead of overwriting, so history is preserved.
- **Prompts live in `prompts/tailoring_prompts.yml`, external to the code.** The user can tune tone without touching Python or rebuilding (mounted volume, read fresh on each run).
- **Human-voice, no-dash writing rules baked into the prompts.** The user flagged that AI-sounding cover letters are a dealbreaker and called the em dash "a dead giveaway." The prompts enforce a plain human voice, a subtle non-cheesy hook, a banned list of AI-tell phrases, and zero dashes or hyphens (ranges written as "2021 to 2023").
- **Job hand-off between pages uses `st.session_state`, not a query param.** A `?job_id=` set immediately before `st.switch_page()` can be dropped by Streamlit, which stuck the Tailor page on the first job tailored. `session_state` is reliable across page switches.

---

## 3. What Has Been Built (as of July 1, 2026)

### Phase 1 Core Features (Complete)

- **Scraping Pipeline**
  - JobSpy integration for major job boards
  - Crawl4AI integration for company career pages (with polite delays, backoff, per-company isolation)
  - LLM-powered structured extraction + scoring using Claude
  - Two-pass deduplication
  - Job freshness / auto-expiry logic

- **User Interface (Streamlit)**
  - Home page with live metrics
  - Browse Jobs page with powerful filters (salary, employment type, keywords, source, date, etc.)
  - Job cards with relevance scoring and skill flags
  - Saved Jobs quick list
  - Applications Kanban board (Saved → Applied → Phone Screen → Interview → Offer)
  - Settings page with scrape run history and config viewing

- **Automation & Reliability**
  - Scheduled scraping via systemd + `cloudflared` service
  - Manual scrape trigger from Settings page (file-based trigger)
  - Full logging and error handling
  - `scrape_runs` table for observability

- **Deployment**
  - Docker Compose setup (app + scraper services)
  - Cloudflare Tunnel configured for `rocket.lionheartsearch.com`
  - Named tunnel "remote-rocket" running as systemd service

### Phase 2 Features (Complete)

- **My Resume page**: upload a PDF or DOCX (or paste text), one time. A Haiku pass structures it into sections; raw text and structured JSON are both stored. Shows a read-only preview with a Replace / Re-upload button. No manual editing.
- **Tailor page**: one tap from any job (Browse Jobs or the Applications board). Sonnet writes a tailored resume and a matching cover letter using only facts from the master resume. Regenerate with an optional note (for example "lean into ROAS and Performance Max"). Every generation is a new version with history.
- **Output**: editable markdown in the UI plus ATS-friendly `.docx` downloads for both documents, and copy-to-clipboard. Mobile-first single-column layout.
- **Writing quality**: prompts enforce a human voice, a subtle hook, no AI-tell phrases, and no dashes or hyphens.
- **Data model**: `master_resume` (single row) + `tailored_documents` (versioned per job). Prompts in `prompts/tailoring_prompts.yml`. New app deps: `anthropic`, `pypdf`, `python-docx`.

---

## 4. Current Deployment Status (as of July 1, 2026)

**VPS**
- Provider: DigitalOcean (San Francisco)
- Size: $14/month plan (1 vCPU, 2 GB RAM)
- User: `deploy` (non-root)
- Docker Compose running both services

**Cloudflare Tunnel**
- Tunnel name: `remote-rocket`
- Service running and healthy (`active (running)`)
- Route configured: `rocket.lionheartsearch.com` → `http://localhost:8501`
- DNS propagated (CNAME visible on whatsmydns.net)

**Status: Live**
- `https://rocket.lionheartsearch.com` loads and serves the app through the tunnel. The earlier timeout resolved on its own (Cloudflare edge route activation delay).
- Both containers run with `restart: unless-stopped`, so the app stays up independently of any SSH session.

**Deploy workflow**
- Push code to `main` on GitHub (`Leewho-notdev/remote-rocket`), then on the VPS `cd ~/remote-rocket && git pull`.
- Reload rules by change type: prompt YAML needs only `git pull` (mounted, read fresh); Python code needs `git pull` + `docker compose restart app`; dependency changes need `docker compose up -d --build` (use `docker compose build --no-cache app` if the pip layer caches when it should not).

---

## 5. Important File Locations (on VPS)

| Path                              | Purpose |
|-----------------------------------|--------|
| `~/remote-rocket/`                | Project root |
| `~/remote-rocket/.env`            | Environment variables (Claude key, intervals, etc.) |
| `~/remote-rocket/docker-compose.yml` | Docker services definition |
| `config/keywords.yml`             | Search terms and exclusions |
| `config/companies.yml`            | Target company career pages + high_priority flag |
| `db/jobs.db`                      | SQLite database |
| `/etc/systemd/system/cloudflared.service` | Tunnel systemd service |

---

## 6. Key Commands

**Check tunnel status**
```bash
sudo systemctl status cloudflared
```

**View tunnel logs**
```bash
sudo journalctl -u cloudflared -f
```

**Restart tunnel**
```bash
sudo systemctl restart cloudflared
```

**Check app logs**
```bash
cd ~/remote-rocket
docker compose logs --tail=50 app
```

**Manual scrape trigger** (from Settings page in UI or via file)

---

## 7. Next Steps / Open Items

1. Validate Phase 2 end-to-end in production: upload the master resume, tailor a job, download the `.docx` files, confirm the cover-letter voice reads human.
2. **Phase 3 ideas**: batch tailoring across a shortlist, a per-application interview-prep brief, OCR fallback for image-only PDF resumes, optional structured resume editing for power users.
3. Optional quality-of-life: add `ServerAliveInterval 60` to the Mac's `~/.ssh/config` to stop the frequent SSH session drops.

---

## 8. Notes for Future Sessions

- The user has zero Python experience → always prioritize Docker Compose + clear commands.
- User is nomadic → observability and remote management are important.
- Domain is on Squarespace; Cloudflare is only used for the subdomain + tunnel.
- Keep configuration in YAML files wherever possible.
- The architecture was intentionally kept simple to remain maintainable by a non-developer using AI assistance.
- **Writing rule**: any generated prose (cover letters most of all) must read human, avoid AI-tell phrases, and use no dashes or hyphens. The em dash is "a dead giveaway."
- **Guiding the user through ops**: give commands one at a time, tell him to type rather than paste short commands (his terminal injects a `[200~` bracketed-paste prefix that corrupts the first line), and always say whether a command runs on the VPS or his Mac. SSH sessions drop often; reconnecting is safe since containers keep running.
- **Two memory layers**: this file is the shared, human- and Grok-readable summary. Claude Code also keeps its own private operational memory (outside the repo) that auto-loads each session. The deep technical design and data model live in `ARCHITECTURE.md`.

---

**Last Updated:** July 1, 2026 (Phase 2 shipped)  
**Maintained by:** Grok (architecture + deploy) and Claude (code); user leewho