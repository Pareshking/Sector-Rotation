from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import CHART_CONFIG, momentum_bar, returns_heatmap
from app.components.metrics import action_counts
from app.components.tables import ranked_table, signal_rows
from app.components.theme import inject_theme, kpi_strip, note, page_header, section, stage_legend
from app.data import load_decisions, load_rs

inject_theme()
page_header(
    "Exposure Universe",
    "Sectors",
    "Sector rotation measured against Nifty 50. Only authoritative decision-grade histories can produce a BUY or a REDUCE / EXIT.",
)

decisions = load_decisions()
frame = decisions[decisions.category == "sector"] if not decisions.empty else decisions
if frame.empty:
    st.info("No sector observations are available.")
    st.stop()

rs = load_rs()
eligible = frame[frame.decision_eligible]
counts = action_counts(frame)
buy = eligible[eligible.model_action == "BUY"]
sell = eligible[eligible.model_action == "REDUCE / EXIT"]

kpi_strip(
    [
        ("Sectors", counts["total"], "in the universe", ""),
        ("Buy", counts["buy"], "full confirmation", "buy"),
        ("Early turn", counts["improving"], "improving, not confirmed", "blue"),
        ("Reduce / exit", counts["reduce"], "exit rule triggered", "red"),
    ]
)

section("Momentum leaderboard", "Composite Z-score, coloured by rotation stage")
stage_legend()
st.plotly_chart(momentum_bar(eligible, limit=22), width="stretch", config=CHART_CONFIG)

section("Return map", "Price return by horizon — the raw evidence under the Z-score")
st.plotly_chart(returns_heatmap(eligible, limit=22), width="stretch", config=CHART_CONFIG)

section("Actionable signals", "BUY and REDUCE / EXIT only")
signals = pd.concat([buy, sell]).sort_values("rank") if len(buy) or len(sell) else buy
if signals.empty:
    note("No sector currently satisfies either the BUY or the REDUCE / EXIT rule.")
else:
    signal_rows(signals, rs=rs)

section("Full sector ranking", "Click any column header to sort")
period = st.segmented_control(
    "Rank by lookback",
    ["Composite", "1M", "3M", "6M", "12M"],
    default="Composite",
    key="sectors_lookback",
)
ranked_table(eligible, rs=rs, sort_by=period or "Composite", key="sectors_table")

unavailable = frame[~frame.decision_eligible]
if not unavailable.empty:
    with st.expander(f"Unavailable sector histories · {len(unavailable)}", expanded=False):
        for row in unavailable.itertuples():
            st.write(f"• {row.exposure} — {getattr(row, 'decision_reason', 'History unavailable.')}")
