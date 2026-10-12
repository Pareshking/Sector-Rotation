from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import (
    CHART_CONFIG,
    equity_curve,
    monthly_excess,
    rolling_excess,
)
from app.components.navigation import mobile_nav
from app.components.theme import (
    fmt_pct,
    inject_theme,
    kpi_strip,
    note,
    page_header,
    section,
)
from app.data import (
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
from src.quantitative.backtest import (
    period_split,
    rolling_summary_stats,
    rolling_windows,
)
from src.quantitative.stats import deflated_sharpe

inject_theme()
mobile_nav("Evidence")
page_header(
    "Walk-forward evidence",
    "Evidence",
    "The live rules replayed over every completed month, net of costs, with cash earning what the "
    "liquid fund earned. Point-in-time, not out-of-sample: the rules were specified after studying "
    "this same window.",
)

panel, benchmark = load_index_panel()
if panel.empty or benchmark.empty:
    note(
        "<b>No canonical index price panel is available yet.</b> The evidence needs "
        "<code>data/processed/index_prices.parquet</code>, which the data pipeline writes on its "
        "next run.",
        tone="amber",
    )
    st.stop()

live_config = strategy_config()
decisions = load_decisions()
NAMES = decisions.set_index("exposure_id")["exposure"].to_dict() if not decisions.empty else {}


def _pretty(holdings: str) -> str:
    if not holdings or holdings == "cash":
        return "cash"
    return ", ".join(NAMES.get(part.strip(), part.strip()) for part in str(holdings).split(","))


def _pretty_reasons(text: str) -> str:
    """Turn 'defence:slots full; it:fails cash hurdle' into readable names."""
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


def _deflated(result, trials: int):
    """Deflated Sharpe of monthly returns in excess of what cash earned the same month."""
    monthly = result.monthly
    return deflated_sharpe(monthly["strategy_return"] - monthly["cash_return"], trials)


# --------------------------------------------------------------------------- #
# The live strategy, first
# --------------------------------------------------------------------------- #
include_backfill = st.toggle(
    "Include back-calculated index history",
    value=live_config.backfill_policy == "include",
    key="ev_backfill",
    help="Before its NSE launch date an index's values were computed after the fact and could not "
    "have been traded. Off: an index is not eligible before its launch.",
)
config = backtest_config(exclude_backcalculated=not include_backfill)
result = load_backtest(config)
if not result.ok:
    note(f"<b>Evidence unavailable.</b> {result.error}", tone="amber")
    st.stop()
stats = result.stats
dsr = _deflated(result, STRATEGY_TRIALS)

kpi_strip(
    [
        ("Net CAGR", fmt_pct(stats["cagr"]), f"Nifty 50 TRI {fmt_pct(stats['benchmark_cagr'])}",
         "buy" if stats["cagr"] > stats["benchmark_cagr"] else "red"),
        ("Net total return", fmt_pct(stats["total_return"]), f"Nifty 50 TRI {fmt_pct(stats['benchmark_total_return'])}", ""),
        ("Net excess vs Nifty", fmt_pct(stats["excess_total"]), f"over {int(stats['months'])} months",
         "buy" if stats["excess_total"] > 0 else "red"),
        ("Max drawdown", fmt_pct(stats["max_drawdown"]), f"Nifty 50 TRI {fmt_pct(stats['benchmark_max_drawdown'])}", "amber"),
        (
            "Deflated Sharpe",
            f"{dsr.deflated:.0%}" if dsr else "—",
            f"P(true Sharpe > 0) after {STRATEGY_TRIALS} trials" if dsr else "too few periods",
            "buy" if dsr and dsr.deflated >= 0.95 else "red",
        ),
    ]
)
kpi_strip(
    [
        ("Sharpe", f"{stats['sharpe']:.2f}", f"rf {stats['risk_free']:.1%} · Nifty {stats['benchmark_sharpe']:.2f}", ""),
        ("Avg turnover", fmt_pct(stats["avg_turnover"]), "of the book each rebalance", ""),
        ("Costs paid", fmt_pct(stats["total_cost"]),
         f"{stats['cost_bps_per_side']:g} bps per side · gross {fmt_pct(stats['gross_total_return'])}", ""),
        ("Periods with cash", f"{int(stats['cash_months'])} of {int(stats['periods'])}", "a slot failed the hurdle", ""),
    ]
)
if dsr:
    note(
        f"<b>Deflated Sharpe {dsr.deflated:.0%}</b> (probabilistic Sharpe before deflation "
        f"{dsr.probabilistic:.0%}). It is the probability that the true monthly Sharpe ratio is above "
        f"zero after allowing for the best result {STRATEGY_TRIALS} zero-edge configurations would "
        f"produce by luck — the {STRATEGY_TRIALS} strategy configurations this page lets anyone try "
        f"({' × '.join(f'{len(v)} {k.lower()}' for k, v in STRATEGY_OPTIONS.items())}). "
        f"Measured on {dsr.observations} monthly returns over cash; luck alone would produce a monthly "
        f"Sharpe of {dsr.benchmark_sharpe:.2f}, against {dsr.sharpe:.2f} here. Below 95% is not "
        "evidence of an edge (Bailey & López de Prado 2014).",
        tone="" if dsr.deflated >= 0.95 else "amber",
    )

# With and without back-calculated history, side by side.
other = load_backtest(backtest_config(exclude_backcalculated=include_backfill))
if other.ok:
    pair = {("Included" if include_backfill else "Excluded"): result, ("Excluded" if include_backfill else "Included"): other}
    comparison = pd.DataFrame(
        [
            {
                "Back-calculated history": label,
                "Net total return": r.stats["total_return"],
                "Net CAGR": r.stats["cagr"],
                "Net excess vs Nifty": r.stats["excess_total"],
                "Max drawdown": r.stats["max_drawdown"],
                "Deflated Sharpe": (_deflated(r, STRATEGY_TRIALS).deflated if _deflated(r, STRATEGY_TRIALS) else None),
            }
            for label, r in sorted(pair.items())
        ]
    )
    section("With and without back-calculated history", "The same rules; only pre-launch eligibility differs")
    st.dataframe(
        comparison,
        hide_index=True,
        width="stretch",
        column_config={
            column: st.column_config.NumberColumn(format="percent", width="small")
            for column in comparison.columns
            if column != "Back-calculated history"
        },
    )

section("Growth of ₹100", "Net strategy against Nifty 50 TRI over the same periods")
st.plotly_chart(equity_curve(result.equity), width="stretch", config=CHART_CONFIG)

section("Every 12-month window", "One number depends on when the test started; this does not")
windows = rolling_windows(result, window=max(12 // live_config.rebalance_months, 2))
roll = rolling_summary_stats(windows)
if roll:
    kpi_strip(
        [
            ("Beat Nifty 50", f"{roll['beat_rate']:.0%}", f"of {int(roll['windows'])} rolling windows",
             "buy" if roll["beat_rate"] >= 0.5 else "red"),
            ("Median excess", fmt_pct(roll["median_excess"]), "typical window vs Nifty 50",
             "buy" if roll["median_excess"] > 0 else "red"),
            ("Worst window", fmt_pct(roll["worst_excess"]), "largest shortfall", "amber"),
            ("Best window", fmt_pct(roll["best_excess"]), "largest lead", ""),
        ]
    )
    distribution = go.Figure(
        go.Histogram(
            x=windows["excess"], nbinsx=20, marker=dict(color="#4338CA", line=dict(width=0)),
            hovertemplate="Excess %{x:.0%}<br>%{y} windows<extra></extra>",
        )
    )
    distribution.add_vline(x=0, line=dict(color="#94A3B8", width=1.5))
    distribution.update_layout(
        height=240, margin=dict(l=10, r=12, t=16, b=10), paper_bgcolor="white", plot_bgcolor="white",
        xaxis=dict(title="Excess over Nifty 50 in the 12 months", tickformat=".0%", gridcolor="#EEF2F7"),
        yaxis=dict(title="Windows", gridcolor="#EEF2F7"), bargap=0.05,
    )
    cols = st.columns(2)
    cols[0].plotly_chart(distribution, width="stretch", config=CHART_CONFIG)
    cols[1].plotly_chart(rolling_excess(windows), width="stretch", config=CHART_CONFIG)
else:
    note("Not enough completed periods yet to form a rolling window.")

section("Early versus recent", "The blended figure hides which half it came from")
split = period_split(result)
if not split.empty:
    st.dataframe(
        split.assign(
            Half=split["half"].map({"early": "Early", "recent": "Recent"}),
            Period=[f"{a:%b %Y} – {b:%b %Y}" for a, b in zip(split["from"], split["to"])],
        )[["Half", "Period", "periods", "strategy", "benchmark", "excess", "cash_periods"]].rename(
            columns={"periods": "Periods", "strategy": "Strategy (net)", "benchmark": "Nifty 50 TRI",
                     "excess": "Excess", "cash_periods": "Periods with cash"}
        ),
        hide_index=True,
        width="stretch",
        column_config={
            c: st.column_config.NumberColumn(format="percent", width="small")
            for c in ("Strategy (net)", "Nifty 50 TRI", "Excess", "Periods with cash")
        },
    )

with st.expander("Month-by-month record", expanded=False):
    st.plotly_chart(monthly_excess(_named(result.monthly)), width="stretch", config=CHART_CONFIG)
    ledger = _named(result.monthly)
    ledger["Month"] = pd.to_datetime(ledger["period_end"]).dt.strftime("%b %Y")
    st.dataframe(
        ledger[["Month", "holdings", "cash_slots", "turnover", "cost", "strategy_return", "benchmark_return",
                "excess_return", "universe", "skipped"]].rename(
            columns={"holdings": "Held", "cash_slots": "Cash", "turnover": "Turnover", "cost": "Cost",
                     "strategy_return": "Strategy (net)", "benchmark_return": "Nifty 50 TRI",
                     "excess_return": "Excess", "universe": "Eligible", "skipped": "Passed over"}
        ),
        hide_index=True,
        width="stretch",
        height=min(56 + 35 * len(ledger), 520),
        column_config={
            c: st.column_config.NumberColumn(format="percent", width="small")
            for c in ("Turnover", "Cost", "Strategy (net)", "Nifty 50 TRI", "Excess")
        },
    )
    st.download_button(
        "Download the monthly ledger (CSV)",
        _named(result.monthly).to_csv(index=False).encode("utf-8"),
        file_name="sector_rotation_evidence.csv",
        mime="text/csv",
    )

# --------------------------------------------------------------------------- #
# What-if: thousands of configurations, explicitly not validated
# --------------------------------------------------------------------------- #
with st.expander("Parameter Sensitivity (Unvalidated)", expanded=False):
    note(
        f"<b>Every setting here is a what-if, not the strategy.</b> These controls reach "
        f"{STRATEGY_TRIALS} strategy configurations across {EVALUATION_SETTINGS} evaluation settings. "
        "On five years of data some of them will beat the live rules by luck alone; picking the "
        "best-looking one is fitting this sample, and the Deflated Sharpe above already counts them "
        "as trials.",
        tone="amber",
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
        note(f"<b>Unavailable.</b> {trial.error}", tone="amber")
    else:
        t = trial.stats
        kpi_strip(
            [
                ("Net total return", fmt_pct(t["total_return"]), f"Nifty {fmt_pct(t['benchmark_total_return'])}", ""),
                ("Net excess", fmt_pct(t["excess_total"]), f"live rules {fmt_pct(stats['excess_total'])}", ""),
                ("Max drawdown", fmt_pct(t["max_drawdown"]), "", "amber"),
                ("Avg turnover", fmt_pct(t["avg_turnover"]), "", ""),
            ]
        )
        st.plotly_chart(equity_curve(trial.equity), width="stretch", config=CHART_CONFIG, key="what_if_curve")

    if st.toggle("Also test six score specifications", value=False, key="wi_scores"):
        grid = load_sensitivity(what_if, months=months, category=category)
        if grid.empty:
            note("Not enough history to test alternative score specifications.")
        else:
            st.dataframe(
                grid.rename(columns={"weighting": "Score specification", "total_return": "Net total",
                                     "excess": "Net excess", "max_drawdown": "Max DD", "hit_rate": "Hit rate",
                                     "turnover": "Turnover"}),
                hide_index=True,
                width="stretch",
                column_config={
                    c: st.column_config.NumberColumn(format="percent", width="small")
                    for c in ("Net total", "Net excess", "Max DD", "Hit rate", "Turnover")
                },
            )
            spread = float(grid["excess"].max() - grid["excess"].min())
            note(
                f"<b>The score specification moves the answer by {spread:.0%}.</b> That spread is the "
                "parameter, not the strategy. v1.1 weights the four segments equally because that assumes "
                "nothing about which horizon predicts best.",
                tone="amber",
            )

section("How to read this")
note(
    "<b>Method.</b> At every month-end close the same <code>construct_target_portfolio</code> that "
    "builds the Portfolio page decides the holdings using only prices up to that close. Trades fill at "
    f"the next session's close and pay {live_config.cost_bps_per_side:g} bps per side on the weight "
    "traded. Cash earns what the liquid fund's NAV earned between fills "
    f"({live_config.risk_free_rate_annual:.1%} before its history). Only completed months count."
)
note(
    "<b>What this is not.</b> Tax, an ETF's premium to NAV and impact on thin funds are not modelled. "
    "These are index levels; a fund lags by its tracking difference. Funds that launched and later "
    "closed are absent. The universe was chosen in 2026 and several indices launched within the "
    "window with back-calculated history. Treat this as a check on the rules, not as evidence of an edge.",
    tone="amber",
)
