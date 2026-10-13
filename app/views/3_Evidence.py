"""Evidence: the Paresh app's Backtest page (src/ui/views/backtest_view.py), on the walk-forward replay.

Element by element: the page head with its toggle on the right, the one-line
"Tested" summary, a strip of six readings, Growth of ₹100 with the drawdown
under it (Lightweight Charts), Calendar returns (year by year, then each
year's months), and a segmented control for the detail views. What Paresh has
no counterpart for (with and without back-calculated history, every 12-month
window, early versus recent, the parameter sensitivity) is drawn in the same
cards. Every figure comes from app/data.py and src/quantitative; this page
only lays them out.
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

from app.components.fmt import num, pct, tone  # noqa: E402
from app.data import (  # noqa: E402
    EVALUATION_OPTIONS,
    EVALUATION_SETTINGS,
    STRATEGY_OPTIONS,
    STRATEGY_TRIALS,
    backtest_config,
    load_backtest,
    load_decisions,
    load_index_panel,
    load_sensitivity,
    strategy_config,
)
from app.kit import lw_chart as lw  # noqa: E402
from app.kit import page_kit as kit  # noqa: E402
from app.kit.calendar import build_grid, render_calendar_returns, render_yearly_summary  # noqa: E402
from app.kit.charts import render_columns  # noqa: E402
from app.kit.theme import render_saas_table  # noqa: E402
from src.quantitative.backtest import period_split, rolling_summary_stats, rolling_windows  # noqa: E402
from src.quantitative.stats import deflated_sharpe  # noqa: E402

BENCH = "Nifty 50 TRI"

actions = kit.page_head("Evidence", "The live rules replayed month by month, net of costs", actions=True)

panel, benchmark = load_index_panel()
if panel.empty or benchmark.empty:
    kit.note("No index price panel yet.", "The data pipeline writes it on its next run.")
    st.stop()

live_config = strategy_config()
decisions = load_decisions()
NAMES = decisions.set_index("exposure_id")["exposure"].to_dict() if not decisions.empty else {}


def _pretty(holdings: str) -> str:
    if not holdings or holdings == "cash":
        return "cash"
    return ", ".join(NAMES.get(part.strip(), part.strip()) for part in str(holdings).split(","))


def _pretty_reasons(text: str) -> str:
    """'defence:slots full; it:fails cash hurdle' as readable names."""
    parts = []
    for item in str(text or "").split(";"):
        exposure_id, _, reason = item.strip().partition(":")
        if exposure_id:
            parts.append(f"{NAMES.get(exposure_id.strip(), exposure_id.strip())} — {reason.strip()}")
    return "; ".join(parts)


def _deflated(result):
    """Deflated Sharpe of monthly returns over what cash earned the same month."""
    monthly = result.monthly
    return deflated_sharpe(monthly["strategy_return"] - monthly["cash_return"], STRATEGY_TRIALS)


def _growth(equity: pd.DataFrame, key: str) -> None:
    """Growth of ₹100 against Nifty 50 TRI, both drawdowns in the pane under it."""
    strat, bench = equity["strategy"].astype(float), equity["benchmark"].astype(float)
    lw.render([
        {"height": 300, "series": [
            {"name": "Strategy (net)", "type": "line", "color": lw.INDIGO, "fmt": "num",
             "data": lw.series_points(equity.index, strat)},
            {"name": BENCH, "type": "line", "color": lw.GREY, "fmt": "num",
             "data": lw.series_points(equity.index, bench)}]},
        {"height": 150, "series": [
            {"name": "Strategy drawdown", "type": "baseline", "color": lw.RED, "negColor": lw.RED, "fmt": "pct",
             "data": lw.series_points(equity.index, strat / strat.cummax() - 1.0, scale=100.0)},
            {"name": f"{BENCH} drawdown", "type": "line", "color": lw.GREY, "fmt": "pct", "width": 1,
             "data": lw.series_points(equity.index, bench / bench.cummax() - 1.0, scale=100.0)}]},
    ], key=key)


def _bars(dates, values, key: str, height: int = 240) -> None:
    """Signed returns as green and red bars on real dates."""
    points = lw.series_points(dates, pd.to_numeric(pd.Series(list(values)), errors="coerce"), scale=100.0)
    lw.render([{"height": height, "series": [
        {"name": "Excess", "type": "histogram", "color": lw.GREEN, "fmt": "pct",
         "colors": [lw.GREEN if v >= 0 else lw.RED for _, v in points], "data": points}]}], key=key)


# --------------------------------------------------------------------------- #
# The live rules, net of costs
# --------------------------------------------------------------------------- #
with actions:
    include_backfill = st.toggle(
        "Include back-calculated index history",
        value=live_config.backfill_policy == "include",
        key="ev_backfill",
        help="Before its NSE launch an index's values were computed after the fact and could not have been traded.",
    )
result = load_backtest(backtest_config(exclude_backcalculated=not include_backfill))
if not result.ok:
    kit.note("Evidence unavailable.", str(result.error))
    st.stop()
stats = result.stats
dsr = _deflated(result)
stamps = pd.to_datetime(result.equity.index)  # first fill to last mark
first, last = stamps.min(), stamps.max()
months = int(stats["months"])

st.html(
    '<div class="bt-sum"><b>Tested</b>'
    f"<span>{first:%d %b %Y} to {last:%d %b %Y}</span>"
    f"<span><b>{months}</b> months</span>"
    f"<span>Hold top <b>{live_config.target_holdings_n}</b></span>"
    f"<span>Keep while rank ≤ <b>{live_config.retention_buffer_m}</b></span>"
    "<span>Hurdle <b>liquid fund 12M</b></span>"
    "<span>Fill <b>next close</b></span>"
    f"<span>Costs <b>{stats['cost_bps_per_side']:g} bps</b> per side</span>"
    f"<span>Back-calculated history <b>{'included' if include_backfill else 'excluded'}</b></span></div>"
)

kit.note(
    "Point-in-time, not out-of-sample.",
    "The rules were specified after studying this window."
    + ("" if dsr and dsr.deflated >= 0.95 else " A Deflated Sharpe below 95% is not evidence of an edge."),
)

kit.readings([
    kit.Reading("Net CAGR", pct(stats["cagr"], signed=True), f"{BENCH} {pct(stats['benchmark_cagr'], signed=True)}",
                "up" if stats["cagr"] > stats["benchmark_cagr"] else "down"),
    kit.Reading("Net total return", pct(stats["total_return"], signed=True),
                f"{BENCH} {pct(stats['benchmark_total_return'], signed=True)}", tone(stats["total_return"])),
    kit.Reading("Net excess vs Nifty", pct(stats["excess_total"], signed=True), f"over {months} months",
                tone(stats["excess_total"])),
    kit.Reading("Max drawdown", pct(stats["max_drawdown"]), f"{BENCH} {pct(stats['benchmark_max_drawdown'])}", "down"),
    kit.Reading("Deflated Sharpe", f"{dsr.deflated:.0%}" if dsr else "—",
                f"after {STRATEGY_TRIALS} trials" if dsr else "too few periods",
                "up" if dsr and dsr.deflated >= 0.95 else "warn"),
    kit.Reading("Sharpe", num(stats["sharpe"]), f"{BENCH} {num(stats['benchmark_sharpe'])} · rf {pct(stats['risk_free'])}"),
], "Walk-forward evidence")

with kit.card("Growth of ₹100", "ev_growth", f"net of costs · {BENCH} in grey"):
    kit.metric_row([
        kit.Metric("Avg turnover", pct(stats["avg_turnover"]), help="Of the book, each rebalance"),
        kit.Metric("Costs paid", pct(stats["total_cost"])),
        kit.Metric("Gross total", pct(stats["gross_total_return"], signed=True)),
        kit.Metric("Periods with cash", f"{int(stats['cash_months'])} of {int(stats['periods'])}",
                   help="A slot failed the hurdle"),
    ], key="ev_growth")
    _growth(result.equity, "ev_equity")

ledger = result.monthly
with kit.card("Calendar returns", "ev_calendar", f"Strategy, {BENCH} and Alpha · month of each fill"):
    calendar = pd.DataFrame({
        "Period": pd.to_datetime(ledger["fill_date"]).dt.to_period("M").astype(str),
        "Strategy": ledger["strategy_return"].astype(float),
        "Benchmark": ledger["benchmark_return"].astype(float),
    })
    grid = build_grid(calendar.assign(Alpha=calendar["Strategy"] - calendar["Benchmark"]),
                      {"Strategy": "Strategy", "Benchmark": BENCH, "Alpha": "Alpha"})
    render_yearly_summary(grid, BENCH)
    render_calendar_returns(grid)

# --------------------------------------------------------------------------- #
# Pre-launch history: the same rules, with and without it
# --------------------------------------------------------------------------- #
other = load_backtest(backtest_config(exclude_backcalculated=include_backfill))
if other.ok:
    pair = {include_backfill: result, (not include_backfill): other}
    comparison = pd.DataFrame([
        {
            "Strategy": "With back-calculated history" if included else "Without back-calculated history",
            "Total Return": r.stats["total_return"],
            "CAGR": r.stats["cagr"],
            "Alpha": r.stats["excess_total"],
            "Max Drawdown": r.stats["max_drawdown"],
            "Deflated Sharpe": f"{d.deflated:.0%}" if (d := _deflated(r)) else "—",
        }
        for included, r in sorted(pair.items(), reverse=True)
    ])
    with kit.card("With and without back-calculated history", "ev_backfill_pair",
                  "same rules · only pre-launch eligibility differs · Alpha = net excess vs Nifty"):
        render_saas_table(comparison)

# --------------------------------------------------------------------------- #
# Robustness: every 12-month window, and early versus recent
# --------------------------------------------------------------------------- #
windows = rolling_windows(result, window=max(12 // live_config.rebalance_months, 2))
roll = rolling_summary_stats(windows)
with kit.card("Every 12-month window", "ev_rolling", f"excess over {BENCH}"):
    if not roll:
        kit.caption("Not enough completed periods yet to form a rolling window.")
    else:
        kit.metric_row([
            kit.Metric("Beat Nifty 50", f"{roll['beat_rate']:.0%}", help=f"Of {int(roll['windows'])} rolling windows"),
            kit.Metric("Median excess", pct(roll["median_excess"], signed=True)),
            kit.Metric("Worst window", pct(roll["worst_excess"], signed=True)),
            kit.Metric("Best window", pct(roll["best_excess"], signed=True)),
        ], key="ev_rolling")
        left, right = st.columns(2, gap="medium")
        with left:
            excess = windows["excess"].astype(float)
            edges = np.linspace(min(excess.min(), 0.0), max(excess.max(), 0.0), 21)
            counts, edges = np.histogram(excess, bins=edges)
            mids = (edges[:-1] + edges[1:]) / 2
            width = float(edges[1] - edges[0]) or 1.0
            median = float(excess.median())
            render_columns(
                [f"{a:+.0%} to {b:+.0%}" for a, b in zip(edges[:-1], edges[1:])],
                counts.tolist(),
                [lw.GREEN if m > 0 else lw.RED for m in mids],
                unit="windows",
                lines=[((0.0 - edges[0]) / width - 0.5, lw.GREY, ""),
                       ((median - edges[0]) / width - 0.5, lw.INDIGO, f"median {median:+.1%}")],
                x_title="How often",
            )
        with right:
            _bars(windows["end"], windows["excess"], "ev_rolling_bars", height=260)
            kit.caption("Each bar: the 12 months ending that date.")

split = period_split(result)
if not split.empty:
    halves = pd.DataFrame({
        "Period": [f"{'Early' if h == 'early' else 'Recent'} · {a:%b %Y} – {b:%b %Y}"
                   for h, a, b in zip(split["half"], split["from"], split["to"])],
        "Rebalances": split["periods"].astype(int),
        "Strategy Net": split["strategy"].astype(float),
        "Benchmark": split["benchmark"].astype(float),
        "Alpha": split["excess"].astype(float),
        "Periods with cash": split["cash_periods"].map(pct),
    })
    with kit.card("Early versus recent", "ev_halves", "the blended figure hides which half it came from"):
        render_saas_table(halves)

# --------------------------------------------------------------------------- #
# Detail views, as on the Paresh Backtest page
# --------------------------------------------------------------------------- #
VIEWS = ["Month by month", "Method"]
view = st.segmented_control("Evidence detail", VIEWS, default=VIEWS[0], key="ev_view",
                            label_visibility="collapsed") or VIEWS[0]

if view == "Month by month":
    named = ledger.assign(holdings=ledger["holdings"].map(_pretty))
    if "skipped" in named.columns:
        named["skipped"] = named["skipped"].map(_pretty_reasons)
    named["Month"] = pd.to_datetime(named["period_end"]).dt.strftime("%b %Y")
    with kit.card("Month by month", "ev_ledger", f"{len(named)} periods · excess over {BENCH}"):
        _bars(named["period_end"], named["excess_return"], "ev_monthly_bars", height=220)
        table = pd.DataFrame({
            "Month": named["Month"],
            "Held names": named["holdings"],
            "Cash": pd.to_numeric(named["cash_slots"], errors="coerce").astype("Int64"),
            "Turnover %": named["turnover"].astype(float) * 100.0,
            "Cost": named["cost"].map(lambda v: pct(v, 2)),
            "Strategy Net": named["strategy_return"].astype(float),
            "Benchmark": named["benchmark_return"].astype(float),
            "Alpha": named["excess_return"].astype(float),
            "Eligible": pd.to_numeric(named["universe"], errors="coerce").astype("Int64"),
            "Passed over (reason)": named["skipped"] if "skipped" in named.columns else "",
        }).iloc[::-1]
        render_saas_table(table, max_height=520)
        export = named[["Month", "holdings", "cash_slots", "turnover", "cost", "strategy_return", "benchmark_return",
                        "excess_return", "universe", "skipped"]]
        st.download_button("Export months CSV", export.to_csv(index=False).encode("utf-8"),
                           file_name="sector_rotation_evidence.csv", mime="text/csv", key="dl_ev_ledger")
else:
    with kit.card("Method", "ev_method", "how every figure on this page is made"):
        st.markdown(
            "**Point-in-time.** At every month-end close the same `construct_target_portfolio` that builds the "
            "Portfolio page decides the holdings from prices up to that close.\n\n"
            f"**Fills and costs.** Trades fill at the next session's close and pay "
            f"**{live_config.cost_bps_per_side:g} bps** per side on the weight traded.\n\n"
            f"**Cash.** Earns what the liquid fund's NAV earned between fills "
            f"({live_config.risk_free_rate_annual:.1%} before its history). Only completed months count.\n\n"
            + (f"**Deflated Sharpe {dsr.deflated:.0%}** (probabilistic Sharpe {dsr.probabilistic:.0%}): the chance "
               f"the true monthly Sharpe is above zero after the best of {STRATEGY_TRIALS} zero-edge configurations "
               f"({' × '.join(f'{len(v)} {k.lower()}' for k, v in STRATEGY_OPTIONS.items())}). Luck alone gives "
               f"{dsr.benchmark_sharpe:.2f} against {dsr.sharpe:.2f} here, over {dsr.observations} monthly returns "
               "over cash (Bailey & López de Prado 2014).\n\n" if dsr else "")
            + "**Not modelled.** Tax, an ETF's premium to NAV, impact on thin funds, a fund's tracking difference, "
            "and funds that launched and later closed. The universe was chosen in 2026."
        )

# --------------------------------------------------------------------------- #
# What-if: hundreds of configurations, explicitly not validated
# --------------------------------------------------------------------------- #
with st.expander("Parameter Sensitivity (Unvalidated)", expanded=False):
    kit.note(
        "Every setting here is a what-if, not the strategy.",
        f"{STRATEGY_TRIALS} configurations across {EVALUATION_SETTINGS} evaluation settings: some will beat the live "
        "rules by luck alone. The Deflated Sharpe above already counts them all as trials.",
    )
    row = st.columns(4)
    universe_choice = row[0].selectbox("Universe", EVALUATION_OPTIONS["Universe"], key="wi_universe")
    top_n = row[1].selectbox("Hold top N", STRATEGY_OPTIONS["Hold top N"],
                             index=STRATEGY_OPTIONS["Hold top N"].index(live_config.target_holdings_n), key="wi_n")
    buffer = row[2].selectbox("Retention buffer", STRATEGY_OPTIONS["Retention buffer"], key="wi_buffer")
    hold = row[3].selectbox("Holding period (months)", STRATEGY_OPTIONS["Holding period (months)"], key="wi_hold")
    row = st.columns(4)
    window = row[0].selectbox("History window", EVALUATION_OPTIONS["History window"], key="wi_window")
    category = row[1].selectbox("Which exposures", EVALUATION_OPTIONS["Which exposures"], key="wi_category")
    cost = row[2].selectbox("Cost per side (bps)", EVALUATION_OPTIONS["Cost per side (bps)"],
                            index=EVALUATION_OPTIONS["Cost per side (bps)"].index(int(live_config.cost_bps_per_side)),
                            key="wi_cost")
    hurdle = row[3].selectbox("Cash hurdle", STRATEGY_OPTIONS["Cash hurdle"], key="wi_hurdle")

    what_if = backtest_config(
        top_n=int(top_n),
        buffer_m=2 * int(top_n) if buffer == "M = 2N" else int(top_n),
        hold_months=int(hold),
        absolute_filter=hurdle == "On",
        investable_only=universe_choice.startswith("Buyable"),
        cost_bps=float(cost),
        exclude_backcalculated=not include_backfill,
    )
    trial_months = None if window == "All" else int(window)
    trial = load_backtest(what_if, months=trial_months, category=category)
    if not trial.ok:
        kit.callout("Unavailable", str(trial.error), "warn")
    else:
        t = trial.stats
        kit.metric_row([
            kit.Metric("Net total return", pct(t["total_return"], signed=True),
                       help=f"Nifty {pct(t['benchmark_total_return'], signed=True)}"),
            kit.Metric("Net excess", pct(t["excess_total"], signed=True),
                       help=f"Live rules {pct(stats['excess_total'], signed=True)}"),
            kit.Metric("Max drawdown", pct(t["max_drawdown"])),
            kit.Metric("Avg turnover", pct(t["avg_turnover"])),
        ], key="ev_what_if")
        _growth(trial.equity, "what_if_curve")

    if st.toggle("Also test six score specifications", value=False, key="wi_scores"):
        specs = load_sensitivity(what_if, months=trial_months, category=category)
        if specs.empty:
            kit.caption("Not enough history to test alternative score specifications.")
        else:
            render_saas_table(pd.DataFrame({
                "Score specification": specs["weighting"],
                "Total Return": specs["total_return"].astype(float),
                "Alpha": specs["excess"].astype(float),
                "Max DD": specs["max_drawdown"].astype(float),
                "Hit rate": specs["hit_rate"].map(pct),
                "Turnover %": specs["turnover"].astype(float) * 100.0,
            }))
            spread = float(specs["excess"].max() - specs["excess"].min())
            kit.callout(f"The score specification moves the answer by {spread:.0%}.",
                        "That spread is the parameter, not the strategy. The live rules weight the four segments "
                        "equally, assuming nothing about which horizon predicts best.", "warn")
