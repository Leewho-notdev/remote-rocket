"""
app/components/filters.py
Sidebar filter controls for the Browse Jobs page.

Returns a dict of filter values that can be passed directly to db.get_jobs().
Keeping all filter logic in one place makes it easy to add new filters later.
"""

import os
import streamlit as st

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
    type_options = {
        "Full-time":      "full_time",
        "Contract":       "contract",
        "Part-time":      "part_time",
    }
    selected_types = st.sidebar.multiselect(
        "Show roles of type",
        options=list(type_options.keys()),
        default=["Full-time", "Contract"],
    )
    employment_types = [type_options[t] for t in selected_types] or None

    # ── Source ────────────────────────────────────────────────────────────────
    st.sidebar.subheader("Source")
    source_options = {
        "Job boards (LinkedIn, Indeed…)": "jobspy",
        "💎 Company career pages":         "career_page",
    }
    selected_sources = st.sidebar.multiselect(
        "Show jobs from",
        options=list(source_options.keys()),
        default=list(source_options.keys()),
    )
    sources = [source_options[s] for s in selected_sources] or None

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
        st.session_state.neg_keywords = []

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
        negative_keywords = st.sidebar.multiselect(
            "Active — click × to remove",
            options=st.session_state.neg_keywords,
            default=st.session_state.neg_keywords,
            label_visibility="visible",
        )
        st.session_state.neg_keywords = negative_keywords
    else:
        negative_keywords = []

    # ── Relevance score ───────────────────────────────────────────────────────
    st.sidebar.subheader("Relevance Score")
    min_score = st.sidebar.slider(
        "Minimum score (1–10)",
        min_value=1,
        max_value=10,
        value=1,
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
        "include_excluded":   include_excluded,
        "include_inactive":   include_inactive,
        "sort_by":            sort_by,
        "negative_keywords":  negative_keywords,
    }
