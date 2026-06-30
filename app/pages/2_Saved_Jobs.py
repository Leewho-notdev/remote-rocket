"""
pages/2_Saved_Jobs.py
Saved and shortlisted jobs view.
Full implementation in Step 7.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from components.db import get_applications
from components.job_card import render_job_card

st.set_page_config(page_title="Saved Jobs — Remote Rocket", page_icon="🔖", layout="wide")
st.title("🔖 Saved Jobs")
st.caption("Jobs you've bookmarked but not yet applied to.")

st.divider()

# Fetch saved jobs (status = 'saved')
saved = get_applications(status="saved")

if not saved:
    st.info(
        "No saved jobs yet. Browse jobs and click **Save** on any listing to add it here.",
        icon="🔖",
    )
else:
    st.caption(f"{len(saved)} saved job(s)")
    for i, app in enumerate(saved):
        # Re-use the job card — it handles the display of title, company, etc.
        # The full application tracker view with notes is built in Step 7.
        render_job_card(app, index=i)
