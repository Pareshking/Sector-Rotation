"""App shell: page config, theme, navigation and the status header every page shares.

Run with ``streamlit run app/streamlit_app.py``. Each page in ``app/views`` is a
read-only consumer of the published artifacts (``data/processed``,
``data/universe/universe.json``) through ``app/data.py``; nothing here computes
a decision of its own.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(
    page_title="India Sector Rotation",
    page_icon=":material/donut_small:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

_LOGO_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 168 32">
  <rect x="1" y="6" width="20" height="20" rx="6" fill="#4338CA"/>
  <path d="M6 20.5 10 15l3 3 4-6" stroke="#fff" stroke-width="2.2" fill="none"
        stroke-linecap="round" stroke-linejoin="round"/>
  <text x="30" y="22" font-family="Inter,-apple-system,'Segoe UI',system-ui,sans-serif"
        font-size="15" font-weight="750" letter-spacing="-.3" fill="#64748B">Dual Momentum</text>
</svg>"""
# st.logo only accepts an absolute http(s) link, so the root is spelled out.
# The default page is served at "/"; "/Portfolio" answers "Page not found".
st.logo(
    f"data:image/svg+xml;base64,{base64.b64encode(_LOGO_SVG).decode()}",
    size="medium",
    link="https://dualmomentum.streamlit.app/",
)

from app.components.header import global_header  # noqa: E402
from app.components.navigation import PAGES, mobile_nav  # noqa: E402
from app.components.theme import inject_theme  # noqa: E402

# Deliberately not "pages/": Streamlit auto-discovers that directory name and
# builds a second, filename-derived sidebar nav alongside the explicit one below.
VIEWS_DIR = ROOT / "app" / "views"

# ``url_path`` is set explicitly so page URLs stay stable when files are renamed.
pages = [
    st.Page(VIEWS_DIR / page.file, title=page.title, icon=page.icon, url_path=page.url_path, default=page.default)
    for page in PAGES
]
current = st.navigation(pages, position="top")

inject_theme()
global_header()
mobile_nav(next((page.url_path for page in PAGES if page.title == current.title), ""))
current.run()
