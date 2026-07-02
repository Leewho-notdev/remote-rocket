"""
theme.py
Shared visual theme for Remote Rocket — a dark translation of the
Lionheart Search brand (lionheartsearch.com).

Streamlit re-runs each page as its own script, so injected CSS does not carry
across page navigation. Every page calls apply_theme() right after
st.set_page_config() so the styling is present on each screen.

Brand cues borrowed from lionheartsearch.com:
  - Space Grotesk for headings (heavy, tight letter-spacing)
  - Montserrat for labels / buttons (uppercase, wide tracking)
  - Orange #FF5E1A as the single accent against near-black
"""

import streamlit as st

# ── Palette ───────────────────────────────────────────────────────────────────
BG        = "#0D0D0D"   # app background (brand black)
SURFACE   = "#161616"   # cards, sidebar, inputs
SURFACE_2 = "#1F1F1F"   # hover / elevated
BORDER    = "#2A2A2A"
ORANGE    = "#FF5E1A"   # brand accent
ORANGE_HI = "#FF7A45"   # hover
TEXT      = "#F4F2F0"
MUTED     = "#9A9691"

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Montserrat:wght@400;500;600;700;800&display=swap');

/* ── Base ─────────────────────────────────────────────────────────────── */
.stApp {{
    background: {BG};
    color: {TEXT};
    font-family: 'Montserrat', -apple-system, BlinkMacSystemFont, sans-serif;
}}

/* Headings — Space Grotesk, heavy, tight tracking */
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {{
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: {TEXT};
}}
.stApp h1 {{ font-size: 2.9rem; line-height: 1.05; }}
.stApp h2 {{ font-size: 1.9rem; }}
.stApp h3 {{ font-size: 1.35rem; }}

/* Orange accent bar under the page title */
.stApp h1:first-of-type {{
    padding-bottom: 0.35rem;
    border-bottom: 3px solid {ORANGE};
    display: inline-block;
}}

/* Body copy + captions */
.stApp p, .stApp li, .stApp label, .stApp .stMarkdown {{
    font-family: 'Montserrat', sans-serif;
}}
.stApp [data-testid="stCaptionContainer"],
.stApp small {{
    color: {MUTED};
    letter-spacing: 0.01em;
}}

/* ── Sidebar ──────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {{
    background: {SURFACE};
    border-right: 1px solid {BORDER};
}}
[data-testid="stSidebarNav"] {{
    padding-top: 0.5rem;
}}
[data-testid="stSidebarNav"] a {{
    border-radius: 0 !important;
    margin: 1px 0;
}}
[data-testid="stSidebarNav"] a span {{
    font-family: 'Montserrat', sans-serif;
    font-weight: 600;
    font-size: 0.9rem;
    letter-spacing: 0.02em;
    color: {MUTED};
}}
[data-testid="stSidebarNav"] a:hover {{
    background: {SURFACE_2};
}}
[data-testid="stSidebarNav"] a:hover span {{
    color: {TEXT};
}}
/* Active page: orange left border + brighter text */
[data-testid="stSidebarNav"] a[aria-current="page"] {{
    background: {SURFACE_2};
    border-left: 3px solid {ORANGE} !important;
}}
[data-testid="stSidebarNav"] a[aria-current="page"] span {{
    color: {TEXT};
    font-weight: 700;
}}

/* ── Buttons ──────────────────────────────────────────────────────────── */
.stButton > button, .stDownloadButton > button {{
    font-family: 'Montserrat', sans-serif;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.10em;
    font-size: 0.78rem;
    border-radius: 0 !important;
    border: 1px solid {BORDER};
    background: {SURFACE};
    color: {TEXT};
    transition: all 0.15s ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
    border-color: {ORANGE};
    color: {ORANGE};
    background: {SURFACE_2};
}}
/* Primary buttons — solid orange, brand CTA */
.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"] {{
    background: {ORANGE};
    border-color: {ORANGE};
    color: #0D0D0D;
}}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:hover {{
    background: {ORANGE_HI};
    border-color: {ORANGE_HI};
    color: #0D0D0D;
}}

/* ── Metrics ──────────────────────────────────────────────────────────── */
[data-testid="stMetric"] {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 0 !important;
    padding: 1rem 1.15rem;
}}
[data-testid="stMetricLabel"] p {{
    font-family: 'Montserrat', sans-serif;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.72rem;
    color: {MUTED};
}}
[data-testid="stMetricValue"] {{
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: {TEXT};
}}

/* ── Alerts / info cards ─────────────────────────────────────────────── */
[data-testid="stAlert"] {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-left: 3px solid {ORANGE};
    border-radius: 0 !important;
}}

/* ── Inputs ───────────────────────────────────────────────────────────── */
[data-baseweb="input"], [data-baseweb="select"], [data-baseweb="textarea"],
.stTextInput input, .stNumberInput input, .stTextArea textarea {{
    background: {SURFACE} !important;
    border-color: {BORDER} !important;
}}
.stTextInput input:focus, .stTextArea textarea:focus {{
    border-color: {ORANGE} !important;
}}

/* ── Tabs ─────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {{
    border-bottom: 1px solid {BORDER};
    gap: 0.25rem;
}}
.stTabs [data-baseweb="tab"] {{
    font-family: 'Montserrat', sans-serif;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 0.8rem;
    color: {MUTED};
}}
.stTabs [aria-selected="true"] {{
    color: {TEXT};
}}
.stTabs [data-baseweb="tab-highlight"] {{
    background: {ORANGE};
}}

/* ── Job card containers (st.container(border=True)) ─────────────────── */
[data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stVerticalBlockBorderWrapper"] > div {{
    border-radius: 0 !important;
}}

/* ── Expander — target all nested elements ────────────────────────────── */
[data-testid="stExpander"],
[data-testid="stExpander"] > *,
[data-testid="stExpander"] details,
[data-testid="stExpander"] summary,
[data-testid="stExpanderDetails"] {{
    border-radius: 0 !important;
    background: {SURFACE};
}}
[data-testid="stExpander"] {{
    border: 1px solid {BORDER};
}}

/* ── Multiselect / tag pills ─────────────────────────────────────────── */
[data-baseweb="tag"] {{
    border-radius: 0 !important;
}}

/* ── BaseWeb dropdowns, popups ───────────────────────────────────────── */
[data-baseweb="popover"],
[data-baseweb="menu"],
[data-baseweb="select"] > div {{
    border-radius: 0 !important;
}}

/* ── Dividers, links ──────────────────────────────────────────────────── */
.stApp hr {{ border-color: {BORDER}; }}
.stApp a {{ color: {ORANGE}; }}
.stApp a:hover {{ color: {ORANGE_HI}; }}

/* Trim Streamlit's default top padding for a tighter header */
.stApp [data-testid="stMainBlockContainer"] {{
    padding-top: 3rem;
}}
</style>
"""


def apply_theme() -> None:
    """Inject the Remote Rocket / Lionheart dark theme. Call once per page,
    right after st.set_page_config()."""
    st.markdown(_CSS, unsafe_allow_html=True)
