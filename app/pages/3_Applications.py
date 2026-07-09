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
import json
import streamlit as st
from components.db import get_applications, upsert_application, update_application_field
from components.resume_store import get_master_resume, jobs_with_tailoring, get_followups, save_followup, followup_count_by_job
from components.resume_generator import structured_to_markdown
from components.followup_generator import (
    find_verified_email, draft_followup_email, followup_subject,
)
from components.theme import apply_theme

st.set_page_config(
    page_title="Applications — Remote Rocket",
    page_icon="🚀",
    layout="centered",
)
apply_theme()
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

tailored_ids  = jobs_with_tailoring()
all_job_ids   = [a["job_id"] for a in get_applications()]
followup_counts = followup_count_by_job(all_job_ids)

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


def render_kanban_card(app: dict, col_key: str, tailored_ids: set,
                       followup_counts: dict = None) -> None:
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
            st.session_state["tailor_job_id"] = job_id
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
            if st.button("Save notes", key=f"save_notes_{key}", use_container_width=True):
                update_application_field(app_id, "notes", notes_val)
                st.toast("Notes saved.")

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
                format="YYYY-MM-DD",
            )
            if follow_up and str(follow_up) != (existing_date or "")[:10]:
                update_application_field(app_id, "follow_up_date", str(follow_up))
                st.toast("Follow-up date saved.")

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
            if st.button("Save contact", key=f"save_contact_{key}", use_container_width=True):
                update_application_field(app_id, "contact_name",  contact_name)
                update_application_field(app_id, "contact_email", contact_email)
                st.toast("Contact saved.")

        # ── Follow-up email ───────────────────────────────────────────────────
        FOLLOWUP_STAGES = {"applied", "phone_screen", "interview"}
        if app.get("status") in FOLLOWUP_STAGES:
            st.markdown(
                '<div style="border-left:3px solid #FF5E1A;padding-left:10px;'
                'margin-top:8px;background:#1a1000;padding:8px 8px 2px 10px;">'
                '<span style="font-size:0.75rem;font-weight:700;letter-spacing:0.08em;'
                'text-transform:uppercase;color:#FF5E1A;">Follow-up</span></div>',
                unsafe_allow_html=True,
            )
            with st.container(border=True):
                draft_key  = f"followup_draft_{app_id}"
                email_key  = f"followup_email_{app_id}"

                fu_count   = (followup_counts or {}).get(job_id, 0)
                btn_label  = (
                    f"📧 Draft follow-up #{fu_count + 1}"
                    if fu_count > 0 else "📧 Draft follow-up email"
                )
                if fu_count > 0:
                    st.caption(f"📬 {fu_count} follow-up{'s' if fu_count != 1 else ''} sent")

                if st.button(btn_label, key=f"draft_btn_{key}", use_container_width=True):
                    with st.spinner("Finding contact email…"):
                        saved_email = (app.get("contact_email") or "").strip()
                        if saved_email:
                            result = {"email": saved_email, "name": app.get("contact_name"),
                                      "status": "verified", "source": "Saved contact"}
                        else:
                            result = find_verified_email(app, app.get("contact_name") or "")

                    st.session_state[email_key] = result

                    sender_name = ""
                    resume_summary = ""
                    master = get_master_resume()
                    if master and master.get("structured_json"):
                        try:
                            sj = json.loads(master["structured_json"])
                            sender_name    = sj.get("name") or ""
                            resume_summary = sj.get("summary") or ""
                        except Exception:
                            pass

                    history = get_followups(job_id)

                    with st.spinner("Drafting email…"):
                        try:
                            body = draft_followup_email(
                                job                = app,
                                sender_name        = sender_name,
                                contact_name       = app.get("contact_name") or "",
                                applied_date       = (app.get("applied_date") or "")[:10],
                                resume_summary     = resume_summary,
                                previous_followups = history,
                            )
                            st.session_state[draft_key] = body
                            st.session_state[f"followup_histlen_{app_id}"] = len(history)
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))

                # Show results if a draft exists in session state.
                email_result = st.session_state.get(email_key)
                draft_body   = st.session_state.get(draft_key)

                if email_result:
                    verified_email = email_result.get("email")
                    estatus = email_result.get("status")
                    if verified_email and estatus == "verified":
                        st.caption(f"✅ Contact: {verified_email} ({email_result['source']})")
                    elif not verified_email:
                        st.caption(f"⚠️ {email_result['source']}")
                    if verified_email and not (app.get("contact_email") or "").strip():
                        if st.button("Save to contact", key=f"save_found_{key}"):
                            update_application_field(app_id, "contact_email", verified_email)
                            if email_result.get("name") and not (app.get("contact_name") or "").strip():
                                update_application_field(app_id, "contact_name", email_result["name"])
                            st.toast("Contact saved.")
                            st.rerun()

                if draft_body is not None:
                    import html as _html
                    safe = _html.escape(draft_body)
                    st.components.v1.html(
                        f"""
                        <style>
                          body {{margin:0;background:#1a1200;padding:10px;}}
                          textarea {{
                            width:100%;box-sizing:border-box;height:200px;
                            background:#241900;color:#fafafa;border:1px solid #5a3a00;
                            border-radius:4px;padding:10px;font-size:0.85rem;
                            font-family:sans-serif;resize:vertical;
                          }}
                          button {{
                            margin-top:6px;width:100%;padding:7px;
                            background:#2e2000;color:#ffb347;border:1px solid #5a3a00;
                            border-radius:4px;cursor:pointer;font-size:0.8rem;
                          }}
                        </style>
                        <textarea id="em">{safe}</textarea>
                        <button onclick="
                          var t=document.getElementById('em');
                          t.select();
                          document.execCommand('copy');
                          this.innerText='✅ Copied!';
                          setTimeout(()=>this.innerText='📋 Copy email',1500);">
                          📋 Copy email
                        </button>
                        """,
                        height=270,
                    )
                    to_addr = (email_result or {}).get("email") or ""
                    subject = followup_subject(app)
                    import urllib.parse
                    mailto_href = (
                        f"mailto:{urllib.parse.quote(to_addr)}"
                        f"?subject={urllib.parse.quote(subject)}"
                    )
                    st.markdown(
                        f'<a href="{mailto_href}" target="_blank" '
                        f'style="display:block;text-align:center;padding:8px 0;'
                        f'font-size:0.85rem;color:#ff6b35;">📨 Open in email client</a>',
                        unsafe_allow_html=True,
                    )
                    histlen = st.session_state.get(f"followup_histlen_{app_id}", fu_count)
                    if st.button("✅ Mark as sent", key=f"mark_sent_{key}",
                                 use_container_width=True):
                        save_followup(
                            job_id        = job_id,
                            followup_num  = histlen + 1,
                            draft_text    = draft_body,
                            contact_email = (email_result or {}).get("email") or "",
                        )
                        del st.session_state[draft_key]
                        if email_key in st.session_state:
                            del st.session_state[email_key]
                        st.toast("Follow-up logged.")
                        st.rerun()


# ── Tabs layout ───────────────────────────────────────────────────────────────
tab_labels = [f"{label} ({len(grouped[k])})" for k, label in ACTIVE_PIPELINE]
closed_total = sum(len(grouped[k]) for k, _ in CLOSED_PIPELINE)
if closed_total > 0:
    tab_labels.append(f"Closed ({closed_total})")

tabs = st.tabs(tab_labels)

for tab, (status_key, label) in zip(tabs[:len(ACTIVE_PIPELINE)], ACTIVE_PIPELINE):
    with tab:
        apps_in_tab = grouped[status_key]
        if apps_in_tab:
            for app in apps_in_tab:
                render_kanban_card(app, col_key=status_key, tailored_ids=tailored_ids,
                                   followup_counts=followup_counts)
        else:
            st.caption("Nothing here yet.")

if closed_total > 0:
    with tabs[-1]:
        for status_key, label in CLOSED_PIPELINE:
            apps_in_group = grouped[status_key]
            if apps_in_group:
                st.markdown(f"**{label}**")
                for app in apps_in_group:
                    render_kanban_card(app, col_key=status_key, tailored_ids=tailored_ids,
                                       followup_counts=followup_counts)
