from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import rs_heatmap
from app.components.metrics import decision_frame
from app.components.theme import inject_theme, page_header, section
from app.data import load_summary

inject_theme()
page_header("Exposure Universe", "Themes", "Thematic baskets ranked by relative momentum and separated from proxy-only histories.")
summary = load_summary()
frame = summary[summary["category"] == "thematic"].sort_values("rank") if not summary.empty else summary
if frame.empty:
    st.info("No thematic observations are available.")
    st.stop()

frame = decision_frame(frame)
proxy_count = int((frame["model_action"] == "PROXY ONLY").sum())
if proxy_count:
    st.markdown(f'<div class="sr-callout">{proxy_count} thematic histories are benchmark proxies. They are visible for coverage, not treated as decision-grade signals.</div>', unsafe_allow_html=True)

section("Theme momentum heatmap")
st.plotly_chart(rs_heatmap(frame, limit=len(frame)), width="stretch", config={"displaylogo": False, "responsive": True})

section("Theme leaderboard")
cols = [c for c in ["rank", "exposure", "model_action", "stage", "momentum_z", "rs_ratio", "rs_momentum", "return_1M", "return_3M", "data_source"] if c in frame]
st.dataframe(frame[cols], width="stretch", hide_index=True)
