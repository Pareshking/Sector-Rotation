from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import ranking_bar
from app.components.theme import inject_theme, page_header, section
from app.data import load_summary

inject_theme()
page_header("Quantitative Ranking", "Rankings", "Composite momentum score across 1M, 3M, 6M and 12M horizons")
summary = load_summary()
if summary.empty:
    st.info("No prepared ranking dataset is available.")
    st.stop()
category = st.segmented_control("Universe", ["All", "sector", "thematic"], default="All")
frame = summary if category == "All" else summary[summary["category"] == category]
section("Momentum ranking")
st.plotly_chart(ranking_bar(frame.head(25)), width="stretch")
section("Rank table")
st.dataframe(frame.sort_values("rank"), width="stretch", hide_index=True)
