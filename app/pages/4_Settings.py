"""
pages/4_Settings.py
Scraper status dashboard, manual trigger, and config viewer.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import time
import streamlit as st
import yaml
from datetime import datetime, timedelta, timezone
from components.db import (
    get_recent_scrape_runs,
    get_last_successful_run,
    trigger_scrape,
    delete_all_jobs,
)
from components.theme import apply_theme

st.set_page_config(page_title="Settings — Remote Rocket", page_icon="⚙️", layout="wide")
apply_theme()
st.title("⚙️ Settings")

# ── Manual scrape trigger ─────────────────────────────────────────────────────
st.subheader("Manual Trigger")

col_btn, col_info = st.columns([1, 3])
with col_btn:
    if st.button("▶ Run Scrape Now", type="primary", use_container_width=True):
        ok = trigger_scrape()
        if ok:
            st.success("Trigger sent — scrape will start within ~60 seconds.")
        else:
            st.error(
                "Could not write trigger file. "
                "Check that the /app/db volume is mounted and writable."
            )

with col_info:
    SCRAPE_INTERVAL_HOURS = int(os.getenv("SCRAPE_INTERVAL_HOURS", 12))
    last_ok = get_last_successful_run()
    if last_ok and last_ok.get("finished_at"):
        try:
            last_dt  = datetime.fromisoformat(last_ok["finished_at"])
            next_dt  = last_dt + timedelta(hours=SCRAPE_INTERVAL_HOURS)
            now_utc  = datetime.now(timezone.utc).replace(tzinfo=None)
            mins_left = int((next_dt - now_utc).total_seconds() / 60)
            if mins_left > 0:
                hrs, mins = divmod(mins_left, 60)
                next_str  = f"{hrs}h {mins}m" if hrs else f"{mins}m"
                st.info(f"Next scheduled scrape in approximately **{next_str}** (every {SCRAPE_INTERVAL_HOURS}h).")
            else:
                st.info("Next scheduled scrape is imminent or overdue.")
        except (ValueError, TypeError):
            st.info(f"Scrape interval: every {SCRAPE_INTERVAL_HOURS} hour(s).")
    else:
        st.info(f"Scrape interval: every {SCRAPE_INTERVAL_HOURS} hour(s).")

st.divider()

# ── Danger zone ───────────────────────────────────────────────────────────────
with st.expander("⚠️ Danger Zone"):
    st.write("**Delete all jobs** — permanently removes every job and application from the database. Use this to start fresh before a new scrape.")
    if st.button("🗑 Delete All Jobs", type="secondary"):
        st.session_state["confirm_delete_all"] = True

    if st.session_state.get("confirm_delete_all"):
        st.warning("This will permanently delete every job and application record. There is no undo.")
        da_col1, da_col2 = st.columns(2)
        with da_col1:
            if st.button("Yes, delete everything", type="primary"):
                count = delete_all_jobs()
                st.session_state["confirm_delete_all"] = False
                st.success(f"Deleted {count} jobs and all associated applications.")
                st.rerun()
        with da_col2:
            if st.button("Cancel"):
                st.session_state["confirm_delete_all"] = False
                st.rerun()

st.divider()

# ── Running state banner + auto-refresh ──────────────────────────────────────
recent_check = get_recent_scrape_runs(limit=1)
is_running = recent_check and recent_check[0].get("status") == "running"

if is_running:
    st.warning("⏳ Scrape in progress — page refreshes every 5 seconds.", icon="🔄")
    st.info(
        "**Why does this take a while?**\n\n"
        "- Job boards (LinkedIn, Indeed, Google Jobs, Glassdoor, ZipRecruiter) are searched "
        "across 21 search terms with a 5-second pause between each to avoid rate limits — "
        "that's ~2 minutes of waiting before results even come back.\n"
        "- Company career pages (13 sites) are crawled individually.\n"
        "- Every new job is then sent to Claude for relevance scoring, which adds ~1–2 seconds per job.\n\n"
        "**Expect 15–25 minutes for a full run.** Subsequent runs are faster — most jobs are "
        "already in the database and get skipped as duplicates early in the pipeline."
    )
    time.sleep(5)
    st.rerun()

# ── Scraper status overview ───────────────────────────────────────────────────
st.subheader("Scraper Status")

last_run = get_last_successful_run()
if last_run:
    finished_raw = last_run.get("finished_at") or ""
    try:
        finished_dt  = datetime.fromisoformat(finished_raw)
        finished_str = finished_dt.strftime("%-d %b %Y, %-I:%M %p UTC")
    except (ValueError, TypeError):
        finished_str = finished_raw[:16].replace("T", " ") or "—"

    st.caption(f"Last successful run: **{finished_str}**")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Jobs Fetched", last_run.get("jobs_fetched", 0))
    with c2:
        st.metric("New Jobs", last_run.get("jobs_new", 0))
    with c3:
        st.metric("Scored", last_run.get("jobs_scored", 0))
    with c4:
        duration = last_run.get("duration_secs")
        st.metric("Duration", f"{duration}s" if duration else "—")
else:
    st.info("No successful scrape runs yet. The scraper may still be starting up.", icon="⏳")

st.divider()

# ── Recent run history ────────────────────────────────────────────────────────
st.subheader("Recent Runs")

recent = get_recent_scrape_runs(limit=10)

STATUS_ICON = {"success": "✅", "partial": "⚠️", "failed": "❌", "running": "⏳"}

if recent:
    for run in recent:
        status   = run.get("status", "unknown")
        icon     = STATUS_ICON.get(status, "❔")
        started  = (run.get("started_at") or "")[:16].replace("T", " ")
        duration = run.get("duration_secs")

        with st.container(border=True):
            rc1, rc2, rc3, rc4, rc5, rc6 = st.columns(6)
            with rc1:
                st.write(f"{icon} **{status.title()}**")
                st.caption(started)
            with rc2:
                st.metric("Fetched", run.get("jobs_fetched", 0))
            with rc3:
                st.metric("New", run.get("jobs_new", 0))
            with rc4:
                st.metric("Scored", run.get("jobs_scored", 0))
            with rc5:
                st.metric("Excluded", run.get("jobs_excluded", 0))
            with rc6:
                err_count = run.get("errors", 0)
                st.metric("Errors", err_count)
                if duration:
                    st.caption(f"{duration}s")

            if run.get("error_details"):
                with st.expander(f"Error details ({len(run['error_details'])} issue(s))"):
                    for err in run["error_details"]:
                        st.error(err)
else:
    st.info("No scrape runs recorded yet.")

st.divider()

# ── Config viewer ─────────────────────────────────────────────────────────────
st.subheader("Configuration")

CONFIG_DIR = os.getenv("CONFIG_DIR", "/app/config")
kw_path  = os.path.join(CONFIG_DIR, "keywords.yml")
co_path  = os.path.join(CONFIG_DIR, "companies.yml")

# Fallback for local dev outside Docker
if not os.path.exists(kw_path):
    kw_path = os.path.join(os.path.dirname(__file__), "..", "..", "config", "keywords.yml")
if not os.path.exists(co_path):
    co_path = os.path.join(os.path.dirname(__file__), "..", "..", "config", "companies.yml")

tab_kw, tab_co, tab_env, tab_log = st.tabs(["Keywords", "Companies", "Environment", "Scraper Log"])

with tab_kw:
    if os.path.exists(kw_path):
        with open(kw_path) as f:
            kw = yaml.safe_load(f)

        search_terms = kw.get("search_terms", [])
        st.write(f"**{len(search_terms)} search terms**")
        for t in search_terms:
            st.markdown(f"- `{t}`")

        st.write("**Title exclusions**")
        for t in kw.get("title_exclusions", []):
            st.markdown(f"- `{t}`")
    else:
        st.warning(f"keywords.yml not found at {kw_path}")

with tab_co:
    if os.path.exists(co_path):
        with open(co_path) as f:
            co = yaml.safe_load(f)

        companies = co.get("companies", [])
        high   = [c for c in companies if c.get("high_priority")]
        std    = [c for c in companies if not c.get("high_priority")]

        st.write(f"**{len(companies)} companies total** — {len(high)} high priority, {len(std)} standard")

        ATS_LABEL = {"greenhouse": "🌱 Greenhouse", "lever": "⚙️ Lever", "ashby": "🔷 Ashby", "crawl4ai": "🕷 Crawl4AI"}

        for section_label, group in [("High priority (scraped every run)", high), ("Standard (scraped every other run)", std)]:
            st.write(f"**{section_label}**")
            for c in group:
                ats  = (c.get("ats") or "crawl4ai").lower()
                slug = c.get("ats_slug") or ""
                ats_badge = ATS_LABEL.get(ats, ats)
                slug_str  = f" `{slug}`" if slug else ""
                st.markdown(f"- [{c['name']}]({c.get('careers_url', '')}) — {ats_badge}{slug_str}")
    else:
        st.warning(f"companies.yml not found at {co_path}")

with tab_env:
    env_vars = {
        "SCRAPE_INTERVAL_HOURS": os.getenv("SCRAPE_INTERVAL_HOURS", "12"),
        "JOB_EXPIRY_DAYS":       os.getenv("JOB_EXPIRY_DAYS", "45"),
        "SALARY_MIN_DEFAULT":    os.getenv("SALARY_MIN_DEFAULT", "100000"),
        "CLAUDE_MODEL":          os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
        "LOG_LEVEL":             os.getenv("LOG_LEVEL", "INFO"),
        "DB_PATH":               os.getenv("DB_PATH", "/app/db/jobs.db"),
        "ANTHROPIC_API_KEY":     "sk-ant-***" if os.getenv("ANTHROPIC_API_KEY") else "NOT SET ⚠️",
    }
    for k, v in env_vars.items():
        c1, c2 = st.columns([2, 3])
        with c1:
            st.code(k)
        with c2:
            st.write(v)

with tab_log:
    LOG_PATH = os.getenv("LOG_PATH", "/app/logs/scraper.log")

    log_col1, log_col2 = st.columns([3, 1])
    with log_col1:
        st.write(f"Reading from `{LOG_PATH}`")
    with log_col2:
        log_lines = st.selectbox("Lines to show", [100, 250, 500, 1000], index=0, label_visibility="collapsed")

    if not os.path.exists(LOG_PATH):
        st.warning(
            f"Log file not found at `{LOG_PATH}`. "
            "This is normal if no scrape has run yet, or if the logs volume "
            "isn't mounted to the app container. Check docker-compose.yml.",
            icon="⚠️",
        )
    else:
        try:
            with open(LOG_PATH, "r") as f:
                all_lines = f.readlines()

            tail = all_lines[-log_lines:]
            log_text = "".join(tail)

            # Colour-coded summary strip — scan for key markers
            errors   = sum(1 for l in tail if "[ERROR]" in l)
            warnings = sum(1 for l in tail if "[WARNING]" in l)
            new_jobs = sum(1 for l in tail if "New job #" in l)
            scored   = sum(1 for l in tail if "Scored #" in l)
            ats_hits = sum(1 for l in tail if ("Greenhouse" in l or "Lever" in l) and "jobs via" in l)

            s1, s2, s3, s4 = st.columns(4)
            s1.metric("New jobs logged", new_jobs)
            s2.metric("Scored", scored)
            s3.metric("Warnings", warnings)
            s4.metric("Errors", errors)

            if errors:
                st.error(f"{errors} error(s) found — scan the log below for [ERROR] lines.", icon="❌")

            st.text_area(
                label="",
                value=log_text,
                height=500,
                disabled=True,
                label_visibility="collapsed",
            )

            st.caption(
                f"Showing last {len(tail)} of {len(all_lines)} total lines. "
                f"Full log at `{LOG_PATH}` on the server."
            )

        except Exception as e:
            st.error(f"Could not read log file: {e}")
