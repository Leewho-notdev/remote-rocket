"""
pages/6_Tailor.py
Phase 2 — tailor a resume + cover letter for one job.

Mobile-first and one-tap: arrive here from a job's "✨ Tailor resume" button,
hit Generate, and download. No manual editing required (but available).
Every generation is saved as a new version, so you can regenerate with a note
and still keep the old one.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st

from components.db import get_job_by_id, get_applications
from components.resume_store import (
    has_master_resume,
    get_master_resume,
    add_tailored_version,
    get_latest_tailored,
    list_tailored_versions,
    update_tailored_content,
)
from components.resume_files import markdown_to_docx
from components.resume_generator import generate_tailored, resume_text_for_tailoring

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

st.set_page_config(page_title="Tailor — Remote Rocket", page_icon="✨", layout="centered")
st.title("✨ Tailor Resume")

# ── Guard: master resume must exist ────────────────────────────────────────────
if not has_master_resume():
    st.warning("Set up your master resume first — it only takes a minute.", icon="📄")
    st.page_link("pages/5_My_Resume.py", label="Go to My Resume", icon="📄")
    st.stop()


# ── Resolve which job we're tailoring for ──────────────────────────────────────
def _resolve_job_id() -> int | None:
    qp = st.query_params.get("job_id")
    if qp:
        try:
            return int(qp)
        except (ValueError, TypeError):
            return None
    return None

job_id = _resolve_job_id()

if job_id is None:
    # Fallback picker: choose from tracked applications.
    apps = get_applications()
    if not apps:
        st.info(
            "Open a job on **Browse Jobs** or the **Applications** board and tap "
            "**✨ Tailor resume** to start.",
            icon="✨",
        )
        st.stop()
    options = [a["job_id"] for a in apps]
    labels = {a["job_id"]: f"{a.get('title', 'Untitled')} @ {a.get('company', '—')}" for a in apps}
    job_id = st.selectbox("Which job?", options, format_func=lambda j: labels[j])

job = get_job_by_id(job_id)
if not job:
    st.error("That job could not be found. It may have been removed.")
    st.stop()

# ── Job context (compact) ──────────────────────────────────────────────────────
st.subheader(job.get("title", "Untitled"))
st.caption(f"**{job.get('company', '—')}**")
if job.get("url"):
    st.link_button("🔗 View listing", job["url"], use_container_width=True)

st.divider()

latest = get_latest_tailored(job_id)

# ── Generate / regenerate ──────────────────────────────────────────────────────
notes = st.text_input(
    "Optional: anything to emphasize?",
    placeholder="e.g. lean into ROAS + Performance Max wins",
    key="tailor_notes",
)
gen_label = "🔄 Regenerate" if latest else "✨ Generate resume + cover letter"
if st.button(gen_label, type="primary", use_container_width=True):
    master = get_master_resume()
    resume_input = resume_text_for_tailoring(master)
    with st.spinner("Claude is tailoring your resume and writing a cover letter…"):
        try:
            result = generate_tailored(job, resume_input, notes=notes)
        except RuntimeError as e:
            st.error(str(e))
            st.stop()
    v = add_tailored_version(
        job_id, result["tailored_resume"], result["cover_letter"], notes=notes
    )
    st.success(f"Done — version {v} ready below.")
    st.rerun()

if not latest:
    st.info("Tap **Generate** — no editing required. You'll get a resume and a cover letter to download.", icon="👆")
    st.stop()


# ── Results (latest version) ───────────────────────────────────────────────────
company = job.get("company", "resume")
safe_company = ("".join(c for c in company if c.isalnum() or c in " -_").strip().replace(" ", "_")) or "Company"

st.caption(
    f"Showing version {latest['version']} · generated {(latest.get('created_at') or '')[:16].replace('T', ' ')}"
    + (f" · note: “{latest['notes']}”" if latest.get("notes") else "")
)

tab_resume, tab_cover = st.tabs(["📄 Resume", "✉️ Cover Letter"])

with tab_resume:
    resume_text = st.text_area(
        "Tailored resume (edit if you like)",
        value=latest.get("resume_md") or "",
        height=420,
        key=f"resume_edit_{latest['id']}",
    )
    st.download_button(
        "⬇️ Download Resume (.docx)",
        data=markdown_to_docx(resume_text, title=f"{company} Resume"),
        file_name=f"Resume_{safe_company}.docx",
        mime=DOCX_MIME,
        use_container_width=True,
        key="dl_resume",
    )
    with st.expander("📋 Copy text"):
        st.code(resume_text, language="markdown")
    with st.expander("👁 Preview"):
        st.markdown(resume_text)

with tab_cover:
    cover_text = st.text_area(
        "Cover letter (edit if you like)",
        value=latest.get("cover_letter_md") or "",
        height=420,
        key=f"cover_edit_{latest['id']}",
    )
    st.download_button(
        "⬇️ Download Cover Letter (.docx)",
        data=markdown_to_docx(cover_text, title=f"{company} Cover Letter"),
        file_name=f"CoverLetter_{safe_company}.docx",
        mime=DOCX_MIME,
        use_container_width=True,
        key="dl_cover",
    )
    with st.expander("📋 Copy text"):
        st.code(cover_text, language="markdown")
    with st.expander("👁 Preview"):
        st.markdown(cover_text)

# Save inline edits back onto this version (doesn't create a new version).
if st.button("💾 Save my edits", use_container_width=True):
    update_tailored_content(latest["id"], resume_text, cover_text)
    st.toast("Edits saved to this version.")


# ── Version history ────────────────────────────────────────────────────────────
versions = list_tailored_versions(job_id)
if len(versions) > 1:
    with st.expander(f"🕘 Version history ({len(versions)} versions)"):
        for v in versions:
            head = f"**v{v['version']}** · {(v.get('created_at') or '')[:16].replace('T', ' ')}"
            if v.get("notes"):
                head += f" · “{v['notes']}”"
            if v["id"] == latest["id"]:
                head += " · _current_"
            st.markdown(head)
            d1, d2 = st.columns(2)
            with d1:
                st.download_button(
                    "Resume",
                    data=markdown_to_docx(v.get("resume_md") or "", title=f"{company} Resume v{v['version']}"),
                    file_name=f"Resume_{safe_company}_v{v['version']}.docx",
                    mime=DOCX_MIME,
                    use_container_width=True,
                    key=f"dlh_resume_{v['id']}",
                )
            with d2:
                st.download_button(
                    "Cover letter",
                    data=markdown_to_docx(v.get("cover_letter_md") or "", title=f"{company} Cover Letter v{v['version']}"),
                    file_name=f"CoverLetter_{safe_company}_v{v['version']}.docx",
                    mime=DOCX_MIME,
                    use_container_width=True,
                    key=f"dlh_cover_{v['id']}",
                )
            st.divider()
