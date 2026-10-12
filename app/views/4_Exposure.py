from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import (  # noqa: E402
    CHART_CONFIG,
    drawdown_chart,
    etf_comparison,
    rs_trajectory,
    trailing_volatility,
)
from app.components.metrics import HELD_ACTIONS, source_label  # noqa: E402
from app.components.tables import show_table  # noqa: E402
from app.components.theme import (  # noqa: E402
    STAGE_TONE,
    _esc,
    action_chip,
    chip,
    fmt_num,
    fmt_pct,
    fmt_rupees,
    html_block,
    kpi_grid,
    note,
    page_header,
    section,
    tone_of,
)
from app.data import (  # noqa: E402
    best_vehicle,
    load_decisions,
    load_etf_prices,
    load_index_panel,
    load_portfolio,
    load_rs,
    strategy_config,
    vehicle_frame,
    vehicle_tracking,
)
from src.portfolio.vehicles import PARTICIPATION_LIMIT, VehicleChoice, days_to_build  # noqa: E402

page_header(
    "Deep dive",
    "Exposure",
    "One sector or theme: why the strategy treats it as it does, how it has behaved, and which fund to buy it with.",
)

decisions = load_decisions()
if decisions.empty:
    note("No prepared model data is available.", tone="warn")
    st.stop()

panel, _ = load_index_panel()
config = strategy_config()
live = load_portfolio()

# Held names first, then rank order: the exposure a reader most likely wants is the default.
ordered = pd.concat([decisions[decisions["model_action"].isin(HELD_ACTIONS)],
                     decisions[~decisions["model_action"].isin(HELD_ACTIONS)]])
options = ordered["exposure"].tolist()
exposure = st.selectbox(
    "Exposure", options, key="detail_exposure",
    help="Type to search. Held exposures are listed first, then every other one in rank order.",
)
signal = decisions[decisions["exposure"] == exposure].iloc[0]
exposure_id = str(signal.get("exposure_id", ""))


def _rank(value: object) -> str:
    rank = pd.to_numeric(value, errors="coerce")
    return f"#{int(rank)}" if pd.notna(rank) else "—"


# --------------------------------------------------------------------------- #
# Decision card
# --------------------------------------------------------------------------- #
action = str(signal.get("model_action", "NOT HELD"))
stage = str(signal.get("stage", "") or "")
category = {"sector": "Sector", "thematic": "Theme"}.get(str(signal.get("category")), "")
source = " · ".join(
    b for b in (source_label(signal.get("data_source")), f"{signal.get('value_type', '')} series".strip(),
                str(signal.get("resolved_official_index_name", "") or "")) if b and b != "series"
)
chips = [action_chip(action, large=True), chip(f"Decision rank {_rank(signal.get('decision_rank'))}"),
         chip(f"Target {fmt_pct(signal.get('target_weight', 0.0), 0)}"),
         chip(f"Quadrant · {stage or '—'}", STAGE_TONE.get(stage, ""))]
if category:
    chips.append(chip(category))
html_block(
    f'<div class="ds-card ds-card-active"><div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center">'
    f'{"".join(chips)}</div><div class="ds-log-d">{_esc(signal.get("analysis_note", ""))}</div>'
    f'<div class="ds-card-s">{_esc(source)}</div></div>'
)
if signal.get("shares_index_with"):
    note(f"This exposure resolves to the same index as <b>{_esc(signal.get('shares_index_with'))}</b>. Holding both is "
         "one bet, not two.", tone="warn")

kpi_grid(
    [
        ("Score", fmt_num(signal.get("momentum_z")), "z-score composite, latest session", tone_of(signal.get("momentum_z"))),
        ("1M", fmt_pct(signal.get("return_1M")), "index return", tone_of(signal.get("return_1M"))),
        ("3M", fmt_pct(signal.get("return_3M")), "", tone_of(signal.get("return_3M"))),
        ("6M", fmt_pct(signal.get("return_6M")), "", tone_of(signal.get("return_6M"))),
        ("12M", fmt_pct(signal.get("return_12M")), "the hurdle compares this", tone_of(signal.get("return_12M"))),
    ]
)

# --------------------------------------------------------------------------- #
# Behaviour: relative strength, volatility, drawdown, durability
# --------------------------------------------------------------------------- #
section("How it has behaved")
level = panel[exposure_id].dropna() if exposure_id in panel.columns else pd.Series(dtype=float)
rs = load_rs()
tab_rs, tab_vol, tab_dd, tab_dur = st.tabs(["Relative strength", "Volatility", "Drawdown", "Durability"])
with tab_rs:
    kpi_grid(
        [
            ("RS ratio", fmt_num(signal.get("rs_ratio"), 3), "1.000 = its own 52-week average", ""),
            ("RS velocity", fmt_num(signal.get("rs_momentum"), 1), "13-week change", tone_of(signal.get("rs_momentum"))),
            ("12M vs Nifty 50", fmt_pct(signal.get("relative_12M")), "return minus benchmark", tone_of(signal.get("relative_12M"))),
        ]
    )
    if exposure_id in getattr(rs, "columns", []):
        st.plotly_chart(rs_trajectory(rs, exposure_id), width="stretch", config=CHART_CONFIG)
        st.caption("Mansfield relative strength against Nifty 50, weekly, over three years. Above zero the price "
                   "relative sits above its own one-year average.")
    else:
        note("No relative-strength history for this exposure.")
