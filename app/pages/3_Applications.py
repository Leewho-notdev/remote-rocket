"""
pages/3_Applications.py
Application pipeline tracker — Kanban-style status board.
Full implementation in Step 7.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from components.db import get_applications

st.set_page_config(page_title="Applications — Remote Rocket", page_icon="📁", layout="wide")
st.title("📁 Applications")
st.caption("Track where you are in each application pipeline.")

st.divider()

# Status pipeline in order
STATUSES = [
    ("saved",        "🔖 Saved"),
    ("applied",      "✅ Applied"),
    ("phone_screen", "📞 Phone Screen"),
    ("interview",    "🎤 Interview"),
    ("offer",        "🎉 Offer"),
    ("rejected",     "❌ Rejected"),
    ("withdrawn",    "↩️ Withdrawn"),
]

# Quick count overview
all_apps = get_applications()
counts   = {s: 0 for s, _ in STATUSES}
for app in all_apps:
    status = app.get("status", "saved")
    if status in counts:
        counts[status] += 1

if not all_apps:
    st.info(
        "No applications tracked yet. "
        "Go to **Browse Jobs** and click **Save** or **Mark Applied** on a listing.",
        icon="📁",
    )
    st.stop()

# Status count summary row
cols = st.columns(len(STATUSES))
for col, (status_key, label) in zip(cols, STATUSES):
    with col:
        st.metric(label, counts[status_key])

st.divider()
st.info("Full Kanban view with notes and follow-up reminders coming in Step 7.", icon="🔧")
