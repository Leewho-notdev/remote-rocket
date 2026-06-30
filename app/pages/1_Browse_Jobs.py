"""
pages/1_Browse_Jobs.py
The main job board — filters in the sidebar, job cards in the main panel.

Filter state persists within a session via Streamlit's widget state.
Each filter change triggers a fresh database query (fast with SQLite + indexes).
"""

import sys
import os

# Ensure the app/ directory is on the path so components can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from components.db import get_jobs, get_job_counts, db_exists
from components.filters import render_filters
from components.job_card import render_job_card

st.set_page_config(
    page_title="Browse Jobs — Remote Rocket",
    page_icon="📋",
    layout="wide",
)

# ── Sidebar filters ───────────────────────────────────────────────────────────
filters = render_filters()

if not db_exists():
    st.title("📋 Browse Jobs")
    st.info(
        "The scraper is initializing. Jobs will appear here after the first scrape completes "
        "(usually 5–15 minutes). Check **Settings** for live status.",
        icon="⏳",
    )
    st.stop()

# ── Page header ───────────────────────────────────────────────────────────────
st.title("📋 Browse Jobs")

# ── Fetch jobs from DB using current filter state ─────────────────────────────
jobs = get_jobs(
    min_salary       = filters["min_salary"],
    employment_types = filters["employment_types"],
    sources          = filters["sources"],
    days_posted      = filters["days_posted"],
    min_score        = filters["min_score"],
    keywords         = filters["keywords"],
    has_google_ads   = filters["has_google_ads"],
    has_msft_ads     = filters["has_msft_ads"],
    has_gtm          = filters["has_gtm"],
    has_gmc          = filters["has_gmc"],
    include_excluded = filters["include_excluded"],
    include_inactive = filters["include_inactive"],
    sort_by          = filters["sort_by"],
    limit            = 200,
)

# ── Result count + sort label ─────────────────────────────────────────────────
counts = get_job_counts()

header_col, sort_col = st.columns([3, 1])
with header_col:
    total_active = counts.get("active", 0)
    showing      = len(jobs)
    st.caption(
        f"Showing **{showing}** jobs"
        + (f" (of {total_active} total active)" if showing < total_active else "")
    )
with sort_col:
    st.caption(f"Sorted by: **{filters['sort_by'].replace('_', ' ').title()}**")

st.divider()

# ── Empty state ───────────────────────────────────────────────────────────────
if not jobs:
    st.info(
        "No jobs match your current filters.\n\n"
        "Try broadening the salary range, selecting more employment types, "
        "or extending the date range. If the database is empty, wait for the "
        "first scrape to complete (check the Settings page for status).",
        icon="🔍",
    )
    st.stop()

# ── Job cards ─────────────────────────────────────────────────────────────────
for i, job in enumerate(jobs):
    render_job_card(job, index=i)

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    f"Showing {showing} of {total_active} active jobs. "
    "Adjust filters or go to **Settings** to trigger a new scrape."
)
