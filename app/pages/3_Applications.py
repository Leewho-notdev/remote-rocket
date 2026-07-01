"""
pages/3_Applications.py
Kanban-style application pipeline tracker.

Columns: Saved → Applied → Phone Screen → Interview → Offer
Rejected and Withdrawn are shown in a collapsed section below.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date
import streamlit as st
from components.db import get_applications, upsert_application, update_application_field
from components.resume_store import jobs_with_tailoring

st.set_page_config(
    page_title="Applications — Remote Rocket",
    page_icon="📁",
    layout="wide",
)
st.title("📁 Applications Pipeline")
st.caption("Track every application from saved → offer.")

# ── Pipeline definition ───────────────────────────────────────────────────────
# Active stages shown as Kanban columns
ACTIVE_PIPELINE = [
    ("saved",        "🔖 Saved"),
    ("applied",      "✅ Applied"),
    ("phone_screen", "📞 Phone Screen"),
    ("interview",    "🎤 Interview"),
    ("offer",        "🎉 Offer"),
]

# Closed stages shown in a collapsed section
CLOSED_PIPELINE = [
    ("rejected",  "❌ Rejected"),
    ("withdrawn", "↩️ Withdrawn"),
]

ALL_STATUSES = ACTIVE_PIPELINE + CLOSED_PIPELINE
STATUS_LABELS = {k: v for k, v in ALL_STATUSES}
STATUS_KEYS   = [k for k, _ in ALL_STATUSES]


# ── Data ──────────────────────────────────────────────────────────────────────

def _load():
    """Fetch all applications from the DB and group by status."""
    apps = get_applications()
    grouped = {k: [] for k in STATUS_KEYS}
    for app in apps:
        s = app.get("status", "saved")
        if s in grouped:
            grouped[s].append(app)
    return grouped, len(apps)


grouped, total = _load()

# ── Summary metrics ───────────────────────────────────────────────────────────
if total == 0:
    st.info(
        "No applications tracked yet. "
        "Go to **Browse Jobs**, open any job, and click **Save** or **Mark Applied**.",
        icon="📁",
    )
    st.stop()

tailored_ids = jobs_with_tailoring()

metric_cols = st.columns(len(ALL_STATUSES))
for col, (status_key, label) in zip(metric_cols, ALL_STATUSES):
    with col:
        st.metric(label, len(grouped[status_key]))

st.divider()


# ── Card renderer ─────────────────────────────────────────────────────────────

def _salary(app: dict) -> str:
    lo, hi = app.get("salary_min"), app.get("salary_max")
    if lo and hi:
        return f"${lo:,}–${hi:,}"
    if lo:
        return f"${lo:,}+"
    return app.get("salary_raw") or "—"


def _score_badge(score) -> str:
    if score is None:
        return "⬜"
    score = int(score)
    if score >= 8:
        return f"🟢 {score}"
    if score >= 5:
        return f"🟡 {score}"
    return f"🔴 {score}"


def render_kanban_card(app: dict, col_key: str, tailored_ids: set) -> None:
    """
    Render one application card.  col_key is used to build unique widget keys.
    `tailored_ids` is the set of job_ids that already have a tailored version.
    All mutations call st.rerun() so the board refreshes immediately.
    """
    app_id  = app["id"]
    job_id  = app["job_id"]
    title   = app.get("title", "Untitled")
    company = app.get("company", "—")
    url     = app.get("url", "")
    key     = f"{col_key}_{app_id}"

    with st.container(border=True):
        # Title + score
        h_col, s_col = st.columns([4, 1])
        with h_col:
            if url:
                st.markdown(f"**[{title}]({url})**")
            else:
                st.markdown(f"**{title}**")
            st.caption(company)
        with s_col:
            st.markdown(_score_badge(app.get("relevance_score")))

        # Salary
        salary_str = _salary(app)
        if salary_str and salary_str != "—":
            st.caption(f"💰 {salary_str}")

        # ── Status selector ───────────────────────────────────────────────────
        current_idx = STATUS_KEYS.index(app.get("status", "saved"))
        new_status = st.selectbox(
            "Move to",
            options=STATUS_KEYS,
            format_func=lambda k: STATUS_LABELS[k],
            index=current_idx,
            key=f"status_{key}",
            label_visibility="collapsed",
        )
        if new_status != app.get("status"):
            existing_notes = app.get("notes") or ""
            upsert_application(job_id, new_status, existing_notes)
            st.rerun()

        # ── Resume tailoring ──────────────────────────────────────────────────
        tailor_label = "✨ Tailored resume" if job_id in tailored_ids else "✨ Tailor resume"
        if st.button(tailor_label, key=f"tailor_{key}", use_container_width=True):
            st.query_params["job_id"] = str(job_id)
            st.switch_page("pages/6_Tailor.py")

        # ── Notes ─────────────────────────────────────────────────────────────
        with st.expander("Notes & details"):
            notes_val = st.text_area(
                "Notes",
                value=app.get("notes") or "",
                height=80,
                key=f"notes_{key}",
                placeholder="Interview prep, impressions, recruiter name…",
                label_visibility="collapsed",
            )
            save_col, date_col = st.columns(2)
            with save_col:
                if st.button("Save notes", key=f"save_notes_{key}", use_container_width=True):
                    update_application_field(app_id, "notes", notes_val)
                    st.toast("Notes saved.")

            with date_col:
                existing_date = app.get("follow_up_date")
                default_date  = None
                if existing_date:
                    try:
                        default_date = date.fromisoformat(existing_date[:10])
                    except (ValueError, TypeError):
                        pass
                follow_up = st.date_input(
                    "Follow-up date",
                    value=default_date,
                    key=f"followup_{key}",
                    label_visibility="collapsed",
                    format="YYYY-MM-DD",
                )
                if follow_up and str(follow_up) != (existing_date or "")[:10]:
                    update_application_field(app_id, "follow_up_date", str(follow_up))
                    st.toast("Follow-up date saved.")

            # Contact info
            contact_name  = st.text_input(
                "Recruiter / contact name",
                value=app.get("contact_name") or "",
                key=f"contact_name_{key}",
            )
            contact_email = st.text_input(
                "Contact email",
                value=app.get("contact_email") or "",
                key=f"contact_email_{key}",
            )
            if st.button("Save contact", key=f"save_contact_{key}"):
                update_application_field(app_id, "contact_name",  contact_name)
                update_application_field(app_id, "contact_email", contact_email)
                st.toast("Contact saved.")


# ── Active pipeline Kanban ────────────────────────────────────────────────────
kanban_cols = st.columns(len(ACTIVE_PIPELINE))

for col_widget, (status_key, label) in zip(kanban_cols, ACTIVE_PIPELINE):
    with col_widget:
        apps_in_col = grouped[status_key]
        st.markdown(f"**{label}** ({len(apps_in_col)})")
        st.divider()
        if apps_in_col:
            for app in apps_in_col:
                render_kanban_card(app, col_key=status_key, tailored_ids=tailored_ids)
        else:
            st.caption("Empty")


# ── Closed applications ───────────────────────────────────────────────────────
closed_total = sum(len(grouped[k]) for k, _ in CLOSED_PIPELINE)
if closed_total > 0:
    with st.expander(f"Closed applications — {closed_total} total (rejected / withdrawn)"):
        closed_cols = st.columns(len(CLOSED_PIPELINE))
        for col_widget, (status_key, label) in zip(closed_cols, CLOSED_PIPELINE):
            with col_widget:
                apps_in_col = grouped[status_key]
                st.markdown(f"**{label}** ({len(apps_in_col)})")
                st.divider()
                for app in apps_in_col:
                    render_kanban_card(app, col_key=status_key, tailored_ids=tailored_ids)
