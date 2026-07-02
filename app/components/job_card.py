"""
app/components/job_card.py
Renders a single job as a Streamlit card with an expandable detail view.

Designed to be called in a loop from the Browse Jobs page.
All rendering logic lives here so the page file stays clean.
"""

import streamlit as st
from components.db import upsert_application


# Colour-coded relevance score indicator
def _score_badge(score) -> str:
    if score is None:
        return "⬜ Unscored"
    score = int(score)
    if score >= 8:
        return f"🟢 {score}/10"
    if score >= 5:
        return f"🟡 {score}/10"
    return f"🔴 {score}/10"


def _salary_display(job: dict) -> str:
    """Format salary range for display. Returns empty string if unknown."""
    lo = job.get("salary_min")
    hi = job.get("salary_max")
    if lo and hi:
        return f"${lo:,} – ${hi:,}"
    if lo:
        return f"${lo:,}+"
    if hi:
        return f"Up to ${hi:,}"
    return "Salary not listed"


def _employment_badge(employment_type: str) -> str:
    mapping = {
        "full_time":  "🔵 Full-time",
        "contract":   "🟠 Contract",
        "part_time":  "⚪ Part-time",
    }
    return mapping.get(employment_type or "", "❔ Unknown")


def _source_badge(job: dict) -> str:
    if job.get("is_hidden_gem"):
        return "💎 Career Page"
    source = job.get("source", "")
    if "linkedin" in source:
        return "🔗 LinkedIn"
    if "indeed" in source:
        return "🔎 Indeed"
    if "glassdoor" in source:
        return "🚪 Glassdoor"
    if "zip" in source:
        return "📦 ZipRecruiter"
    return "📋 Job Board"


def _date_display(date_str: str) -> str:
    """Convert ISO date string to a readable label."""
    if not date_str:
        return "Date unknown"
    try:
        from datetime import date, datetime
        posted = datetime.fromisoformat(date_str[:10]).date()
        delta  = (date.today() - posted).days
        if delta == 0:
            return "Today"
        if delta == 1:
            return "Yesterday"
        if delta < 7:
            return f"{delta} days ago"
        if delta < 30:
            return f"{delta // 7}w ago"
        return date_str[:10]
    except (ValueError, TypeError):
        return date_str[:10] if date_str else "Date unknown"


def _skill_chips(job: dict) -> str:
    """Build a compact skill tag string from boolean flags."""
    chips = []
    if job.get("has_google_ads"):
        chips.append("✓ Google Ads")
    if job.get("has_msft_ads"):
        chips.append("✓ Microsoft Ads")
    if job.get("has_gtm"):
        chips.append("✓ GTM")
    if job.get("has_gmc"):
        chips.append("✓ Merchant Center")
    return "  ·  ".join(chips) if chips else ""


def render_job_card(job: dict, index: int) -> None:
    """
    Render a single job card inside a Streamlit container.
    `index` is used to create unique widget keys for each card.

    The card shows a summary row, and an expander reveals full details
    plus action buttons (Save / Mark Applied / Apply link).
    """
    job_id   = job.get("id")
    title    = job.get("title", "Untitled")
    company  = job.get("company", "Unknown Company")
    app_status = job.get("application_status")

    # ── Card header row ───────────────────────────────────────────────────────
    with st.container(border=True):

        # Top line: title + company
        col_title, col_score = st.columns([5, 1])
        with col_title:
            # Show applied badge inline if tracked
            status_prefix = ""
            if app_status == "applied":
                status_prefix = "✅ "
            elif app_status == "saved":
                status_prefix = "🔖 "
            elif app_status in ("phone_screen", "interview"):
                status_prefix = "📞 "
            st.markdown(f"### {status_prefix}{title}")
            st.markdown(f"**{company}**")
        with col_score:
            st.markdown(_score_badge(job.get("relevance_score")))

        # Second line: meta tags
        meta_cols = st.columns(4)
        with meta_cols[0]:
            st.caption(_salary_display(job))
        with meta_cols[1]:
            st.caption(_employment_badge(job.get("employment_type")))
        with meta_cols[2]:
            st.caption(_source_badge(job))
        with meta_cols[3]:
            st.caption(_date_display(job.get("date_posted") or job.get("date_scraped")))

        # Skill chips (only shown when LLM has scored the job)
        chips = _skill_chips(job)
        if chips:
            st.caption(chips)

        # Excluded warning
        if job.get("is_excluded"):
            st.warning(
                f"Filtered: {job.get('exclusion_reason', 'excluded by rules')}",
                icon="⚠️",
            )

        # ── Expandable detail view ────────────────────────────────────────────
        with st.expander("View details & actions"):

            # Action buttons row
            btn_col1, btn_col2, btn_col3 = st.columns(3)

            with btn_col1:
                url = job.get("url", "")
                if url:
                    st.link_button("🔗 Apply / View Listing", url, use_container_width=True)

            with btn_col2:
                if st.button("🔖 Save", key=f"save_{index}_{job_id}", use_container_width=True):
                    upsert_application(job_id, "saved")
                    st.success("Saved!")
                    st.rerun()

            with btn_col3:
                if st.button("✅ Mark Applied", key=f"applied_{index}_{job_id}", use_container_width=True):
                    upsert_application(job_id, "applied")
                    st.success("Marked as applied!")
                    st.rerun()

            # Tailor resume + cover letter for this role (Phase 2)
            if st.button("✨ Tailor resume", key=f"tailor_{index}_{job_id}", use_container_width=True):
                st.session_state["tailor_job_id"] = job_id
                st.switch_page("pages/6_Tailor.py")

            st.divider()

            # Full job details
            detail_left, detail_right = st.columns([3, 1])

            with detail_left:
                st.subheader("Description")
                desc = job.get("description_clean") or job.get("description_raw") or ""
                if desc:
                    # Truncate very long descriptions but allow full scroll
                    st.text_area(
                        label="",
                        value=desc[:5000] + ("…" if len(desc) > 5000 else ""),
                        height=300,
                        disabled=True,
                        label_visibility="collapsed",
                    )
                else:
                    st.caption("No description available.")

            with detail_right:
                st.subheader("Details")
                st.write(f"**Company:** {company}")
                st.write(f"**Location:** {job.get('location', 'Remote')}")
                st.write(f"**Type:** {_employment_badge(job.get('employment_type'))}")
                st.write(f"**Salary:** {_salary_display(job)}")
                st.write(f"**Source:** {_source_badge(job)}")
                st.write(f"**Posted:** {_date_display(job.get('date_posted'))}")
                st.write(f"**Scraped:** {(job.get('date_scraped') or '')[:10]}")

                # Skills detected (once LLM extraction runs)
                skills = job.get("skills_detected")
                if skills and isinstance(skills, list):
                    st.subheader("Skills Detected")
                    for skill in skills:
                        st.markdown(f"- {skill}")

                # Requirements (once LLM extraction runs)
                requirements = job.get("requirements")
                if requirements and isinstance(requirements, list):
                    st.subheader("Key Requirements")
                    for req in requirements:
                        st.markdown(f"- {req}")
