from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import CHART_CONFIG, rrg_scatter
from app.components.navigation import mobile_nav
from app.components.tables import audit_frame
from app.components.theme import inject_theme, note, page_header, section, stage_legend
from app.data import load_decisions

inject_theme()
mobile_nav("Rankings")
page_header(
    "The whole universe",
    "Rankings",
    "Every sector and theme on the strategy's own score, as of the latest session. The portfolio "
    "acts on these ranks only at month end.",
)

decisions = load_decisions()
if decisions.empty:
    st.info("No prepared ranking dataset is available.")
    st.stop()

counts = decisions["category"].value_counts()
universes = {
    f"All ({len(decisions)})": None,
    f"Sectors ({int(counts.get('sector', 0))})": "sector",
    f"Themes ({int(counts.get('thematic', 0))})": "thematic",
}
controls = st.columns([1.6, 1.2, 1.2])
picked = controls[0].segmented_control("Universe", list(universes), default=list(universes)[0], key="rank_universe")
basis = controls[1].segmented_control(
    "Returns", ["Absolute", "vs Nifty 50"], default="Absolute", key="rank_basis",
    help="Absolute is what a holder earned; vs Nifty 50 subtracts the benchmark over the same window.",
)
only_buyable = controls[2].toggle(
    "Buyable only", value=False, key="rank_buyable",
    help="Keep only exposures with a mapped ETF or index fund that had incepted by the latest decision date.",
)
search = st.text_input("Search", placeholder="e.g. pharma, defence, bank", label_visibility="collapsed")

frame = decisions
category = universes.get(picked or list(universes)[0])
if category:
    frame = frame[frame["category"] == category]
if only_buyable and "tradeable" in frame:
    frame = frame[frame["tradeable"]]
if search.strip():
    frame = frame[frame["exposure"].str.contains(search.strip(), case=False, na=False)]

prefix = "relative_" if basis == "vs Nifty 50" else "return_"
suffix = " vs N50" if basis == "vs Nifty 50" else ""
table = pd.DataFrame(
    {
        "Rank": pd.to_numeric(frame["rank"], errors="coerce").to_numpy(),
        "Exposure": frame["exposure"].to_numpy(),
        "Category": frame["category"].map({"sector": "Sector", "thematic": "Theme"}).to_numpy(),
        **{f"{p}{suffix}": pd.to_numeric(frame[f"{prefix}{p}"], errors="coerce").to_numpy() for p in ("1M", "3M", "6M", "12M")},
        "Score": pd.to_numeric(frame["momentum_z"], errors="coerce").to_numpy(),
        "Portfolio": frame["model_action"].to_numpy(),
        "Stage (display only)": frame["stage"].to_numpy(),
    }
).sort_values("Rank", na_position="last", kind="mergesort")

section(f"{len(table)} exposures", "Click any column header to re-sort")
percent = {
    f"{p}{suffix}": st.column_config.NumberColumn(format="percent", width="small") for p in ("1M", "3M", "6M", "12M")
}
st.dataframe(
    table,
    hide_index=True,
    width="stretch",
    height=min(56 + 35 * len(table), 720),
    column_config={
        "Rank": st.column_config.NumberColumn(
            format="%d", width="small",
            help="Strategy score rank across the whole universe at the latest session (provisional "
            "between rebalances; the portfolio ranks only buyable exposures, at month end).",
        ),
        "Exposure": st.column_config.TextColumn(width="medium", pinned=True),
        **percent,
        "Score": st.column_config.NumberColumn(
            format="%+.2f", width="small",
            help="Weighted z-scores of the non-overlapping 1M, 3M-1M, 6M-3M and 12M-6M returns. "
            "0 is the universe average, not a zero return.",
        ),
        "Portfolio": st.column_config.TextColumn(width="small", help="What the target portfolio does with it"),
        "Stage (display only)": st.column_config.TextColumn(
            width="small",
            help="RRG stage of the RS line against its own 52-week average. Context only: it decides nothing.",
        ),
    },
)
note(
    "<b>Rank orders the score; it is not an instruction.</b> The portfolio holds the top "
    "buyable names at month end, keeps a holding while it stays inside the retention buffer, and "
    "only while its 12-month return beats cash — see the Portfolio page."
)

with st.expander("RRG Quadrant View (Display Context)", expanded=False):
    stage_legend()
    st.plotly_chart(rrg_scatter(frame), width="stretch", config=CHART_CONFIG)
    st.caption(
        "Where each RS line sits against its own 52-week average (x) and how fast that is changing "
        "(y). Shown for context; the strategy's decisions do not use it."
    )

with st.expander("Every model input", expanded=False):
    audit_frame(frame, key="rankings_audit")
