from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import CHART_CONFIG, stage_distribution
from app.components.metrics import (
    HELD_ACTIONS,
    action_counts,
    data_health_banner,
    get_metadata,
    health_summary,
    market_state,
)
from app.components.tables import (
    BASES,
    BASIS_RELATIVE,
    action_board,
    audit_frame,
    ranked_table,
)
from app.components.theme import (
    _esc,
    brand_header,
    inject_theme,
    kpi_strip,
    mobile_nav,
    note,
    page_header,
    section,
    stage_legend,
)
from app.data import (
    load_decisions,
    load_index_panel,
    load_portfolio,
    load_rs,
    strategy_config,
)
from src.portfolio.calendar import fill_date

inject_theme()
mobile_nav("Overview")

_summary = load_decisions()
_panel, _benchmark = load_index_panel()
_state = market_state(_panel, _benchmark, _summary)
_health = health_summary()
_metadata_type = get_metadata().get("benchmark_value_type")

_chips: list[tuple[str, str]] = []
if _state.get("level") is not None:
    move = f" ({_state['vs_200d']:+.1%} vs 200D)" if _state.get("vs_200d") is not None else ""
    # Name the series the pipeline actually recorded; never assume TRI.
    label = f"NIFTY 50 {_metadata_type}" if _metadata_type else "NIFTY 50"
    _chips.append((label, f"{_state['level']:,.0f}{move}"))
if _state.get("universe"):
    _chips.append(("Universe", str(_state["universe"])))
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
    "The target portfolio at the latest month-end rebalance and the reason for every line. "
    "It is produced by the same function the backtest runs at every rebalance, so what you "
    "see here is the strategy that was tested.",
)
data_health_banner()

decisions = _summary
live = load_portfolio()
if decisions.empty or live is None:
    st.warning("Prepared data is not available yet. Run the data pipeline first.")
    st.stop()

config = strategy_config()
target = live.target
counts = action_counts(decisions)
fill = fill_date(_panel.index, target.as_of) if not _panel.empty else None
held = decisions[decisions.model_action.isin(HELD_ACTIONS)]
buy = decisions[decisions.model_action == "BUY"]
hold = decisions[decisions.model_action.isin(["HOLD", "TRIM"])]
sell = decisions[decisions.model_action == "SELL"]

kpi_strip(
    [
        ("Decision", f"{target.as_of:%d %b %Y}", f"next rebalance {live.next_rebalance:%d %b %Y}", ""),
        (
            "Holdings",
            f"{len(target.holdings)} of {config.target_holdings_n}",
            f"{target.cash_weight:.0%} in cash",
            "buy" if target.holdings else "amber",
        ),
        ("Buy", counts["buy"], "new entries this rebalance", "buy"),
        ("Sell", counts["sell"], "exits this rebalance", "red"),
    ]
)
execution = (
    f"Orders from this decision execute at the <b>{fill:%d %b %Y}</b> close (the session after the signal)."
    if fill is not None
    else "Orders from this decision execute at the next session's close."
)
note(
    f"{execution} Between rebalances the target does not change; the ranking below updates daily "
    "but is acted on only at the next month end."
)
for line in target.notes:
    note(_esc(line), tone="amber")

section(
    "Target portfolio",
    f"Strategy v{target.config_version} · config {target.config_hash} · decision {target.as_of:%d %b %Y}",
)
action_board(
    [
        ("Buy", "buy", buy, "No new entries at this rebalance."),
        ("Hold", "blue", hold, "Nothing carried over from the previous rebalance."),
        ("Sell", "red", sell, "No exits at this rebalance."),
    ],
    limit=8,
)
if not held.empty:
    lines = "<br>".join(
        f"<b>{_esc(row.exposure)}</b> · {row.model_action} · {row.target_weight:.0%} — {_esc(row.decision_reason)}"
        for row in held.itertuples()
    )
    note(lines)

section("Full ranking", "Click any column header to sort")
period = st.segmented_control(
    "Rank by lookback",
    ["Composite", "1M", "3M", "6M", "12M"],
    default="Composite",
    key="overview_lookback",
    help="Composite is the strategy score: weighted z-scores of the non-overlapping 1M, 3M-1M, "
    "6M-3M and 12M-6M returns, as of the latest session.",
)
basis = st.segmented_control(
    "Measure",
    BASES,
    default=BASIS_RELATIVE,
    key="overview_basis",
    help="Relative strength is exposure return minus Nifty 50 over the same window. Absolute is "
    "what a holder actually earned.",
)
controls = st.columns(2)
only_grade = controls[0].toggle("Decision-grade only", value=True, key="overview_grade")
only_tradeable = controls[1].toggle(
    "Buyable only", value=False, key="overview_tradeable",
    help="Keep only exposures with a mapped ETF or index fund that had a price on the decision date.",
)
eligible = decisions[decisions.decision_eligible]
table_frame = eligible if only_grade else decisions
if only_tradeable and "tradeable" in table_frame.columns:
    table_frame = table_frame[table_frame.tradeable]
ranked_table(
    table_frame, rs=load_rs(), sort_by=period or "Composite",
    basis=basis or BASIS_RELATIVE, key="overview_table",
)

section("How a decision is reached")
hurdle = (
    f"its own 12-month return beats cash ({config.risk_free_rate_annual:.1%})"
    if config.absolute_momentum_filter == "dual_momentum_cash_hurdle"
    else "no absolute-momentum hurdle"
)
note(
    f"At each month-end close every exposure with a full 12-month history is scored on four "
    "non-overlapping return segments — the latest month, months 2–3, 4–6 and 7–12 — each "
    "z-scored across the universe and weighted equally. Buyable exposures are ranked by that "
    f"score. A holding is kept while its rank is ≤ <b>{config.retention_buffer_m}</b> and "
    f"{hurdle}; an empty slot is filled only from ranks ≤ <b>{config.target_holdings_n}</b>, and "
    "a top name that fails the hurdle leaves its slot in cash. Each slot is "
    f"1/{config.target_holdings_n} of the book. Trades fill at the next session's close and the "
    f"backtest charges {config.cost_bps_per_side:g} bps per side.<br>"
    "The rotation stage (Leading, Weakening, Lagging, Improving) describes the RS line against its "
    "own 52-week average. It is shown for context and decides nothing."
)

section("Rotation stage", f"Where the {len(eligible)} decision-grade exposures sit · display only")
stage_legend()
st.plotly_chart(stage_distribution(eligible), width="stretch", config=CHART_CONFIG)

unavailable = decisions[~decisions.decision_eligible]
if not unavailable.empty:
    with st.expander(f"Outside the decision set · {len(unavailable)}", expanded=False):
        st.caption(
            "Not replaced with synthetic sector proxies. These stay outside the portfolio "
            "until an authoritative 12-month history exists."
        )
        for row in unavailable.itertuples():
            st.write(f"• {row.exposure} — {getattr(row, 'decision_reason', 'History unavailable.')}")

with st.expander("Model inputs · audit", expanded=False):
    audit_frame(decisions, key="overview_audit")

st.caption(
    "A quantitative decision aid, not advice. Verify the underlying ETF, liquidity, tracking "
    "quality and implementation before placing an order."
)
