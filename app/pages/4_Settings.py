"""
pages/4_Settings.py
Scraper status dashboard and configuration viewer.
Full implementation in Step 6 (scrape run history, manual trigger).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from components.db import get_recent_scrape_runs, get_last_successful_run

st.set_page_config(page_title="Settings — Remote Rocket", page_icon="⚙️", layout="wide")
st.title("⚙️ Settings")

st.divider()

# ── Scraper status ────────────────────────────────────────────────────────────
st.subheader("Scraper Status")

last_run  = get_last_successful_run()
recent    = get_recent_scrape_runs(limit=5)

if last_run:
    status_col1, status_col2, status_col3 = st.columns(3)
    with status_col1:
        st.metric("Last Successful Run", (last_run.get("finished_at") or "")[:16].replace("T", " "))
    with status_col2:
        st.metric("Jobs Found (last run)", last_run.get("jobs_new", 0))
    with status_col3:
        duration = last_run.get("duration_secs")
        st.metric("Duration", f"{duration}s" if duration else "—")
else:
    st.info("No successful scrape runs recorded yet. The scraper may still be starting up.", icon="⏳")

# Recent run history table
if recent:
    st.subheader("Recent Runs")
    for run in recent:
        status    = run.get("status", "unknown")
        icon      = {"success": "✅", "partial": "⚠️", "failed": "❌", "running": "⏳"}.get(status, "❔")
        started   = (run.get("started_at") or "")[:16].replace("T", " ")
        new       = run.get("jobs_new", 0)
        errors    = run.get("errors", 0)
        duration  = run.get("duration_secs")

        with st.container(border=True):
            rc1, rc2, rc3, rc4 = st.columns(4)
            with rc1:
                st.write(f"{icon} **{status.title()}**")
                st.caption(started)
            with rc2:
                st.metric("New jobs", new)
            with rc3:
                st.metric("Errors", errors)
            with rc4:
                st.metric("Duration", f"{duration}s" if duration else "—")

            if run.get("error_details"):
                with st.expander("Error details"):
                    for err in run["error_details"]:
                        st.error(err)

st.divider()
st.info(
    "Manual scrape trigger and configuration editor coming in Step 6.",
    icon="🔧",
)
