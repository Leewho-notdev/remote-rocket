import streamlit as st
from components.theme import apply_theme
from components.db import insert_manual_job, upsert_application
from components.job_fetcher import fetch_url, html_to_text, extract_job

st.set_page_config(page_title="Add Job — Remote Rocket", page_icon="🚀", layout="centered")
apply_theme()

st.title("➕ Add Job")
st.caption("Paste any job posting URL to pull it in, score it, and tailor your resume.")

url = st.text_input("Job posting URL", placeholder="https://boards.greenhouse.io/...")

if st.button("Fetch & Analyze", type="primary", disabled=not url.strip()):
    with st.spinner("Fetching page..."):
        try:
            html = fetch_url(url.strip())
            raw_text = html_to_text(html)
        except Exception as e:
            st.error(f"Could not fetch that URL: {e}")
            st.stop()

    with st.spinner("Analyzing with Claude..."):
        try:
            job = extract_job(url.strip(), raw_text)
        except Exception as e:
            st.error(f"Extraction failed: {e}")
            st.stop()

    st.session_state["pending_manual_job"] = job

if "pending_manual_job" in st.session_state:
    job = st.session_state["pending_manual_job"]

    st.divider()
    st.subheader(job.get("title", "Unknown Title"))
    st.markdown(f"**{job.get('company', 'Unknown Company')}**  ·  {job.get('location', 'Remote')}")

    col1, col2, col3 = st.columns(3)
    score = job.get("relevance_score")
    emoji = "🟢" if score and score >= 8 else "🟡" if score and score >= 5 else "🔴"
    col1.metric("Relevance", f"{emoji} {score}/10" if score else "Unscored")
    sal = job.get("salary_raw") or (
        f"${job['salary_min']:,}+" if job.get("salary_min") else "Not listed"
    )
    col2.metric("Salary", sal)
    col3.metric("Type", job.get("employment_type", "").replace("_", " ").title() or "Unknown")

    if job.get("requirements"):
        with st.expander("Requirements extracted"):
            for r in job["requirements"]:
                st.markdown(f"- {r}")

    st.divider()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("✨ Save & Tailor Resume", type="primary", use_container_width=True):
            job_id = insert_manual_job(job)
            if job_id:
                upsert_application(job_id, "saved")
                st.session_state["tailor_job_id"] = job_id
                del st.session_state["pending_manual_job"]
                st.switch_page("pages/6_Tailor.py")
            else:
                st.error("This job URL is already in your database.")

    with c2:
        if st.button("✅ Save & Mark Applied", use_container_width=True):
            job_id = insert_manual_job(job)
            if job_id:
                upsert_application(job_id, "applied")
                del st.session_state["pending_manual_job"]
                st.success("Added to your Applications list!")
            else:
                st.error("This job URL is already in your database.")