with tab_vol:
    kpi_grid(
        [
            ("Volatility 3Y", fmt_pct(signal.get("volatility_3y")), "annualised", ""),
            ("Beta", fmt_num(signal.get("beta")), f"R² {fmt_num(signal.get('r_squared'))}", ""),
            ("Sharpe 3Y", fmt_num(signal.get("sharpe_3y")), "risk-free 6.5%", ""),
        ]
    )
    st.plotly_chart(trailing_volatility(level), width="stretch", config=CHART_CONFIG)
with tab_dd:
    kpi_grid(
        [
            ("Max drawdown", fmt_pct(signal.get("max_drawdown")), "worst fall over five years", "neg"),
            ("Off its high", fmt_pct(signal.get("drawdown_from_high")), "today", tone_of(signal.get("drawdown_from_high"))),
        ]
    )
    st.plotly_chart(drawdown_chart(level), width="stretch", config=CHART_CONFIG)
with tab_dur:
    kpi_grid(
        [
            ("1Y win rate", fmt_pct(signal.get("consistency_overall"), 0), "rolling years beating Nifty 50", ""),
            ("Win in a falling market", fmt_pct(signal.get("consistency_downside"), 0), "when Nifty 50 itself fell", ""),
            ("Alpha", fmt_pct(signal.get("alpha")), "annualised, after beta", tone_of(signal.get("alpha"))),
            ("Rolling 3Y median", fmt_pct(signal.get("rolling_3y_median")),
             f"worst {fmt_pct(signal.get('rolling_3y_min'))}", ""),
        ]
    )
    st.caption("A rank says who is strongest today; these say whether that strength has held up.")

# --------------------------------------------------------------------------- #
# Implementation matrix: every fund that tracks this index
# --------------------------------------------------------------------------- #
section("Implementation matrix", "ETF against index fund, on the numbers a holder actually pays")
vehicles = vehicle_frame(exposure_id)
choice = best_vehicle(exposure_id, live.target.as_of) if live is not None else None
if vehicles.empty:
    note("No ETF or index fund is mapped to this exposure. The index signal stands, but there is no instrument in the "
         "universe to express it.")
