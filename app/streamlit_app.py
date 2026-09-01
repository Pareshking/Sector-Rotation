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
_LOGO_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 280 40">
  <rect x="0" y="26" width="7" height="13" rx="2" fill="#4338CA" opacity=".55"/>
  <rect x="9"  y="18" width="7" height="21" rx="2" fill="#4338CA" opacity=".75"/>
  <rect x="18" y="8"  width="7" height="31" rx="2" fill="#4338CA"/>
  <rect x="27" y="22" width="7" height="17" rx="2" fill="#4338CA" opacity=".55"/>
  <text x="40" y="29"
        font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif"
        font-size="17" font-weight="800" letter-spacing="-.4" fill="#1E293B">
    India Sector Rotation
  </text>
</svg>"""
st.logo(
    f"data:image/svg+xml;base64,{base64.b64encode(_LOGO_SVG).decode()}",
    size="medium",
    link="/Overview",
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PAGES_DIR = ROOT / "app" / "pages"

# Top navigation keeps every research view one tap away. ``url_path`` is set
# explicitly so page URLs stay stable when files are renamed or reordered.
pages = [
    st.Page(PAGES_DIR / "1_Overview.py", title="Dashboard", icon="📊", url_path="Overview", default=True),
    st.Page(PAGES_DIR / "2_Sectors.py", title="Sectors", icon="🏭", url_path="Sectors"),
    st.Page(PAGES_DIR / "3_Themes.py", title="Themes", icon="🧭", url_path="Themes"),
    st.Page(PAGES_DIR / "4_Rankings.py", title="Screener", icon="🔎", url_path="Rankings"),
    st.Page(PAGES_DIR / "5_Backtest.py", title="Backtest", icon="📈", url_path="Backtest"),
    st.Page(PAGES_DIR / "6_ETF_Detail.py", title="Exposure", icon="💹", url_path="ETF_Detail"),
    st.Page(PAGES_DIR / "7_System_Health.py", title="Data Health", icon="🛡️", url_path="System_Health"),
]

st.navigation(pages, position="top", expanded=False).run()
