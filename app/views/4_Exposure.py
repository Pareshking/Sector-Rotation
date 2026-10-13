"""Exposure: the Paresh app's stock page (src/ui/views/stock_view.py), for one sector or theme index.

Element by element: the picker sits where the stock page keeps its actions,
the identity becomes a strip of readings (action, rank, score, returns), the
verdict a callout, and "Price and relative strength" Lightweight-Charts panes:
the index level with its drawdown, Mansfield RS against Nifty 50, and trailing
volatility. The implementation matrix and position sizing are kit tables in
cards. The selectbox key (``detail_exposure``) is how the Screener opens an
exposure here; the book slider sets ``st.session_state["book_size"]``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import repair_level_shifts  # noqa: E402
from app.components.fmt import DASH, day, num, pct, rupees, tone  # noqa: E402
from app.components.metrics import HELD_ACTIONS, source_label  # noqa: E402
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
from app.kit import lw_chart as lw  # noqa: E402
from app.kit import page_kit as kit  # noqa: E402
from app.kit.theme import render_saas_table  # noqa: E402
from src.portfolio.vehicles import PARTICIPATION_LIMIT, VehicleChoice, days_to_build  # noqa: E402

actions = kit.page_head("Exposure", "One sector or theme: its signal, how it behaves, and the fund to buy it with",
                        actions=True)

decisions = load_decisions()
if decisions.empty:
    kit.note("No prepared model data is available.")
    st.stop()

panel, _ = load_index_panel()
config = strategy_config()
live = load_portfolio()

# Held names first, then rank order: the exposure a reader most likely wants is the default.
ordered = pd.concat([decisions[decisions["model_action"].isin(HELD_ACTIONS)],
                     decisions[~decisions["model_action"].isin(HELD_ACTIONS)]])
# ?exposure=<id> is how a Screener row opens this page (its table cannot call
# back into Python). Applied once per id, so picking another exposure here is
# not undone by the next rerun.
wanted = str(st.query_params.get("exposure") or "")
if wanted and st.session_state.get("_exposure_from_url") != wanted:
    st.session_state["_exposure_from_url"] = wanted
    match = decisions.loc[decisions["exposure_id"].astype(str) == wanted, "exposure"]
    if not match.empty:
        st.session_state["detail_exposure"] = match.iloc[0]
with actions:
    exposure = st.selectbox(
        "Exposure", ordered["exposure"].tolist(), key="detail_exposure", label_visibility="collapsed", width=300,
        help="Type to search. Held exposures first, then rank order.",
    )
signal = decisions[decisions["exposure"] == exposure].iloc[0]
exposure_id = str(signal.get("exposure_id", ""))


def _rank(value: object) -> str:
    rank = pd.to_numeric(value, errors="coerce")
    return f"#{int(rank)}" if pd.notna(rank) else DASH


# --------------------------------------------------------------------------- #
# Identity: readings and the verdict
# --------------------------------------------------------------------------- #
action = str(signal.get("model_action", "NOT HELD"))
stage = str(signal.get("stage", "") or "")
category = {"sector": "Sector", "thematic": "Theme"}.get(str(signal.get("category")), "")
if signal.get("shares_index_with"):
    kit.note(f"Same index as {signal.get('shares_index_with')}.", "Holding both is one bet, not two.")

kit.readings([
    kit.Reading("Action", action.title(), f"Decision rank {_rank(signal.get('decision_rank'))} · target "
                f"{pct(signal.get('target_weight', 0.0), 0)}",
                "up" if action in HELD_ACTIONS else ("down" if action == "SELL" else "")),
    kit.Reading("Score", num(signal.get("momentum_z")), "z-score composite", tone(signal.get("momentum_z"))),
    kit.Reading("1M", pct(signal.get("return_1M"), signed=True), "index return", tone(signal.get("return_1M"))),
    kit.Reading("3M", pct(signal.get("return_3M"), signed=True), "", tone(signal.get("return_3M"))),
    kit.Reading("6M", pct(signal.get("return_6M"), signed=True), "", tone(signal.get("return_6M"))),
    kit.Reading("12M", pct(signal.get("return_12M"), signed=True), "the hurdle compares this",
                tone(signal.get("return_12M"))),
], exposure)

kit.callout(" · ".join(b for b in (exposure, category, f"{stage} quadrant" if stage else "") if b),
            str(signal.get("analysis_note", "") or ""),
            "up" if action in HELD_ACTIONS else ("down" if action == "SELL" else "muted"))
source = " · ".join(
    b for b in (source_label(signal.get("data_source")), f"{signal.get('value_type', '')} series".strip(),
                str(signal.get("resolved_official_index_name", "") or "")) if b and b != "series"
)
if source:
    kit.caption(source)

# --------------------------------------------------------------------------- #
# Price and relative strength
# --------------------------------------------------------------------------- #
level = panel[exposure_id].dropna() if exposure_id in panel.columns else pd.Series(dtype=float)
with kit.card("Index level & drawdown", "ex_level", "drawdown from the running high"):
    kit.metric_row([
        kit.Metric("Max drawdown", pct(signal.get("max_drawdown")), help="Worst fall over five years"),
        kit.Metric("Off its high", pct(signal.get("drawdown_from_high")), help="Today"),
    ], key="ex_level")
    if level.empty:
        kit.caption("No index history for this exposure.")
    else:
        span = st.segmented_control("Window", ["1Y", "3Y", "All"], default="All", key="ex_window",
                                    label_visibility="collapsed") or "All"
        drawdown = level / level.cummax() - 1.0
        if span != "All":
            start = level.index.max() - pd.DateOffset(years=int(span[0]))
            level_shown, drawdown = level.loc[start:], drawdown.loc[start:]
        else:
            level_shown = level
        lw.render([
            {"height": 300, "series": [{"name": exposure, "type": "line", "color": lw.INDIGO, "fmt": "num",
                                        "data": lw.series_points(level_shown.index, level_shown)}]},
            {"height": 140, "series": [{"name": "Drawdown", "type": "baseline", "color": lw.RED, "negColor": lw.RED,
                                        "fmt": "pct", "data": lw.series_points(drawdown.index, drawdown, scale=100.0)}]},
        ], key="ex_level_chart")

rs = load_rs()
left, right = st.columns(2, gap="medium")
with left, kit.card("Relative strength vs Nifty 50", "ex_rs", "Mansfield RS, weekly, three years"):
    kit.metric_row([
        kit.Metric("RS ratio", num(signal.get("rs_ratio"), 3), help="1.000 = its own 52-week average"),
        kit.Metric("RS velocity", num(signal.get("rs_momentum"), 1), help="13-week change"),
        kit.Metric("12M vs Nifty 50", pct(signal.get("relative_12M"), signed=True), help="Return minus benchmark"),
    ], key="ex_rs")
    series = (pd.to_numeric(rs[exposure_id], errors="coerce").dropna().tail(156)
              if exposure_id in getattr(rs, "columns", []) else pd.Series(dtype=float))
    if series.empty:
        kit.caption("No relative-strength history for this exposure.")
    else:
        lw.render([{"height": 260, "series": [
            {"name": "Mansfield RS", "type": "baseline", "color": lw.GREEN, "negColor": lw.RED, "fmt": "pct",
             "data": lw.series_points(series.index, series)}]}], key="ex_rs_chart")
with right, kit.card("Volatility", "ex_vol", "annualised, daily log returns"):
    kit.metric_row([
        kit.Metric("Volatility 3Y", pct(signal.get("volatility_3y"))),
        kit.Metric("Beta", num(signal.get("beta")), help=f"R² {num(signal.get('r_squared'))}"),
        kit.Metric("Sharpe 3Y", num(signal.get("sharpe_3y")), help="Risk-free 6.5%"),
    ], key="ex_vol")
    prices = pd.to_numeric(level, errors="coerce").dropna()
    if len(prices) < 70:
        kit.caption("Too little history to measure.")
    else:
        daily = np.log(prices).diff()
        lw.render([{"height": 260, "series": [
            {"name": name, "type": "line", "color": colour, "fmt": "share1", "width": width,
             "data": lw.series_points(vol.index, vol, scale=100.0)}
            for name, colour, width, vol in (
                ("12-month", lw.INDIGO, 2, (daily.rolling(252).std() * np.sqrt(252)).dropna()),
                ("3-month", lw.AMBER, 1, (daily.rolling(63).std() * np.sqrt(252)).dropna()),
            )
        ]}], key="ex_vol_chart")

with kit.card("Durability", "ex_durability", "whether the strength has held up"):
    kit.metric_row([
        kit.Metric("1Y win rate", pct(signal.get("consistency_overall"), 0), help="Rolling years beating Nifty 50"),
        kit.Metric("Win in a falling market", pct(signal.get("consistency_downside"), 0),
                   help="When Nifty 50 itself fell"),
        kit.Metric("Alpha", pct(signal.get("alpha"), signed=True), help="Annualised, after beta"),
        kit.Metric("Rolling 3Y median", pct(signal.get("rolling_3y_median")),
                   help=f"Worst {pct(signal.get('rolling_3y_min'))}"),
    ], key="ex_durability")

# --------------------------------------------------------------------------- #
# Implementation matrix: every fund that tracks this index
# --------------------------------------------------------------------------- #
vehicles = vehicle_frame(exposure_id)
choice = best_vehicle(exposure_id, live.target.as_of) if live is not None else None
if vehicles.empty:
    with kit.card("Implementation matrix", "ex_matrix"):
        kit.caption("No ETF or index fund is mapped to this exposure: the signal stands, with nothing to buy.")
    st.stop()

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

with kit.card("Implementation matrix", "ex_matrix", "ETF against index fund, on what a holder actually pays"):
    render_saas_table(matrix.assign(**{
        "Incepted": matrix["Incepted"].map(day),
        "Tracking diff": matrix["Tracking diff"].map(lambda v: pct(v, 2, signed=True)),
        "Tracking err": matrix["Tracking err"].map(lambda v: pct(v, 2)),
        "Years": matrix["Years"].map(lambda v: num(v, 1)),
        "Turnover ₹": matrix["Turnover ₹"].map(rupees),
        "Prem/disc %": matrix["Prem/disc %"].map(lambda v: DASH if pd.isna(v) else f"{v:+.2f}%"),
    }))
    if choice is not None:
        kit.callout(f"Best vehicle at the {live.target.as_of:%d %b %Y} decision: {choice.label}",
                    f"{choice.reason} The Portfolio page uses the same rule.", "up")
    rich = matrix[matrix["Prem/disc %"] > 1.0]
    if not rich.empty:
        kit.callout("Trading above NAV",
                    ", ".join(f"{v} {p:+.2f}%" for v, p in zip(rich["Vehicle"], rich["Prem/disc %"]))
                    + ". A premium hands back part of the edge on day one.", "warn")
    kit.caption("Tracking: annualised return given up against the index, and how erratically. Turnover and premium: "
                "the NSE snapshot from the last pipeline run; — means NSE served none.")

# --------------------------------------------------------------------------- #
# Position sizing
# --------------------------------------------------------------------------- #
with kit.card("Position sizing", "ex_sizing",
              f"one slot = 1/{config.target_holdings_n} of the book · ETFs capped at "
              f"{PARTICIPATION_LIMIT:.0%} of a day's turnover"):
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
        sizing.append({"Vehicle": candidate.label, "Type": "Index fund" if candidate.vehicle == "index_fund" else "ETF",
                       "Position": position,
                       "Share of a day's turnover": (position / candidate.traded_value) if candidate.traded_value else None,
                       "Days to build": days_to_build(candidate, position)})
    sizing = pd.DataFrame(sizing)
    for column in ("Share of a day's turnover", "Days to build"):
        sizing[column] = pd.to_numeric(sizing[column], errors="coerce")
    sizing = sizing.sort_values("Days to build", na_position="last", kind="mergesort")
    fastest = sizing["Days to build"].min()
    kit.metric_row([
        kit.Metric("Book", rupees(book)),
        kit.Metric("One slot", rupees(position), help=f"1/{config.target_holdings_n} of the book"),
        kit.Metric("Fastest build", DASH if pd.isna(fastest) else f"{fastest:.0f} day{'s' if fastest != 1 else ''}",
                   help="Index funds fill at the next NAV"),
    ], key="ex_sizing")
    render_saas_table(sizing.assign(**{
        "Position": sizing["Position"].map(rupees),
        "Share of a day's turnover": sizing["Share of a day's turnover"].map(lambda v: pct(v, 2)),
        "Days to build": sizing["Days to build"].map(lambda v: DASH if pd.isna(v) else f"{v:.0f}"),
    }))
    if sizing["Days to build"].isna().all():
        kit.callout("No NSE turnover snapshot for these funds.",
                    "Days to build cannot be judged for an ETF without one; check its traded value before you order.",
                    "warn")

# --------------------------------------------------------------------------- #
# Fund performance on the window every vehicle shares
# --------------------------------------------------------------------------- #
navs = load_etf_prices()
cleaned = {}
for key in (k for k in vehicles["key"] if k in navs.columns):
    fixed, _ = repair_level_shifts(navs[key])
    if not fixed.empty:
        cleaned[key] = fixed
if cleaned:
    start = max(s.index.min() for s in cleaned.values())
    end = min(s.index.max() for s in cleaned.values())
    palette = [lw.INDIGO, lw.GREEN, lw.AMBER, lw.GREY, lw.RED, lw.INK]
    lines = []
    for i, (key, fixed) in enumerate(cleaned.items()):
        window = fixed.loc[start:end]
        if not window.empty:
            lines.append({"name": key, "type": "line", "color": palette[i % len(palette)], "fmt": "num",
                          "data": lw.series_points(window.index, window / float(window.iloc[0]) * 100.0)})
    if lines:
        with kit.card("Fund performance", "ex_funds", f"growth of ₹100 · common window {start:%d %b %Y} – {end:%d %b %Y}"):
            lw.render([{"height": 300, "series": lines}], key="ex_funds_chart")
