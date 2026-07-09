"""
app/components/filters.py
Sidebar filter controls for the Browse Jobs page.

Returns a dict of filter values that can be passed directly to db.get_jobs().
Keeping all filter logic in one place makes it easy to add new filters later.
"""

import os
import streamlit as st
from components.db import get_saved_neg_keywords, save_neg_keywords

# Default minimum salary from environment (matches .env SALARY_MIN_DEFAULT)
DEFAULT_SALARY_MIN = int(os.getenv("SALARY_MIN_DEFAULT", 100_000))


def render_filters() -> dict:
    """
    Render all sidebar filters and return the current values as a dict.
    Call this at the top of any page that needs job filtering.

    Returns a dict with keys matching db.get_jobs() parameters:
        min_salary, employment_types, sources, days_posted,
        min_score, keywords, negative_keywords, has_google_ads, has_msft_ads,
        has_gtm, has_gmc, include_excluded, include_inactive, sort_by
    """
    st.sidebar.header("🔍 Filters")

    # ── Salary ────────────────────────────────────────────────────────────────
    st.sidebar.subheader("Salary")
    min_salary = st.sidebar.number_input(
        "Minimum salary (USD / year)",
        min_value=0,
        max_value=500_000,
        value=DEFAULT_SALARY_MIN,
        step=10_000,
        format="%d",
        help="Shows jobs where the minimum salary meets this threshold, "
             "plus all jobs where salary is not listed.",
    )

    # ── Employment type ───────────────────────────────────────────────────────
    st.sidebar.subheader("Employment Type")
    col_ft, col_ct, col_pt = st.sidebar.columns(3)
    show_fulltime = col_ft.toggle("Full-time", value=True)
    show_contract = col_ct.toggle("Contract",  value=True)
    show_parttime = col_pt.toggle("Part-time", value=False)
    employment_types = (
        (["full_time"] if show_fulltime else [])
        + (["contract"] if show_contract else [])
        + (["part_time"] if show_parttime else [])
    ) or None

    # ── Source ────────────────────────────────────────────────────────────────
    st.sidebar.subheader("Source")
    col_jp, col_cp = st.sidebar.columns(2)
    show_jobspy     = col_jp.toggle("Job boards",     value=False)
    show_careerpages = col_cp.toggle("💎 Career pages", value=True)
    sources = (
        (["jobspy"] if show_jobspy else [])
        + (["career_page"] if show_careerpages else [])
    ) or None

    # ── Date posted ───────────────────────────────────────────────────────────
    st.sidebar.subheader("Date Posted")
    days_map = {
        "Last 24 hours": 1,
        "Last 3 days":   3,
        "Last 7 days":   7,
        "Last 14 days":  14,
        "Last 30 days":  30,
        "All time":      None,
    }
    days_label = st.sidebar.selectbox(
        "Posted within",
        options=list(days_map.keys()),
        index=2,   # Default: Last 7 days
    )
    days_posted = days_map[days_label]

    # ── Skills ────────────────────────────────────────────────────────────────
    st.sidebar.subheader("Required Skills")
    has_google_ads = st.sidebar.checkbox("Google Ads")
    has_msft_ads   = st.sidebar.checkbox("Microsoft Ads")
    has_gtm        = st.sidebar.checkbox("Google Tag Manager")
    has_gmc        = st.sidebar.checkbox("Google Merchant Center")

    # ── Keyword search ────────────────────────────────────────────────────────
    st.sidebar.subheader("Keyword Search")
    keywords = st.sidebar.text_input(
        "Search in title or company",
        placeholder="e.g. 'performance' or 'Klaviyo'",
    )

    # ── Negative keywords ─────────────────────────────────────────────────────
    st.sidebar.subheader("Negative Keywords")
    if "neg_keywords" not in st.session_state:
        st.session_state.neg_keywords = get_saved_neg_keywords()

    st.sidebar.markdown(
        "<style>#neg_kw_form [data-testid='stFormSubmitButton']{display:none}</style>",
        unsafe_allow_html=True,
    )
    with st.sidebar.form("neg_kw_form", clear_on_submit=True, border=False):
        new_kw = st.text_input(
            "Add keyword to exclude",
            placeholder="e.g. tiktok, meta",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Add", disabled=False)
        if submitted and new_kw.strip():
            kw = new_kw.strip().lower()
            if kw not in st.session_state.neg_keywords:
                st.session_state.neg_keywords.append(kw)

    if st.session_state.neg_keywords:
        ms_key = "neg_kw_ms_" + "_".join(sorted(st.session_state.neg_keywords))
        negative_keywords = st.sidebar.multiselect(
            "Active — click × to remove",
            options=st.session_state.neg_keywords,
            default=st.session_state.neg_keywords,
            key=ms_key,
            label_visibility="visible",
        )
        st.session_state.neg_keywords = list(negative_keywords)
    else:
        negative_keywords = []

    col1, col2 = st.sidebar.columns(2)
    if col1.button("💾 Save", key="save_neg_kw", use_container_width=True):
        save_neg_keywords(st.session_state.neg_keywords)
        st.sidebar.success("Saved!")
    if col2.button("Clear", key="clear_neg_kw", use_container_width=True):
        st.session_state.neg_keywords = []
        save_neg_keywords([])
        st.rerun()

    # ── Relevance score ───────────────────────────────────────────────────────
    st.sidebar.subheader("Relevance Score")
    min_score = st.sidebar.slider(
        "Minimum score (1–10)",
        min_value=1,
        max_value=10,
        value=7,
        help="Relevance scores are assigned by Claude in Step 5. "
             "All jobs score 0 until extraction runs.",
    )

    # ── Sort ──────────────────────────────────────────────────────────────────
    st.sidebar.subheader("Sort By")
    sort_map = {
        "Relevance score":  "relevance_score",
        "Date posted":      "date_posted",
        "Salary (high→low)": "salary_min",
        "Company (A–Z)":    "company",
        "Date scraped":     "date_scraped",
    }
    sort_label = st.sidebar.selectbox("Order results by", options=list(sort_map.keys()))
    sort_by    = sort_map[sort_label]

    # ── Advanced toggles ──────────────────────────────────────────────────────
    with st.sidebar.expander("Advanced"):
        include_actioned = st.checkbox(
            "Show saved / applied jobs",
            value=False,
            help="Show jobs you've already saved or marked as applied.",
        )
        include_excluded = st.checkbox(
            "Show excluded jobs",
            value=False,
            help="Show jobs filtered out by keyword or LLM rules.",
        )
        include_inactive = st.checkbox(
            "Show expired / inactive jobs",
            value=False,
            help=f"Show jobs not seen in recent scrapes (marked inactive after ~45 days).",
        )

    return {
        "min_salary":       min_salary,
        "employment_types": employment_types,
        "sources":          sources,
        "days_posted":      days_posted,
        "min_score":        min_score if min_score > 1 else 0,
        "keywords":         keywords,
        "has_google_ads":   has_google_ads,
        "has_msft_ads":     has_msft_ads,
        "has_gtm":          has_gtm,
        "has_gmc":          has_gmc,
        "include_actioned":   include_actioned,
        "include_excluded":   include_excluded,
        "include_inactive":   include_inactive,
        "sort_by":            sort_by,
        "negative_keywords":  negative_keywords,
    }
