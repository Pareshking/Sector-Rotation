from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import CHART_CONFIG, momentum_bar, returns_heatmap
from app.components.metrics import HELD_ACTIONS, action_counts
from app.components.tables import BASES, BASIS_RELATIVE, ranked_table, signal_rows
from app.components.theme import mobile_nav, inject_theme, kpi_strip, note, page_header, section, stage_legend
from app.data import load_decisions, load_rs

inject_theme()
mobile_nav("Sectors")
page_header(
    "Exposure Universe",
    "Sectors",
    "Sector rotation measured against Nifty 50. Actions are the target portfolio's; only authoritative decision-grade histories can be held.",
)

decisions = load_decisions()
frame = decisions[decisions.category == "sector"] if not decisions.empty else decisions
if frame.empty:
    st.info("No sector observations are available.")
    st.stop()

rs = load_rs()
eligible = frame[frame.decision_eligible]
counts = action_counts(frame)
held = eligible[eligible.model_action.isin(HELD_ACTIONS)]
sell = eligible[eligible.model_action == "SELL"]

kpi_strip(
    [
        ("Sectors", counts["total"], "in the universe", ""),
        ("In the portfolio", counts["held"], "held at the latest rebalance", "buy"),
        ("Buy", counts["buy"], "new entries this rebalance", "buy"),
        ("Sell", counts["sell"], "exits this rebalance", "red"),
    ]
)

section("Momentum leaderboard", "Strategy score · 0 is the universe average, not zero return")
stage_legend()
st.plotly_chart(momentum_bar(eligible, limit=22), width="stretch", config=CHART_CONFIG)

section("Return map", "Price return by horizon — the raw evidence under the Z-score")
st.plotly_chart(returns_heatmap(eligible, limit=22), width="stretch", config=CHART_CONFIG)

section("In the target portfolio", "Held, bought or sold at the latest rebalance")
signals = pd.concat([held, sell]).sort_values("rank") if len(held) or len(sell) else held
if signals.empty:
    note("The target portfolio holds no sector and sold none at the latest rebalance.")
else:
    signal_rows(signals, rs=rs)

section("Full sector ranking", "Click any column header to sort")
period = st.segmented_control(
    "Rank by lookback",
    ["Composite", "1M", "3M", "6M", "12M"],
    default="Composite",
    key="sectors_lookback",
)
basis = st.segmented_control(
    "Measure",
    BASES,
    default=BASIS_RELATIVE,
    key="sectors_basis",
    help="Relative strength is the model's own measure: exposure return minus Nifty 50 over the "
    "same window. Absolute is what a holder actually earned.",
)
ranked_table(
    eligible, rs=rs, sort_by=period or "Composite",
    basis=basis or BASIS_RELATIVE, key="sectors_table",
)

unavailable = frame[~frame.decision_eligible]
if not unavailable.empty:
    with st.expander(f"Unavailable sector histories · {len(unavailable)}", expanded=False):
        for row in unavailable.itertuples():
            st.write(f"• {row.exposure} — {getattr(row, 'decision_reason', 'History unavailable.')}")
