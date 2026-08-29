from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import rs_heatmap
from app.components.theme import inject_theme, page_header, section
from app.data import load_summary

inject_theme()
page_header("Exposure Universe", "Themes", "Thematic baskets ranked by relative momentum")
summary = load_summary()
frame = summary[summary["category"] == "thematic"].sort_values("rank") if not summary.empty else summary
if frame.empty:
    st.info("No thematic observations are available.")
    st.stop()
section("Theme momentum heatmap")
st.plotly_chart(rs_heatmap(frame), width="stretch")
section("Theme leaderboard")
st.dataframe(frame, width="stretch", hide_index=True)
