"""
pages/5_My_Resume.py
Phase 2 — set up your master resume ONCE.

Upload a PDF/DOCX (paste is a fallback). On save, a lightweight Claude pass
structures the text into clean sections, stored alongside the raw text so
tailoring has high-quality input. The page then shows a read-only preview with
a big "Replace / Re-upload" button. No manual editing — phone-friendly.
"""

import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st

from components.resume_store import get_master_resume, save_master_resume
from components.resume_files import extract_text
from components.resume_generator import structure_resume, structured_to_markdown

# Centered layout reads far better on mobile than wide/multi-column.
st.set_page_config(page_title="My Resume — Remote Rocket", page_icon="📄", layout="centered")

st.title("📄 My Resume")
st.caption("Set this up once. Every job you tailor for uses it — no need to touch it again.")

master = get_master_resume()
replace_mode = st.session_state.get("resume_replace_mode", False)


# ── Upload / replace flow ──────────────────────────────────────────────────────
def _render_uploader() -> None:
    st.subheader("Upload your resume")
    st.caption("PDF or Word (.docx). We'll read it and organize it for you automatically.")

    uploaded = st.file_uploader(
        "Resume file", type=["pdf", "docx", "txt", "md"], label_visibility="collapsed",
    )

    pasted = ""
    with st.expander("…or paste the text instead"):
        pasted = st.text_area(
            "Paste resume text", height=240, label_visibility="collapsed",
            placeholder="Paste your full resume here — experience, skills, education, metrics…",
        )

    disabled = uploaded is None and not pasted.strip()
    if st.button("✨ Analyze & save", type="primary", use_container_width=True, disabled=disabled):
        # Get raw text from whichever input was provided.
        filename = None
        try:
            if uploaded is not None:
                raw = extract_text(uploaded.name, uploaded.getvalue())
                filename = uploaded.name
            else:
                raw = pasted.strip()
        except (ValueError, RuntimeError) as e:
            st.error(str(e))
            return

        with st.spinner("Reading and organizing your resume…"):
            structured = structure_resume(raw)  # None on failure — we still save raw

        save_master_resume(raw, structured, filename)
        st.session_state["resume_replace_mode"] = False
        if structured is None:
            st.warning("Saved. (Couldn't auto-organize the sections, so tailoring will use the raw text.)")
        else:
            st.success("Saved and organized! You're ready to tailor resumes from any job.")
        st.rerun()


# ── Read-only preview ──────────────────────────────────────────────────────────
def _render_preview(m: dict) -> None:
    updated = (m.get("updated_at") or "")[:16].replace("T", " ")
    src = m.get("source_filename") or "pasted text"
    st.success(f"Master resume saved ✓  ·  from {src}  ·  updated {updated}")

    if st.button("🔄 Replace / Re-upload", use_container_width=True):
        st.session_state["resume_replace_mode"] = True
        st.rerun()

    st.divider()

    structured = None
    if m.get("structured_json"):
        try:
            structured = json.loads(m["structured_json"])
        except (json.JSONDecodeError, TypeError):
            structured = None

    if structured:
        st.markdown(structured_to_markdown(structured))
    else:
        # No structured data — show the raw text read-only.
        st.caption("Preview (raw text):")
        st.text(m.get("raw_text") or "")

    st.divider()
    st.caption(
        "To tailor for a specific role, open any job on **Browse Jobs** or the "
        "**Applications** board and tap **✨ Tailor resume**."
    )


# ── Route ──────────────────────────────────────────────────────────────────────
if master and not replace_mode:
    _render_preview(master)
else:
    if master and replace_mode and st.button("← Cancel", use_container_width=True):
        st.session_state["resume_replace_mode"] = False
        st.rerun()
    _render_uploader()
