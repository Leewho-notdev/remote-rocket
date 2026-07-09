"""
pages/1_Browse_Jobs.py
The main job board — filters in the sidebar, job cards in the main panel.
Hidden Gem career page jobs are surfaced in a dedicated section at the top.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from components.db import get_jobs, get_job_counts, db_exists
from components.filters import render_filters
from components.job_card import render_job_card
from components.theme import apply_theme

st.set_page_config(
    page_title="Browse Jobs — Remote Rocket",
    page_icon="🚀",
    layout="wide",
)
apply_theme()

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
selected_sources = filters["sources"] or ["career_page"]
both_on = "career_page" in selected_sources and "jobspy" in selected_sources
page_title = "📋 Hidden Gems & Job Boards" if both_on else ("💎 Hidden Gems" if "career_page" in selected_sources else "📌 Job Boards")
st.title(page_title)

# Shared filter kwargs (everything except source)
base_filters = dict(
    min_salary        = filters["min_salary"],
    employment_types  = filters["employment_types"],
    days_posted       = filters["days_posted"],
    min_score         = filters["min_score"],
    keywords          = filters["keywords"],
    negative_keywords = filters["negative_keywords"],
    has_google_ads    = filters["has_google_ads"],
    has_msft_ads      = filters["has_msft_ads"],
    has_gtm           = filters["has_gtm"],
    has_gmc           = filters["has_gmc"],
    include_actioned  = filters["include_actioned"],
    include_excluded  = filters["include_excluded"],
    include_inactive  = filters["include_inactive"],
    sort_by           = filters["sort_by"],
)

gems       = get_jobs(sources=["career_page"], limit=200, **base_filters) if "career_page" in selected_sources else []
board_jobs = get_jobs(sources=["jobspy"],       limit=200, **base_filters) if "jobspy"       in selected_sources else []
total_showing = len(gems) + len(board_jobs)

st.caption(f"Showing **{total_showing}** jobs")
st.divider()

# ── Hidden Gems section ───────────────────────────────────────────────────────
if "career_page" in selected_sources:
    st.markdown("## 💎 Hidden Gems")
    st.markdown(
        "**Jobs sourced directly from company career pages. "
        "Not posted on LinkedIn or Indeed. These are the unique finds.**"
    )
    if gems:
        for i, job in enumerate(gems):
            render_job_card(job, index=i)
    else:
        st.info("No career page jobs match your current filters.", icon="💎")
    st.divider()

# ── Job boards section ────────────────────────────────────────────────────────
if "jobspy" in selected_sources:
    st.markdown("## 📌 Job Boards")
    st.caption("Jobs from LinkedIn, Indeed, and other job boards.")
    if board_jobs:
        for i, job in enumerate(board_jobs):
            render_job_card(job, index=i)
    else:
        st.info("No job board listings match your current filters.", icon="📌")

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption("Adjust filters or go to **Settings** to trigger a new scrape.")
