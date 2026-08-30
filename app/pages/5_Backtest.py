from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import CHART_CONFIG, equity_curve, monthly_excess
from app.components.theme import fmt_pct, inject_theme, kpi_strip, note, page_header, section
from app.data import load_backtest, load_decisions, load_index_panel

inject_theme()
page_header(
    "Out of Sample",
    "Backtest",
    "Rank the universe at each month end, hold the top exposures for the next month, repeat. "
    "Ranking uses only data available on the rebalance date, and is computed by the same code "
    "that produces the live dashboard.",
)

panel, benchmark = load_index_panel()
if panel.empty or benchmark.empty:
    note(
        "<b>No canonical index price panel is available yet.</b> The backtest needs "
        "<code>data/processed/index_prices.parquet</code>, which the data pipeline writes on its "
        "next run. Everything else in the app works without it.",
        tone="amber",
    )
    st.stop()

section("Strategy")
controls = st.columns([1.15, 1.05, 1.3])
top_n = controls[0].segmented_control(
    "Hold top", [1, 2, 3, 5], default=2, key="bt_topn",
    help="Number of exposures held, equally weighted, until the next month end.",
)
months = controls[1].segmented_control(
    "Window", [12, 24, 36, 60], default=12, key="bt_months",
    help="Backtest length in months. Twelve is the minimum.",
)
absolute_filter = controls[2].toggle(
    "Absolute momentum filter (dual momentum)",
    value=True,
    key="bt_abs",
    help="Only hold an exposure whose own 12-month return is positive; otherwise that slot sits "
         "in cash at 0%.",
)

result = load_backtest(top_n=top_n or 2, months=months or 12, absolute_filter=absolute_filter)
if not result.ok:
    note(f"<b>Backtest unavailable.</b> {result.error}", tone="amber")
    st.stop()

# The price panel is keyed by exposure_id; show the names people recognise.
decisions = load_decisions()
NAMES = decisions.set_index("exposure_id")["exposure"].to_dict() if not decisions.empty else {}


def _pretty(holdings: str) -> str:
    if not holdings or holdings == "cash":
        return "cash"
    return ", ".join(NAMES.get(part.strip(), part.strip()) for part in str(holdings).split(","))


def _named(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["holdings"] = out["holdings"].map(_pretty)
    return out


stats = result.stats
beat = stats["total_return"] >= stats["benchmark_total_return"]
kpi_strip(
    [
        (
            f"Strategy · {int(stats['months'])}M",
            fmt_pct(stats["total_return"]),
            f"CAGR {fmt_pct(stats['cagr'])}",
            "buy" if stats["total_return"] >= 0 else "red",
        ),
        (
            "Nifty 50",
            fmt_pct(stats["benchmark_total_return"]),
            f"CAGR {fmt_pct(stats['benchmark_cagr'])}",
            "",
        ),
        (
            "Excess",
            fmt_pct(stats["excess_total"]),
            "strategy minus benchmark",
            "buy" if beat else "red",
        ),
        (
            "Max drawdown",
            fmt_pct(stats["max_drawdown"]),
            f"Nifty 50 {fmt_pct(stats['benchmark_max_drawdown'])}",
            "amber",
        ),
    ]
)
kpi_strip(
    [
        ("Months ahead of Nifty", f"{stats['hit_rate'] * 100:.0f}%", "monthly hit rate", ""),
        ("Positive months", f"{stats['win_rate'] * 100:.0f}%", "strategy return > 0", ""),
        ("Volatility", fmt_pct(stats["volatility"]), f"Nifty {fmt_pct(stats['benchmark_volatility'])}", ""),
        ("Avg turnover", fmt_pct(stats["avg_turnover"]), "of the book each month", ""),
    ]
)

section("Growth of ₹100", "Strategy against Nifty 50 over the same months")
st.plotly_chart(equity_curve(result.equity), width="stretch", config=CHART_CONFIG)

section("Monthly excess return", "Green months beat Nifty 50; hover for the holdings")
st.plotly_chart(monthly_excess(_named(result.monthly)), width="stretch", config=CHART_CONFIG)

section("Month-by-month record")
ledger = _named(result.monthly)
ledger["Month"] = pd.to_datetime(ledger["period_end"]).dt.strftime("%b %Y")
ledger = ledger[
    ["Month", "holdings", "strategy_return", "benchmark_return", "excess_return", "universe"]
].rename(
    columns={
        "holdings": "Held",
        "strategy_return": "Strategy",
        "benchmark_return": "Nifty 50",
        "excess_return": "Excess",
        "universe": "Eligible",
    }
)
st.dataframe(
    ledger,
    hide_index=True,
    width="stretch",
    height=min(56 + 35 * len(ledger), 520),
    column_config={
        "Month": st.column_config.TextColumn(width="small"),
        "Held": st.column_config.TextColumn(width="medium"),
        "Strategy": st.column_config.NumberColumn(format="percent", width="small"),
        "Nifty 50": st.column_config.NumberColumn(format="percent", width="small"),
        "Excess": st.column_config.NumberColumn(format="percent", width="small"),
        "Eligible": st.column_config.NumberColumn(
            width="small", help="Exposures with enough history to be ranked that month"
        ),
    },
)

st.download_button(
    "Download the monthly ledger (CSV)",
    _named(result.monthly).to_csv(index=False).encode("utf-8"),
    file_name="sector_rotation_backtest.csv",
    mime="text/csv",
)

section("How to read this")
note(
    "<b>Method.</b> On the last trading day of each month the universe is ranked by the composite "
    "momentum Z-score using only prices up to that day. The top "
    f"{top_n or 2} exposures are held, equally weighted, until the next month end. The return of a "
    "decision is measured entirely after the decision was made."
    + (
        " With the absolute-momentum filter on, an exposure is skipped when its own trailing "
        "12-month return is negative, and that slot earns 0% in cash."
        if absolute_filter
        else " The absolute-momentum filter is off, so the top-ranked exposures are held even in a "
        "falling market."
    )
)
note(
    "<b>What this is not.</b> These are index levels, not fund returns: no brokerage, spread, "
    "STT, expense ratio, tracking error or tax is deducted, and an index cannot be bought "
    "directly — the ETF that implements it will lag. The eligible universe grows over time as "
    "newer indices reach a full 12-month history, so early months are chosen from a smaller set. "
    "Index reconstitution is embedded in the published series. A 12-month sample is far too short "
    "to distinguish skill from luck; treat it as a sanity check on the signal, not as evidence of "
    "an edge.",
    tone="amber",
)
