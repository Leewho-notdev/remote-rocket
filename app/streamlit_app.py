"""
streamlit_app.py
Remote Rocket — main entry point.

Streamlit's multi-page app structure picks up pages from the pages/ directory
automatically. This file sets global page config and shows the home screen.

Run via Docker:  docker compose up
Run locally:     streamlit run streamlit_app.py
"""

import streamlit as st
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from components.db import get_job_counts, get_last_successful_run

st.set_page_config(
    page_title="Remote Rocket",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🚀 Remote Rocket")
st.caption("Your personal feed for remote performance marketing jobs.")

st.divider()

# ── Quick stats ───────────────────────────────────────────────────────────────
counts      = get_job_counts()
last_run    = get_last_successful_run()

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Active Jobs", counts.get("active", 0))
with col2:
    st.metric("💎 Career Page Finds", counts.get("hidden_gems", 0))
with col3:
    st.metric("Google Ads Roles", counts.get("google_ads_roles", 0))
with col4:
    last_run_label = "Never"
    if last_run and last_run.get("finished_at"):
        # Show just the date + time, drop microseconds
        last_run_label = last_run["finished_at"][:16].replace("T", " ")
    st.metric("Last Scrape", last_run_label)

st.divider()

# ── Navigation cards ──────────────────────────────────────────────────────────
st.subheader("Navigate")

nav1, nav2, nav3 = st.columns(3)

with nav1:
    st.info("**📋 Browse Jobs**\nFilter and search all active remote jobs.", icon="📋")
    if st.button("Go to Browse Jobs", use_container_width=True):
        st.switch_page("pages/1_Browse_Jobs.py")

with nav2:
    st.info("**📁 Applications**\nTrack your application pipeline.", icon="📁")
    if st.button("Go to Applications", use_container_width=True):
        st.switch_page("pages/3_Applications.py")

with nav3:
    st.info("**⚙️ Settings**\nView scraper status and configure the tool.", icon="⚙️")
    if st.button("Go to Settings", use_container_width=True):
        st.switch_page("pages/4_Settings.py")

st.divider()
st.caption(
    "Jobs are scraped automatically every 12 hours. "
    "Go to **Settings** to trigger a manual run or adjust configuration."
)
