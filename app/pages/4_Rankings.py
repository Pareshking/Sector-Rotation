from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.metrics import decision_frame
from app.components.theme import inject_theme, page_header, render_decision_cards, render_rank_list, section
from app.data import load_summary

inject_theme()
page_header(
    "Quantitative Ranking",
    "Rankings",
    "Cross-sectional momentum across 1M, 3M, 6M and 12M horizons. Rank orders strength; it does not decide BUY or REDUCE / EXIT.",
)
summary = load_summary()
if summary.empty:
    st.info("No prepared ranking dataset is available.")
    st.stop()

category = st.segmented_control("Universe", ["All", "sector", "thematic"], default="All")
frame = summary if category == "All" else summary[summary.category == category]
frame = decision_frame(frame).sort_values("rank")
only = st.toggle("Decision-grade only", value=True, help="Hide histories that cannot support a decision-grade signal.")
if only:
    frame = frame[frame.decision_eligible]

buy = frame[frame.model_action == "BUY"]
sell = frame[frame.model_action == "REDUCE / EXIT"]

section("BUY")
render_decision_cards(buy, limit=20, empty_text="No BUY signal currently.")

section("REDUCE / EXIT")
render_decision_cards(sell, limit=20, empty_text="No REDUCE / EXIT signal currently.")

section("Ranked decision set")
render_rank_list(frame, limit=50)

with st.expander("Detailed model inputs · audit", expanded=False):
    st.dataframe(frame, width="stretch", hide_index=True)
