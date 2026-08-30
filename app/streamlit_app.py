from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="India Sector Rotation",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Deliberately not "pages/": Streamlit auto-discovers that directory name and
# builds a second, filename-derived sidebar nav alongside the explicit one below.
VIEWS_DIR = ROOT / "app" / "views"

# Top navigation keeps every research view one tap away. ``url_path`` is set
# explicitly so page URLs stay stable when files are renamed or reordered.
pages = [
    st.Page(VIEWS_DIR / "1_Overview.py", title="Dashboard", icon="📊", url_path="Overview", default=True),
    st.Page(VIEWS_DIR / "2_Sectors.py", title="Sectors", icon="🏭", url_path="Sectors"),
    st.Page(VIEWS_DIR / "3_Themes.py", title="Themes", icon="🧭", url_path="Themes"),
    st.Page(VIEWS_DIR / "4_Rankings.py", title="Screener", icon="🔎", url_path="Rankings"),
    st.Page(VIEWS_DIR / "5_Backtest.py", title="Backtest", icon="📈", url_path="Backtest"),
    st.Page(VIEWS_DIR / "6_ETF_Detail.py", title="Exposure", icon="💹", url_path="ETF_Detail"),
    st.Page(VIEWS_DIR / "7_System_Health.py", title="Data Health", icon="🛡️", url_path="System_Health"),
]

st.navigation(pages, position="top", expanded=False).run()
