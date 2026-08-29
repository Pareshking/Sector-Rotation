from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import ranking_bar, rrg_quadrant
from app.components.metrics import data_health_banner, get_metadata, metric_row
from app.components.theme import inject_theme, page_header, section
from app.data import load_summary

inject_theme()
page_header("India Sector Rotation", "Overview", "Relative strength, momentum and rotation at a glance")
data_health_banner(get_metadata())
summary = load_summary()
if summary.empty:
    st.warning("No prepared dataset found. Run the data pipeline first.")
    st.stop()
metric_row(summary)
section("Rotation map")
st.plotly_chart(rrg_quadrant(summary), width="stretch")
section("Cross-sectional momentum")
st.plotly_chart(ranking_bar(summary.head(20)), width="stretch")
section("Leaderboard")
st.dataframe(summary.sort_values("rank").head(20), width="stretch", hide_index=True)
