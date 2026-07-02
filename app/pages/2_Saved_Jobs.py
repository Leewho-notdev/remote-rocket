"""
pages/2_Saved_Jobs.py
Quick-access view of bookmarked jobs not yet applied to.
Full detail and pipeline management is on the Applications page.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from components.db import get_applications, upsert_application
from components.theme import apply_theme

st.set_page_config(page_title="Saved Jobs — Remote Rocket", page_icon="🚀", layout="wide")
apply_theme()
st.title("🔖 Saved Jobs")
st.caption("Bookmarked listings you haven't applied to yet.")

st.divider()

saved = get_applications(status="saved")

if not saved:
    st.info(
        "Nothing saved yet. Browse jobs and click **Save** on any listing to add it here.",
        icon="🔖",
    )
    st.stop()

st.caption(f"{len(saved)} saved listing(s)")

for app in saved:
    app_id  = app["id"]
    job_id  = app["job_id"]
    title   = app.get("title", "Untitled")
    company = app.get("company", "—")
    url     = app.get("url", "")

    lo, hi = app.get("salary_min"), app.get("salary_max")
    if lo and hi:
        salary = f"${lo:,}–${hi:,}"
    elif lo:
        salary = f"${lo:,}+"
    else:
        salary = "Salary not listed"

    score = app.get("relevance_score")
    if score is not None:
        score_str = f"🟢 {score}/10" if score >= 8 else (f"🟡 {score}/10" if score >= 5 else f"🔴 {score}/10")
    else:
        score_str = "⬜ Unscored"

    with st.container(border=True):
        c1, c2, c3 = st.columns([4, 2, 2])

        with c1:
            if url:
                st.markdown(f"**[{title}]({url})**")
            else:
                st.markdown(f"**{title}**")
            st.caption(f"{company}  ·  {salary}  ·  {score_str}")

        with c2:
            if st.button("✅ Mark Applied", key=f"applied_{app_id}", use_container_width=True):
                upsert_application(job_id, "applied", app.get("notes") or "")
                st.success("Moved to Applied!")
                st.rerun()

        with c3:
            if st.button("📁 View in Pipeline", key=f"pipeline_{app_id}", use_container_width=True):
                st.switch_page("pages/3_Applications.py")

st.divider()
st.caption("To manage notes, follow-up dates, and pipeline status, use the **Applications** page.")
