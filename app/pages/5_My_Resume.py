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
from components.resume_files import extract_text, markdown_to_docx
from components.resume_generator import structure_resume, structured_to_markdown
from components.theme import apply_theme

# Centered layout reads far better on mobile than wide/multi-column.
st.set_page_config(page_title="My Resume — Remote Rocket", page_icon="🚀", layout="centered")
apply_theme()

st.title("📄 My Resume")
st.caption("Set this up once. Every job you tailor for uses it — no need to touch it again.")

master = get_master_resume()
replace_mode = st.session_state.get("resume_replace_mode", False)
edit_mode = st.session_state.get("resume_edit_mode", False)


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

        docx_bytes = None
        try:
            md = structured_to_markdown(json.loads(structured)) if structured else raw
            docx_bytes = markdown_to_docx(md)
        except Exception:
            pass

        save_master_resume(raw, structured, filename, docx_bytes)
        st.session_state["resume_replace_mode"] = False
        if structured is None:
            st.warning("Saved. (Couldn't auto-organize the sections, so tailoring will use the raw text.)")
        else:
            st.success("Saved and organized! You're ready to tailor resumes from any job.")
        st.rerun()


# ── Edit mode ─────────────────────────────────────────────────────────────────
def _render_edit(m: dict) -> None:
    st.subheader("Edit your resume")

    edited = st.text_area(
        "Resume text",
        value=m.get("raw_text") or "",
        height=600,
        label_visibility="collapsed",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Cancel", use_container_width=True):
            st.session_state["resume_edit_mode"] = False
            st.rerun()
    with col2:
        if st.button("✨ Save changes", type="primary", use_container_width=True):
            with st.spinner("Re-organizing your resume…"):
                structured = structure_resume(edited.strip())

            # Build a fresh .docx from the updated content.
            docx_bytes = None
            try:
                md = structured_to_markdown(json.loads(structured)) if structured else edited.strip()
                docx_bytes = markdown_to_docx(md)
            except Exception:
                pass

            save_master_resume(edited.strip(), structured, m.get("source_filename"), docx_bytes)
            st.session_state["resume_edit_mode"] = False
            st.rerun()


# ── Read-only preview ──────────────────────────────────────────────────────────
def _render_preview(m: dict) -> None:
    updated = (m.get("updated_at") or "")[:16].replace("T", " ")
    src = m.get("source_filename") or "pasted text"
    st.success(f"Master resume saved ✓  ·  from {src}  ·  updated {updated}")

    docx_bytes = m.get("master_docx")
    if docx_bytes:
        col1, col2, col3 = st.columns(3)
    else:
        col1, col2 = st.columns(2)

    with col1:
        if st.button("✏️ Edit text", use_container_width=True):
            st.session_state["resume_edit_mode"] = True
            st.rerun()
    with col2:
        if st.button("🔄 Replace / Re-upload", use_container_width=True):
            st.session_state["resume_replace_mode"] = True
            st.rerun()
    if docx_bytes:
        with col3:
            src = m.get("source_filename") or "resume.docx"
            if not src.lower().endswith(".docx"):
                src = src.rsplit(".", 1)[0] + ".docx"
            st.download_button("⬇️ Download .docx", data=bytes(docx_bytes),
                               file_name=src, mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               use_container_width=True)

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
if master and edit_mode:
    _render_edit(master)
elif master and not replace_mode:
    _render_preview(master)
else:
    if master and replace_mode and st.button("← Cancel", use_container_width=True):
        st.session_state["resume_replace_mode"] = False
        st.rerun()
    _render_uploader()
