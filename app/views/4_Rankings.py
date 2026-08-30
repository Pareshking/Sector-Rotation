from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import CHART_CONFIG, returns_heatmap
from app.components.tables import BASES, BASIS_RELATIVE, audit_frame, ranked_table
from app.components.theme import mobile_nav, inject_theme, kpi_strip, note, page_header, section
from app.data import load_decisions, load_rs

inject_theme()
mobile_nav("Rankings")
page_header(
    "Quantitative Ranking",
    "Screener",
    "The whole universe in one sortable table. Filter it, pick the lookback that matters to you, "
    "then sort on any column.",
)

decisions = load_decisions()
if decisions.empty:
    st.info("No prepared ranking dataset is available.")
    st.stop()

rs = load_rs()

section("Filters")
row1 = st.columns([1.1, 1.1, 1.3])
categories = sorted(decisions.category.dropna().unique().tolist())
actions = ["BUY", "WATCH / IMPROVING", "WATCH", "REDUCE / EXIT", "DATA UNAVAILABLE"]
stages = ["Leading", "Weakening", "Lagging", "Improving"]

picked_categories = row1[0].multiselect("Universe", categories, default=categories)
picked_actions = row1[1].multiselect(
    "Action", actions, default=[a for a in actions if a != "DATA UNAVAILABLE"]
)
search = row1[2].text_input("Search exposure", placeholder="e.g. pharma, defence, bank")

row2 = st.columns([1.3, 1.4, 1.1])
picked_stages = row2[0].multiselect("Stage", stages, default=stages)
period = row2[1].segmented_control(
    "Rank by lookback",
    ["Composite", "1M", "3M", "6M", "12M"],
    default="Composite",
    key="screener_lookback",
    help="Composite blends the cross-sectional Z-scores of all four horizons.",
)
row3 = st.columns([1.3, 1.4, 1.1])
basis = row3[0].segmented_control(
    "Measure",
    BASES,
    default=BASIS_RELATIVE,
    key="screener_basis",
    help="Relative strength is the model's own measure: exposure return minus Nifty 50 over the "
    "same window. Absolute is what a holder actually earned.",
)
only_grade = row2[2].toggle("Decision-grade only", value=True, key="screener_grade")
only_tradeable = row3[2].toggle(
    "Tradeable only", value=False, key="screener_tradeable",
    help="Keep only exposures with a listed ETF that traded at the last NSE snapshot.",
)

frame = decisions[decisions.category.isin(picked_categories)]
if picked_actions:
    frame = frame[frame.model_action.isin(picked_actions)]
if picked_stages:
    frame = frame[frame.stage.isin(picked_stages)]
if only_grade:
    frame = frame[frame.decision_eligible]
if only_tradeable and "tradeable" in frame.columns:
    frame = frame[frame.tradeable]
if search.strip():
    frame = frame[frame.exposure.str.contains(search.strip(), case=False, na=False)]

if frame.empty:
    note("No exposure matches every filter. Widen the action or stage selection.")
    st.stop()

kpi_strip(
    [
        ("Matching", len(frame), f"of {len(decisions)} exposures", ""),
        ("Buy", int((frame.model_action == "BUY").sum()), "in this selection", "buy"),
        (
            "Reduce / exit",
            int((frame.model_action == "REDUCE / EXIT").sum()),
            "in this selection",
            "red",
        ),
        (
            "Tradeable",
            int(frame.tradeable.sum()) if "tradeable" in frame else "—",
            "have a listed ETF",
            "",
        ),
        (
            "Median 3M",
            f"{frame.return_3M.median() * 100:.1f}%" if "return_3M" in frame else "—",
            "selection median",
            "",
        ),
    ]
)

measure = "composite momentum" if (period or "Composite") == "Composite" else f"{period} {basis or BASIS_RELATIVE}"
section("Ranked universe", f"{len(frame)} exposures · sorted by {measure}")
ranked_table(
    frame, rs=rs, sort_by=period or "Composite",
    basis=basis or BASIS_RELATIVE, height=620, key="screener_table",
)

st.download_button(
    "Download this selection (CSV)",
    frame.to_csv(index=False).encode("utf-8"),
    file_name="sector_rotation_screen.csv",
    mime="text/csv",
)

section("Return map", "Selection returns across every horizon")
st.plotly_chart(returns_heatmap(frame, limit=25), width="stretch", config=CHART_CONFIG)

with st.expander("Model inputs · audit", expanded=False):
    audit_frame(frame, key="screener_audit")
