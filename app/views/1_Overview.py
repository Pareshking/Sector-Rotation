from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import CHART_CONFIG, stage_distribution
from app.components.metrics import (
    action_counts,
    data_health_banner,
    health_summary,
    market_state,
)
from app.components.tables import BASES, BASIS_RELATIVE, action_board, audit_frame, ranked_table
from app.components.theme import (
    mobile_nav,
    brand_header,
    inject_theme,
    kpi_strip,
    note,
    page_header,
    section,
    stage_legend,
)
from app.data import load_decisions, load_index_panel, load_rs

inject_theme()
mobile_nav("Overview")

_summary = load_decisions()
_panel, _benchmark = load_index_panel()
_state = market_state(_panel, _benchmark, _summary)
_health = health_summary()

_chips: list[tuple[str, str]] = []
if _state.get("level") is not None:
    move = f" ({_state['vs_200d']:+.1%} vs 200D)" if _state.get("vs_200d") is not None else ""
    # The benchmark is the total-return series, so its level is not the price
    # index anyone sees quoted. Say which one this is.
    _chips.append(("NIFTY 50 TRI", f"{_state['level']:,.0f}{move}"))
if _state.get("universe"):
    _chips.append(("Universe", str(_state["universe"])))
if _state.get("breadth") is not None:
    _chips.append(("Leading", f"{_state['leading']} ({_state['breadth']:.0%})"))
if _state.get("as_of") is not None:
    _chips.append(("", f"{_state['as_of']:%d %b %Y}"))

brand_header(
    "Dual Momentum",
    regime=str(_state.get("regime", "")),
    stats=_chips,
    when=f"Updated {_health.get('age', '')}" if _health else "",
)
page_header(
    "India Sector Rotation",
    "Decision Dashboard",
    "What the model says to do today, and the evidence behind it. BUY and REDUCE / EXIT are "
    "earned by the signal conditions — never by rank alone.",
)
data_health_banner()

decisions = _summary
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
buyable = int(buy["tradeable"].sum()) if "tradeable" in buy.columns else len(buy)
if len(buy) and buyable < len(buy):
    note(
        f"<b>{len(buy) - buyable} of {len(buy)} BUY signals have no ETF or index fund.</b> "
        "They are research, not positions. Use the tradeable filter below to see only what you "
        "can actually put money into.",
        tone="amber",
    )

section("Universe breadth", f"Where the {len(eligible)} decision-grade exposures sit in the rotation cycle")
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
basis = st.segmented_control(
    "Measure",
    BASES,
    default=BASIS_RELATIVE,
    key="overview_basis",
    help="Relative strength is the model's own measure: exposure return minus Nifty 50 over the "
    "same window. Absolute is what a holder actually earned.",
)
controls = st.columns(2)
only_grade = controls[0].toggle("Decision-grade only", value=True, key="overview_grade")
only_tradeable = controls[1].toggle(
    "Tradeable only", value=False, key="overview_tradeable",
    help="Keep only exposures with a listed ETF that traded at the last NSE snapshot.",
)
table_frame = eligible if only_grade else decisions
if only_tradeable and "tradeable" in table_frame.columns:
    table_frame = table_frame[table_frame.tradeable]
ranked_table(
    table_frame, rs=rs, sort_by=period or "Composite",
    basis=basis or BASIS_RELATIVE, key="overview_table",
)

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
    audit_frame(decisions, key="overview_audit")

st.caption(
    "A quantitative decision aid, not advice. Verify the underlying ETF, liquidity, tracking "
    "quality and implementation before placing an order."
)
