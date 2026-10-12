from __future__ import annotations

import base64
import sys
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="India Sector Rotation",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Logo shown in the sticky top-nav so the site identity is always visible,
# even after the brand_header scrolls out of view.
_LOGO_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 40">
  <circle cx="8"  cy="20" r="6" fill="#FF5F57"/>
  <circle cx="22" cy="20" r="6" fill="#FEBC2E"/>
  <circle cx="36" cy="20" r="6" fill="#28C840"/>
  <text x="50" y="26"
        font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif"
        font-size="16" font-weight="800" letter-spacing="-.4" fill="#1E293B">
    Dual Momentum
  </text>
</svg>"""
# st.logo only accepts an absolute http(s) link, so the root is spelled out.
# The default page is served at "/"; "/Overview" answers "Page not found".
st.logo(
    f"data:image/svg+xml;base64,{base64.b64encode(_LOGO_SVG).decode()}",
    size="medium",
    link="https://dualmomentum.streamlit.app/",
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Deliberately not "pages/": Streamlit auto-discovers that directory name and
# builds a second, filename-derived sidebar nav alongside the explicit one below.
VIEWS_DIR = ROOT / "app" / "views"

from app.components.navigation import PAGES  # noqa: E402

# Top navigation keeps every view one tap away. ``url_path`` is set explicitly
# so page URLs stay stable when files are renamed or reordered.
pages = [
    st.Page(VIEWS_DIR / page.file, title=page.title, icon=page.icon, url_path=page.url_path, default=page.default)
    for page in PAGES
]

st.navigation(pages, position="top", expanded=False).run()
