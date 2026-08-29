from __future__ import annotations

from pathlib import Path
import sys

import streamlit as st

st.set_page_config(
    page_title="India Sector Rotation",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Use Streamlit's native top navigation instead of the sidebar. This is the
# critical mobile fix: every research view remains one tap away on a phone.
pages = [
    st.Page(ROOT / "app" / "pages" / "1_Overview.py", title="Overview", icon="📊", default=True),
    st.Page(ROOT / "app" / "pages" / "2_Sectors.py", title="Sectors", icon="🏭"),
    st.Page(ROOT / "app" / "pages" / "3_Themes.py", title="Themes", icon="🧭"),
    st.Page(ROOT / "app" / "pages" / "4_Rankings.py", title="Rankings", icon="📈"),
    st.Page(ROOT / "app" / "pages" / "5_ETF_Detail.py", title="ETF Detail", icon="💹"),
    st.Page(ROOT / "app" / "pages" / "6_System_Health.py", title="System Health", icon="🛡️"),
]

pg = st.navigation(pages, position="top", expanded=False)
pg.run()
