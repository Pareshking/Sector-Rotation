from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import ranking_bar
from app.components.metrics import decision_frame
from app.components.theme import inject_theme, page_header, section
from app.data import load_summary

inject_theme()
page_header("Quantitative Ranking", "Rankings", "Composite momentum across 1M, 3M, 6M and 12M horizons, with the decision boundary made explicit.")
summary = load_summary()
if summary.empty:
    st.info("No prepared ranking dataset is available.")
    st.stop()

category = st.segmented_control("Universe", ["All", "sector", "thematic"], default="All")
frame = summary if category == "All" else summary[summary["category"] == category]
frame = decision_frame(frame).sort_values("rank")

only_decision_grade = st.toggle("Decision-grade only", value=True, help="Hide benchmark-proxy histories from the actionable ranking.")
if only_decision_grade:
    frame = frame[frame["decision_eligible"]]

section("Momentum ranking")
st.plotly_chart(ranking_bar(frame, limit=min(15, len(frame))), width="stretch", config={"displaylogo": False, "responsive": True})

section("Rank table")
cols = [c for c in ["rank", "exposure", "model_action", "stage", "momentum_z", "rs_ratio", "rs_momentum", "return_1M", "return_3M", "return_6M", "return_12M", "data_source"] if c in frame]
st.dataframe(frame[cols], width="stretch", hide_index=True)
