from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import CHART_CONFIG, rrg_scatter  # noqa: E402
from app.components.metrics import HELD_ACTIONS  # noqa: E402
from app.components.tables import audit_frame, show_table, tinted  # noqa: E402
from app.components.theme import (  # noqa: E402
    STAGE_TONE,
    chip,
    html_block,
    note,
    page_header,
    section,
    stage_legend,
)
from app.data import load_decisions  # noqa: E402

page_header(
    "The whole universe",
    "Rankings",
    "Every sector and theme on the strategy's own score at the latest session. The portfolio acts on these "
    "ranks only at month end.",
)

decisions = load_decisions()
if decisions.empty:
    note("No prepared ranking dataset is available.", tone="warn")
    st.stop()

counts = decisions["category"].value_counts()
universes = {
    f"All ({len(decisions)})": None,
    f"Sectors ({int(counts.get('sector', 0))})": "sector",
    f"Themes ({int(counts.get('thematic', 0))})": "thematic",
}
with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
    picked = st.segmented_control("Universe", list(universes), default=list(universes)[0], key="rank_universe")
    basis = st.segmented_control(
        "Returns", ["Absolute", "vs Nifty 50"], default="Absolute", key="rank_basis",
        help="Absolute is what a holder earned; vs Nifty 50 subtracts the benchmark over the same window.",
    )
    only_buyable = st.toggle(
        "Buyable only", value=False, key="rank_buyable",
        help="Only exposures with a mapped ETF or index fund that had incepted by the latest decision date.",
    )
search = st.text_input("Search exposures", placeholder="Search: pharma, defence, bank…", label_visibility="collapsed")

frame = decisions
category = universes.get(picked or list(universes)[0])
if category:
    frame = frame[frame["category"] == category]
if only_buyable and "tradeable" in frame:
    frame = frame[frame["tradeable"]]
if search.strip():
    frame = frame[frame["exposure"].str.contains(search.strip(), case=False, na=False, regex=False)]

# Quadrant counts and what the portfolio holds, as one glanceable line.
held = frame[frame["model_action"].isin(HELD_ACTIONS)]["exposure"].tolist()
stages = frame["stage"].value_counts()
html_block(
    '<div class="ds-legend">'
    + "".join(chip(f"{stage} {int(stages.get(stage, 0))}", tone) for stage, tone in STAGE_TONE.items())
    + (f"<span>Held: <b>{', '.join(held)}</b></span>" if held else "<span>No holding in this view</span>")
    + "</div>"
)

absolute = basis != "vs Nifty 50"
prefix, suffix = ("return_", "") if absolute else ("relative_", " vs N50")
periods = [f"{p}{suffix}" for p in ("1M", "3M", "6M", "12M")]
table = pd.DataFrame(
    {
        "Rank": pd.to_numeric(frame["rank"], errors="coerce").to_numpy(),
        "Exposure": frame["exposure"].to_numpy(),
        "Category": frame["category"].map({"sector": "Sector", "thematic": "Theme"}).to_numpy(),
        **{
            label: pd.to_numeric(frame[f"{prefix}{p}"], errors="coerce").to_numpy()
            for label, p in zip(periods, ("1M", "3M", "6M", "12M"))
        },
        "Score": pd.to_numeric(frame["momentum_z"], errors="coerce").to_numpy(),
        "Portfolio": frame["model_action"].to_numpy(),
        "Quadrant (display only)": frame["stage"].to_numpy(),
    }
).sort_values("Rank", na_position="last", kind="mergesort").reset_index(drop=True)

section(f"{len(table)} exposures", "Sorted by score · click a header to re-sort · the header stays in view while you scroll")
show_table(
    tinted(table, periods, cap=0.30 if absolute else 0.20),
    hide_index=True,
    width="stretch",
    height=min(40 + 35 * len(table), 760),
    column_config={
        "Rank": st.column_config.NumberColumn(
            format="%d", width="small", pinned=True,
            help="Score rank across the whole universe at the latest session (provisional between rebalances; "
            "the portfolio ranks only buyable exposures, at month end).",
        ),
        "Exposure": st.column_config.TextColumn(width="medium", pinned=True),
        "Category": st.column_config.TextColumn(width="small"),
        **{p: st.column_config.NumberColumn(format="percent", width="small") for p in periods},
        "Score": st.column_config.ProgressColumn(
            format="%+.2f", width="small", min_value=float(min(table["Score"].min(), -1.0)),
            max_value=float(max(table["Score"].max(), 1.0)),
            help="Weighted z-scores of the non-overlapping 1M, 3M-1M, 6M-3M and 12M-6M log returns. "
            "0 is the universe average, not a zero return.",
        ),
        "Portfolio": st.column_config.TextColumn(width="small", help="What the target portfolio does with it"),
        "Quadrant (display only)": st.column_config.TextColumn(
            width="small", help="RRG quadrant of the RS line against its own 52-week average. It decides nothing.",
        ),
    },
)
note(
    "<b>Rank orders the score; it is not an instruction.</b> The portfolio holds the top buyable names at "
    "month end, keeps a holding while it stays inside the retention buffer, and only while its 12-month "
    "return beats cash. See the Portfolio page."
)

with st.expander("RRG Quadrant View (Display Context)", expanded=False):
    stage_legend()
    st.plotly_chart(rrg_scatter(frame), width="stretch", config=CHART_CONFIG)
    st.caption(
        "Where each RS line sits against its own 52-week average (x) and how fast that is changing (y). "
        "Hover for a crosshair. Shown for context; the strategy's decisions do not use it."
    )

with st.expander("Every model input", expanded=False):
    audit_frame(frame, key="rankings_audit")
