from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.metrics import data_health_banner, decision_frame, get_metadata, metric_row
from app.components.theme import inject_theme, page_header, render_decision_cards, render_rank_list, section
from app.data import load_summary

inject_theme()
page_header(
    "India Sector Rotation",
    "Decision Dashboard",
    "A clean, decision-first view of sector and theme rotation. BUY and REDUCE / EXIT are earned by the model conditions — not by rank alone.",
)
metadata = get_metadata()
data_health_banner(metadata)
summary = load_summary()
if summary.empty:
    st.warning("Prepared data is not available yet. Run the data pipeline first.")
    st.stop()

metric_row(summary)
decisions = decision_frame(summary).sort_values("rank")
buy = decisions[decisions.model_action == "BUY"].sort_values("rank")
sell = decisions[decisions.model_action == "REDUCE / EXIT"].sort_values("rank")
watch = decisions[decisions.model_action.isin(["WATCH / IMPROVING", "WATCH"]) & decisions.decision_eligible].sort_values("rank")
unavailable = decisions[~decisions.decision_eligible].sort_values("rank")

section("Decision rule")
st.markdown(
    "**BUY** = Leading stage + RS ratio > 1 + positive RS velocity + positive momentum Z. "
    "**REDUCE / EXIT** = Weakening or Lagging + RS ratio < 1 + negative RS velocity. "
    "Rank is a strength ordering only; it is never a BUY/SELL gate."
)

section("BUY")
render_decision_cards(
    buy,
    limit=20,
    empty_text="No exposure currently satisfies the complete BUY rule.",
)

section("REDUCE / EXIT")
render_decision_cards(
    sell,
    limit=20,
    empty_text="No exposure currently satisfies the REDUCE / EXIT rule.",
)

section("WATCH")
render_decision_cards(
    watch,
    limit=12,
    empty_text="No decision-grade watchlist entries.",
)

section("Decision-grade ranking")
render_rank_list(decisions[decisions.decision_eligible].sort_values("rank"), limit=20)

if not unavailable.empty:
    section("Unavailable for decision")
    st.caption(
        "These exposures are not replaced with synthetic sector proxies. They remain outside the decision set until an authoritative history is available."
    )
    for r in unavailable.itertuples():
        st.write(f"• {r.exposure} — {getattr(r, 'decision_reason', 'Authoritative history unavailable.')}")

with st.expander("Detailed model inputs · audit", expanded=False):
    st.dataframe(decisions, width="stretch", hide_index=True)

st.caption(
    "The dashboard is a quantitative decision aid. Verify the underlying ETF, liquidity, tracking quality and implementation before placing an order."
)
