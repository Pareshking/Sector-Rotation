from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import CHART_CONFIG, stage_distribution
from app.components.metrics import action_counts, data_health_banner
from app.components.tables import action_board, ranked_table
from app.components.theme import (
    inject_theme,
    kpi_strip,
    note,
    page_header,
    section,
    stage_legend,
)
from app.data import load_decisions, load_rs

inject_theme()
page_header(
    "India Sector Rotation",
    "Decision Dashboard",
    "What the model says to do today, and the evidence behind it. BUY and REDUCE / EXIT are "
    "earned by the signal conditions — never by rank alone.",
)
data_health_banner()

decisions = load_decisions()
if decisions.empty:
    st.warning("Prepared data is not available yet. Run the data pipeline first.")
    st.stop()

rs = load_rs()
counts = action_counts(decisions)
eligible = decisions[decisions.decision_eligible]
buy = eligible[eligible.model_action == "BUY"]
sell = eligible[eligible.model_action == "REDUCE / EXIT"]
improving = eligible[eligible.model_action == "WATCH / IMPROVING"]
rolling_over = eligible[eligible.watch_kind == "Rolling over"]

kpi_strip(
    [
        ("Decision-grade", counts["eligible"], f'of {counts["total"]} exposures', ""),
        ("Buy", counts["buy"], "full confirmation", "buy"),
        ("Early turn", counts["improving"], "improving, not confirmed", "blue"),
        ("Reduce / exit", counts["reduce"], "exit rule triggered", "red"),
    ]
)

section("Universe breadth", "Where the 43 exposures sit in the rotation cycle")
stage_legend()
st.plotly_chart(stage_distribution(eligible), width="stretch", config=CHART_CONFIG)

section("Action board", "Ranked within each bucket by composite momentum")
action_board(
    [
        ("Buy", "buy", buy, "No exposure satisfies the complete BUY rule."),
        ("Early turn · watch", "blue", improving, "Nothing has turned up yet."),
        ("Reduce / exit", "red", sell, "No exposure satisfies the REDUCE / EXIT rule."),
    ],
    limit=8,
)

if not rolling_over.empty:
    names = ", ".join(rolling_over.head(6).exposure.tolist())
    note(
        f"<b>{len(rolling_over)} leaders are rolling over.</b> Still above the benchmark on RS "
        f"ratio, but RS velocity has turned negative — leadership is fading before the exit rule "
        f"triggers: {names}.",
        tone="amber",
    )

section("Full ranking", "Click any column header to sort")
period = st.segmented_control(
    "Rank by lookback",
    ["Composite", "1M", "3M", "6M", "12M"],
    default="Composite",
    key="overview_lookback",
    help="Composite is the cross-sectional Z-score blended across all four horizons.",
)
only_grade = st.toggle("Decision-grade only", value=True, key="overview_grade")
table_frame = eligible if only_grade else decisions
ranked_table(table_frame, rs=rs, sort_by=period or "Composite", key="overview_table")

section("How a decision is reached")
note(
    "<b>BUY</b> = Leading stage + RS ratio &gt; 1 + positive RS velocity + positive momentum Z.<br>"
    "<b>REDUCE / EXIT</b> = Weakening or Lagging + RS ratio &lt; 1 + negative RS velocity.<br>"
    "<b>Early turn</b> = Improving stage with RS velocity newly positive — below the benchmark, "
    "but no longer falling behind.<br>"
    "Rank orders strength; it is never a BUY or SELL gate."
)

unavailable = decisions[~decisions.decision_eligible]
if not unavailable.empty:
    with st.expander(f"Outside the decision set · {len(unavailable)}", expanded=False):
        st.caption(
            "Not replaced with synthetic sector proxies. These stay outside the decision set "
            "until an authoritative history exists."
        )
        for row in unavailable.itertuples():
            st.write(f"• {row.exposure} — {getattr(row, 'decision_reason', 'History unavailable.')}")

with st.expander("Model inputs · audit", expanded=False):
    st.dataframe(decisions, width="stretch", hide_index=True)

st.caption(
    "A quantitative decision aid, not advice. Verify the underlying ETF, liquidity, tracking "
    "quality and implementation before placing an order."
)