else:
    vehicles = vehicles.assign(key=vehicles["symbol"].fillna(vehicles["name"]))
    track = vehicle_tracking(exposure_id)
    if not track.empty:
        track = track.assign(key=track["symbol"].fillna(track["name"]))
        vehicles = vehicles.merge(track[["key", "tracking_difference", "tracking_error", "history_years"]],
                                  on="key", how="left")
    for column in ("tracking_difference", "tracking_error", "history_years", "traded_value", "premium_discount_pct"):
        if column not in vehicles:
            vehicles[column] = float("nan")
    matrix = pd.DataFrame(
        {
            "Best": [choice is not None and k == choice.key for k in vehicles["key"]],
            "Vehicle": [f"{s} · {n}" if isinstance(s, str) and s else n for s, n in zip(vehicles["symbol"], vehicles["name"])],
            "Type": vehicles["vehicle"].map({"etf": "ETF", "index_fund": "Index fund"}).fillna("ETF"),
            "Incepted": pd.to_datetime(vehicles["inception_date"], errors="coerce"),
            "Tracking diff": pd.to_numeric(vehicles["tracking_difference"], errors="coerce"),
            "Tracking err": pd.to_numeric(vehicles["tracking_error"], errors="coerce"),
            "Years": pd.to_numeric(vehicles["history_years"], errors="coerce"),
            "Turnover ₹": pd.to_numeric(vehicles["traded_value"], errors="coerce"),
            "Prem/disc %": pd.to_numeric(vehicles["premium_discount_pct"], errors="coerce"),
        }
    ).sort_values(["Best", "Tracking diff"], ascending=[False, False], na_position="last", kind="mergesort")
    show_table(
        matrix,
        hide_index=True,
        width="stretch",
        column_config={
            "Best": st.column_config.CheckboxColumn(width="small", help="The vehicle the Portfolio page buys"),
            "Vehicle": st.column_config.TextColumn(width="large", pinned=True),
            "Type": st.column_config.TextColumn(width="small", help="ETF: bought on exchange at a price that can "
                                                "differ from NAV. Index fund: bought from the AMC at NAV."),
            "Incepted": st.column_config.DateColumn(format="DD MMM YYYY", help="First published NAV in AMFI's record"),
            "Tracking diff": st.column_config.NumberColumn(format="percent", help="Annualised return given up against "
                                                           "its own index: what the holder actually lost."),
            "Tracking err": st.column_config.NumberColumn(format="percent", help="How erratically it was given up"),
            "Years": st.column_config.NumberColumn(format="%.1f", help="Years of overlapping history measured"),
            "Turnover ₹": st.column_config.NumberColumn(format="compact", help="Value traded on NSE at the last snapshot"),
            "Prem/disc %": st.column_config.NumberColumn(format="%+.2f", help="Last price against NAV"),
        },
    )
    if choice is not None:
        note(f"<b>Best vehicle at the {live.target.as_of:%d %b %Y} decision: {_esc(choice.label)}.</b> "
             f"{_esc(choice.reason)} The Portfolio page uses the same rule.")
    rich = matrix[matrix["Prem/disc %"] > 1.0]
    if not rich.empty:
        note("<b>Trading above NAV:</b> " + ", ".join(f"{_esc(v)} {p:+.2f}%" for v, p in zip(rich["Vehicle"], rich["Prem/disc %"]))
             + ". Buying at a premium hands back part of the signal's edge on day one.", tone="warn")
    st.caption("Turnover and premium are a point-in-time NSE snapshot from the last pipeline run, not a history; blank "
               "means NSE did not serve one. Check the AMC factsheet before you trade.")

    # ----------------------------------------------------------------------- #
    # Position sizing
    # ----------------------------------------------------------------------- #
    section("Position sizing", f"One slot is 1/{config.target_holdings_n} of the book · ETFs capped at "
            f"{PARTICIPATION_LIMIT:.0%} of a day's turnover")
    book_lakh = st.slider("Book size (₹ lakh)", min_value=10, max_value=100, step=5,
                          value=int(st.session_state.get("book_size", 3_000_000) / 100_000), key="book_lakh",
                          help="₹10 lakh to ₹1 crore. The Portfolio page's days-to-build uses the same book.")
    st.session_state["book_size"] = float(book_lakh) * 100_000
    book = st.session_state["book_size"]
    position = book / config.target_holdings_n
    sizing = []
    for row in vehicles.itertuples():
        candidate = VehicleChoice(
            exposure_id=exposure_id, key=row.key, name=row.name, vehicle=row.vehicle or "etf",
            symbol=row.symbol if isinstance(row.symbol, str) else None, scheme_code=row.scheme_code, reason="",
            traded_value=float(row.traded_value) if pd.notna(row.traded_value) else None,
        )
        days = days_to_build(candidate, position)
        sizing.append({"Vehicle": candidate.label, "Type": "Index fund" if candidate.vehicle == "index_fund" else "ETF",
                       "Position": position, "Share of a day's turnover":
                       (position / candidate.traded_value) if candidate.traded_value else None,
                       "Days to build": days})
    sizing = pd.DataFrame(sizing)
    # None would print as the word "None"; NaN renders blank, as the column help promises.
    for column in ("Share of a day's turnover", "Days to build"):
        sizing[column] = pd.to_numeric(sizing[column], errors="coerce")
    sizing = sizing.sort_values("Days to build", na_position="last", kind="mergesort")
    fastest = sizing["Days to build"].min()
    kpi_grid(
        [
            ("Book", fmt_rupees(book), "", ""),
            ("One slot", fmt_rupees(position), f"1/{config.target_holdings_n} of the book", "accent"),
            ("Fastest build", "—" if pd.isna(fastest) else f"{fastest:.0f} day{'s' if fastest != 1 else ''}",
             "index funds fill at the next NAV", "pos" if fastest == 1 else "warn"),
        ]
    )
    show_table(
        sizing,
        hide_index=True,
        width="stretch",
        column_config={
            "Vehicle": st.column_config.TextColumn(width="large", pinned=True),
            "Position": st.column_config.NumberColumn(format="compact"),
            "Share of a day's turnover": st.column_config.NumberColumn(format="percent"),
            "Days to build": st.column_config.NumberColumn(format="%.0f", help="Blank: no NSE turnover to judge from"),
        },
    )
    if sizing["Days to build"].isna().all():
        note("<b>No NSE turnover snapshot for these funds.</b> Days to build cannot be judged for an ETF without "
             "one; check its traded value on NSE before sizing an order.", tone="warn")

    prices = load_etf_prices()
    keys = [k for k in vehicles["key"] if k in prices.columns]
    if keys:
        with st.expander("Fund performance, rebased to a common start", expanded=False):
            figure, window = etf_comparison(prices, keys)
            st.plotly_chart(figure, width="stretch", config=CHART_CONFIG)
            if window:
                st.caption(f"{window}. Each fund over its own full history would make the longest-listed one look "
                           "strongest purely because it started earlier.")
