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
    equity_curve,
    excess_distribution,
    monthly_excess,
    rolling_excess,
)
from app.components.tables import show_table, tinted  # noqa: E402
from app.components.theme import fmt_pct, kpi_grid, note, page_header, section, tone_of  # noqa: E402
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
from src.quantitative.backtest import period_split, rolling_summary_stats, rolling_windows  # noqa: E402
from src.quantitative.stats import deflated_sharpe  # noqa: E402

page_header(
    "Walk-forward evidence",
    "Evidence",
    "The live rules replayed over every completed month, net of costs, with cash earning what the liquid fund "
    "earned. Point-in-time, not out-of-sample: the rules were specified after studying this window.",
)

panel, benchmark = load_index_panel()
if panel.empty or benchmark.empty:
    note("<b>No index price panel is available yet.</b> The data pipeline writes "
         "<code>data/processed/index_prices.parquet</code> on its next run.", tone="warn")
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


def _named(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["holdings"] = out["holdings"].map(_pretty)
    if "skipped" in out.columns:
        out["skipped"] = out["skipped"].map(_pretty_reasons)
    return out


def _deflated(result):
    """Deflated Sharpe of monthly returns over what cash earned the same month."""
    monthly = result.monthly
    return deflated_sharpe(monthly["strategy_return"] - monthly["cash_return"], STRATEGY_TRIALS)


# --------------------------------------------------------------------------- #
# Tearsheet: the live rules, net of costs
# --------------------------------------------------------------------------- #
include_backfill = st.toggle(
    "Include back-calculated index history",
    value=live_config.backfill_policy == "include",
    key="ev_backfill",
    help="Before its NSE launch date an index's values were computed after the fact and could not have been "
    "traded. Off: an index is not eligible before its launch.",
)
result = load_backtest(backtest_config(exclude_backcalculated=not include_backfill))
if not result.ok:
    note(f"<b>Evidence unavailable.</b> {result.error}", tone="warn")
    st.stop()
stats = result.stats
dsr = _deflated(result)
first, last = pd.to_datetime(result.monthly["period_end"]).agg(["min", "max"])

section("Tearsheet", f"Net of {stats['cost_bps_per_side']:g} bps per side · {int(stats['months'])} months · "
        f"{first:%b %Y} – {last:%b %Y}")
kpi_grid(
    [
        ("Net CAGR", fmt_pct(stats["cagr"]), f"Nifty 50 TRI {fmt_pct(stats['benchmark_cagr'])}",
         "pos" if stats["cagr"] > stats["benchmark_cagr"] else "neg"),
        ("Net total return", fmt_pct(stats["total_return"]), f"Nifty 50 TRI {fmt_pct(stats['benchmark_total_return'])}", ""),
        ("Net excess vs Nifty", fmt_pct(stats["excess_total"]), f"over {int(stats['months'])} months",
         tone_of(stats["excess_total"])),
        ("Max drawdown", fmt_pct(stats["max_drawdown"]), f"Nifty 50 TRI {fmt_pct(stats['benchmark_max_drawdown'])}", "neg"),
        ("Deflated Sharpe", f"{dsr.deflated:.0%}" if dsr else "—",
         f"P(true Sharpe > 0) after {STRATEGY_TRIALS} trials" if dsr else "too few periods",
         "pos" if dsr and dsr.deflated >= 0.95 else "warn"),
    ]
)
kpi_grid(
    [
        ("Sharpe", f"{stats['sharpe']:.2f}", f"rf {stats['risk_free']:.1%} · Nifty {stats['benchmark_sharpe']:.2f}", ""),
        ("Avg turnover", fmt_pct(stats["avg_turnover"]), "of the book each rebalance", ""),
        ("Costs paid", fmt_pct(stats["total_cost"]), f"gross total {fmt_pct(stats['gross_total_return'])}", ""),
        ("Periods with cash", f"{int(stats['cash_months'])} of {int(stats['periods'])}", "a slot failed the hurdle", ""),
    ]
)
if dsr:
    note(
        f"<b>Deflated Sharpe {dsr.deflated:.0%}</b> (probabilistic Sharpe before deflation {dsr.probabilistic:.0%}): "
        f"the probability that the true monthly Sharpe is above zero after allowing for the best of "
        f"{STRATEGY_TRIALS} zero-edge configurations, which is every strategy setting this page lets anyone try "
        f"({' × '.join(f'{len(v)} {k.lower()}' for k, v in STRATEGY_OPTIONS.items())}). Luck alone would produce "
        f"a monthly Sharpe of {dsr.benchmark_sharpe:.2f}, against {dsr.sharpe:.2f} here, over {dsr.observations} "
        "monthly returns over cash. Below 95% is not evidence of an edge (Bailey &amp; López de Prado 2014).",
        tone="" if dsr.deflated >= 0.95 else "warn",
    )

section("Growth of ₹100", "Net strategy against Nifty 50 TRI, with both drawdowns beneath")
st.plotly_chart(equity_curve(result.equity), width="stretch", config=CHART_CONFIG)

# --------------------------------------------------------------------------- #
# Pre-launch history: the same rules, with and without it
# --------------------------------------------------------------------------- #
other = load_backtest(backtest_config(exclude_backcalculated=include_backfill))
if other.ok:
    pair = {("Included" if include_backfill else "Excluded"): result,
            ("Excluded" if include_backfill else "Included"): other}
    comparison = pd.DataFrame(
        [
            {
                "Back-calculated history": label,
                "Net total return": r.stats["total_return"],
                "Net CAGR": r.stats["cagr"],
                "Net excess vs Nifty": r.stats["excess_total"],
                "Max drawdown": r.stats["max_drawdown"],
                "Deflated Sharpe": (d.deflated if (d := _deflated(r)) else None),
            }
            for label, r in sorted(pair.items())
        ]
    )
    section("With and without back-calculated history", "Same rules; only pre-launch eligibility differs")
    show_table(
        tinted(comparison, ["Net excess vs Nifty"], cap=0.4),
        hide_index=True,
        width="stretch",
        column_config={
            c: st.column_config.NumberColumn(format="percent") for c in comparison.columns if c != "Back-calculated history"
        },
    )

# --------------------------------------------------------------------------- #
# Robustness: every 12-month window, and early versus recent
# --------------------------------------------------------------------------- #
section("Every 12-month window", "A single number depends on when the test started; this does not")
windows = rolling_windows(result, window=max(12 // live_config.rebalance_months, 2))
roll = rolling_summary_stats(windows)
if roll:
    kpi_grid(
        [
            ("Beat Nifty 50", f"{roll['beat_rate']:.0%}", f"of {int(roll['windows'])} rolling windows",
             "pos" if roll["beat_rate"] >= 0.5 else "neg"),
            ("Median excess", fmt_pct(roll["median_excess"]), "the typical window", tone_of(roll["median_excess"])),
            ("Worst window", fmt_pct(roll["worst_excess"]), "largest shortfall", "neg"),
            ("Best window", fmt_pct(roll["best_excess"]), "largest lead", "pos"),
        ]
    )
    left, right = st.columns(2, gap="medium")
    with left:
        st.plotly_chart(excess_distribution(windows), width="stretch", config=CHART_CONFIG)
    with right:
        st.plotly_chart(rolling_excess(windows), width="stretch", config=CHART_CONFIG)
else:
    note("Not enough completed periods yet to form a rolling window.")

section("Early versus recent", "The blended figure hides which half it came from")
split = period_split(result)
if not split.empty:
    halves = split.assign(
        Half=split["half"].map({"early": "Early", "recent": "Recent"}),
        Period=[f"{a:%b %Y} – {b:%b %Y}" for a, b in zip(split["from"], split["to"])],
    )[["Half", "Period", "periods", "strategy", "benchmark", "excess", "cash_periods"]].rename(
        columns={"periods": "Periods", "strategy": "Strategy (net)", "benchmark": "Nifty 50 TRI",
                 "excess": "Excess", "cash_periods": "Periods with cash"}
    )
    show_table(
        tinted(halves, ["Excess"], cap=0.3),
        hide_index=True,
        width="stretch",
        column_config={c: st.column_config.NumberColumn(format="percent")
                       for c in ("Strategy (net)", "Nifty 50 TRI", "Excess", "Periods with cash")},
    )

with st.expander("Month-by-month record", expanded=False):
    ledger = _named(result.monthly)
    st.plotly_chart(monthly_excess(ledger), width="stretch", config=CHART_CONFIG)
    ledger["Month"] = pd.to_datetime(ledger["period_end"]).dt.strftime("%b %Y")
    show_table(
        ledger[["Month", "holdings", "cash_slots", "turnover", "cost", "strategy_return", "benchmark_return",
                "excess_return", "universe", "skipped"]].rename(
            columns={"holdings": "Held", "cash_slots": "Cash", "turnover": "Turnover", "cost": "Cost",
                     "strategy_return": "Strategy (net)", "benchmark_return": "Nifty 50 TRI",
                     "excess_return": "Excess", "universe": "Eligible", "skipped": "Passed over"}),
        hide_index=True,
        width="stretch",
        height=min(40 + 35 * len(ledger), 520),
        column_config={c: st.column_config.NumberColumn(format="percent")
                       for c in ("Turnover", "Cost", "Strategy (net)", "Nifty 50 TRI", "Excess")},
    )
    st.download_button("Download the monthly ledger (CSV)", ledger.to_csv(index=False).encode("utf-8"),
                       file_name="sector_rotation_evidence.csv", mime="text/csv")

# --------------------------------------------------------------------------- #
# What-if: hundreds of configurations, explicitly not validated
# --------------------------------------------------------------------------- #
with st.expander("Parameter Sensitivity (Unvalidated)", expanded=False):
    note(
        f"<b>Multiple-testing warning: every setting here is a what-if, not the strategy.</b> These controls reach "
        f"{STRATEGY_TRIALS} strategy configurations across {EVALUATION_SETTINGS} evaluation settings. On five years "
        "of data some will beat the live rules by luck alone; choosing the best-looking one is fitting this sample. "
        f"The Deflated Sharpe above already counts all {STRATEGY_TRIALS} as trials.",
        tone="warn",
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
    months = None if window == "All" else int(window)
    trial = load_backtest(what_if, months=months, category=category)
    if not trial.ok:
        note(f"<b>Unavailable.</b> {trial.error}", tone="warn")
    else:
        t = trial.stats
        kpi_grid(
            [
                ("Net total return", fmt_pct(t["total_return"]), f"Nifty {fmt_pct(t['benchmark_total_return'])}", ""),
                ("Net excess", fmt_pct(t["excess_total"]), f"live rules {fmt_pct(stats['excess_total'])}",
                 tone_of(t["excess_total"])),
                ("Max drawdown", fmt_pct(t["max_drawdown"]), "", "neg"),
                ("Avg turnover", fmt_pct(t["avg_turnover"]), "", ""),
            ]
        )
        st.plotly_chart(equity_curve(trial.equity), width="stretch", config=CHART_CONFIG, key="what_if_curve")

    if st.toggle("Also test six score specifications", value=False, key="wi_scores"):
        grid = load_sensitivity(what_if, months=months, category=category)
        if grid.empty:
            note("Not enough history to test alternative score specifications.")
        else:
            show_table(
                grid.rename(columns={"weighting": "Score specification", "total_return": "Net total",
                                     "excess": "Net excess", "max_drawdown": "Max DD", "hit_rate": "Hit rate",
                                     "turnover": "Turnover"}),
                hide_index=True,
                width="stretch",
                column_config={c: st.column_config.NumberColumn(format="percent")
                               for c in ("Net total", "Net excess", "Max DD", "Hit rate", "Turnover")},
            )
            spread = float(grid["excess"].max() - grid["excess"].min())
            note(
                f"<b>The score specification moves the answer by {spread:.0%}.</b> That spread is the parameter, not "
                "the strategy. The live rules weight the four segments equally because that assumes nothing about "
                "which horizon predicts best.",
                tone="warn",
            )

section("How to read this")
note(
    "<b>Method.</b> At every month-end close the same <code>construct_target_portfolio</code> that builds the "
    "Portfolio page decides the holdings from prices up to that close. Trades fill at the next session's close and "
    f"pay {live_config.cost_bps_per_side:g} bps per side on the weight traded. Cash earns what the liquid fund's NAV "
    f"earned between fills ({live_config.risk_free_rate_annual:.1%} before its history). Only completed months count."
)
note(
    "<b>What this is not.</b> Tax, an ETF's premium to NAV and impact on thin funds are not modelled. These are index "
    "levels; a fund lags by its tracking difference. Funds that launched and later closed are absent. The universe was "
    "chosen in 2026 and several indices launched inside the window with back-calculated history. Treat this as a check "
    "on the rules, not as evidence of an edge.",
    tone="warn",
)
