from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import CHART_CONFIG, equity_curve, monthly_excess, rolling_excess
from app.components.theme import mobile_nav, fmt_pct, inject_theme, kpi_strip, note, page_header, section
from app.data import load_backtest, load_decisions, load_index_panel, load_sensitivity

inject_theme()
mobile_nav("Backtest")
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
# Three questions, asked in order. Naming them by the question keeps them apart:
# "investable" vs "investable + BUY" said nothing about what each one measures.
MODES = {
    "All indices": (False, False),
    "Buyable only": (True, False),
    "Buyable + entry rule": (True, True),
}
mode = st.segmented_control(
    "Universe",
    list(MODES),
    default="Buyable + entry rule",
    key="bt_mode",
)
note(
    "<b>All indices</b> — ranks all 47 indices and buys the top ones, whether or not a fund "
    "existed. It measures <i>the signal</i>: does momentum pick strong sectors?<br>"
    "<b>Buyable only</b> — same ranking, but a pick must have had a real ETF or index fund "
    "trading on that date. It measures <i>the portfolio</i>: could you have owned it?<br>"
    "<b>Buyable + entry rule</b> — and the exposure must also satisfy the live BUY rule "
    "(Leading, RS ratio above 1, positive RS velocity). It measures <i>what this app would "
    "actually have told you to do</i>.<br>"
    "Each step is stricter than the last, so the return falls at each one. The gap between the "
    "first and the last is the part of the headline result you could never have captured."
)

investable_only, require_buy = MODES.get(mode or "Buyable + entry rule", (True, True))

controls = st.columns(3)
top_n = controls[0].segmented_control(
    "Hold top", [1, 2, 3, 5], default=2, key="bt_topn",
    help="Exposures held, equally weighted, until the next rebalance.",
)
hold_months = controls[1].segmented_control(
    "Holding period", [1, 2, 3, 6], default=1, key="bt_hold",
    help="Months a decision is left alone before the ranking is revisited.",
)
months = controls[2].segmented_control(
    "History window", [12, 24, 36, 60], default=60, key="bt_months",
    help="Months of price history to draw on. The ranking needs a full 12-month history "
    "before it can pick anything, so the first year of the window is warm-up and produces "
    "fewer months of actual returns.",
)

extra = st.columns(3)
category = extra[0].segmented_control(
    "Which universe", ["All", "Sectors", "Themes"], default="All", key="bt_category",
    help="Sectors and themes rotate on different cycles, so they can be tested apart. "
    "Note that the combined universe is not the average of the two — breadth itself helps.",
)
max_rank_depth = extra[1].segmented_control(
    "Substitute down to rank", [2, 3, 5], default=3, key="bt_depth",
    help="When the top-ranked exposure cannot be bought, how far down the ranking to look "
    "before the slot goes to cash instead.",
)
absolute_filter = extra[2].toggle(
    "Absolute momentum filter (dual momentum)", value=True, key="bt_abs",
    help="Only hold an exposure whose own 12-month return is positive; otherwise that slot "
         "sits in cash at 0%.",
)

result = load_backtest(
    top_n=top_n or 2,
    months=months or 60,
    hold_months=hold_months or 1,
    absolute_filter=absolute_filter,
    investable_only=investable_only,
    require_buy=require_buy,
    max_rank_depth=max_rank_depth or 3,
    category=category or "All",
)
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


def _pretty_reasons(text: str) -> str:
    """Turn 'defence:no vehicle; it:not BUY' into readable names."""
    if not text:
        return ""
    parts = []
    for item in str(text).split(";"):
        item = item.strip()
        if not item:
            continue
        exposure_id, _, reason = item.partition(":")
        parts.append(f"{NAMES.get(exposure_id.strip(), exposure_id.strip())} — {reason.strip()}")
    return "; ".join(parts)


def _named(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["holdings"] = out["holdings"].map(_pretty)
    if "skipped" in out.columns:
        out["skipped"] = out["skipped"].map(_pretty_reasons)
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
        (
            "Periods ahead of Nifty",
            f"{stats['hit_rate'] * 100:.0f}%",
            f"{int(stats['periods'])} × {int(stats['hold_months'])}M periods",
            "",
        ),
        ("Positive periods", f"{stats['win_rate'] * 100:.0f}%", "strategy return > 0", ""),
        ("Volatility", fmt_pct(stats["volatility"]), f"Nifty {fmt_pct(stats['benchmark_volatility'])}", ""),
        ("Avg turnover", fmt_pct(stats["avg_turnover"]), "of the book each rebalance", ""),
    ]
)

warmup = stats.get("warmup_months", 0.0)
if warmup > 0:
    note(
        f"<b>{int(stats['requested_months'])} months of history produced "
        f"{int(stats['months'])} months of returns.</b> The ranking needs a full 12-month "
        "history before it can choose anything, so the opening "
        f"{int(warmup)} months of the window are warm-up and hold nothing. Every figure "
        "here is measured over the "
        f"{int(stats['months'])} months that followed."
    )

cash_periods = float((result.monthly["cash_slots"] > 0).mean())
if investable_only and cash_periods > 0:
    note(
        f"<b>{cash_periods:.0%} of periods left at least one slot in cash</b> because the "
        "top-ranked exposures had no fund you could have bought at the time. Investability is "
        "judged from each vehicle's own price history, not from the fact that it exists today — "
        "most of these ETFs and index funds launched in 2024–25.",
        tone="amber",
    )
if not investable_only:
    note(
        "<b>All indices includes exposures with no buyable vehicle.</b> It measures the signal, "
        "not a portfolio you could have held. Switch to <i>Investable only</i> for what was "
        "actually purchasable on each date.",
        tone="amber",
    )

section("Growth of ₹100", "Strategy against Nifty 50 over the same period")
st.plotly_chart(equity_curve(result.equity), width="stretch", config=CHART_CONFIG)

section("Monthly excess return", "Green months beat Nifty 50; hover for the holdings")
st.plotly_chart(monthly_excess(_named(result.monthly)), width="stretch", config=CHART_CONFIG)

section("Every 12-month window", "One number depends on when the test started; this does not")
from src.quantitative.backtest import rolling_summary_stats, rolling_windows

windows = rolling_windows(result, window=max(12 // max(hold_months or 1, 1), 2))
roll = rolling_summary_stats(windows)
if roll:
    kpi_strip(
        [
            (
                "Beat Nifty 50",
                f"{roll['beat_rate']:.0%}",
                f"of {int(roll['windows'])} rolling windows",
                "buy" if roll["beat_rate"] >= 0.5 else "red",
            ),
            ("Made money", f"{roll['positive_rate']:.0%}", "windows with a positive return", ""),
            (
                "Median excess",
                fmt_pct(roll["median_excess"]),
                "typical window vs Nifty 50",
                "buy" if roll["median_excess"] > 0 else "red",
            ),
            ("Worst window", fmt_pct(roll["worst_excess"]), "largest shortfall", "amber"),
        ]
    )
    st.plotly_chart(rolling_excess(windows), width="stretch", config=CHART_CONFIG)
    note(
        f"A single headline figure is one draw. Across <b>{int(roll['windows'])}</b> overlapping "
        f"windows the strategy was ahead of Nifty 50 in <b>{roll['beat_rate']:.0%}</b> of them, "
        f"with a median excess of <b>{fmt_pct(roll['median_excess'])}</b> and a worst window of "
        f"<b>{fmt_pct(roll['worst_excess'])}</b>. How often it worked matters more than how much "
        "it made in the one window that happens to end today.",
        tone="" if roll["beat_rate"] >= 0.5 else "amber",
    )
else:
    note("Not enough completed periods yet to form a rolling window.")

section("Early versus recent", "The blended figure hides which half it came from")
from src.quantitative.backtest import period_split

split = period_split(result)
if not split.empty:
    LABELS = {"early": "Early", "recent": "Recent"}
    st.dataframe(
        split.assign(
            Half=split["half"].map(LABELS),
            Period=[f"{a:%b %Y} – {b:%b %Y}" for a, b in zip(split["from"], split["to"])],
        )[["Half", "Period", "periods", "strategy", "benchmark", "excess", "cash_periods"]]
        .rename(columns={"periods": "Periods", "strategy": "Strategy",
                         "benchmark": "Nifty 50", "excess": "Excess",
                         "cash_periods": "Periods with cash"}),
        hide_index=True,
        width="stretch",
        column_config={
            "Half": st.column_config.TextColumn(width="small"),
            "Period": st.column_config.TextColumn(width="medium"),
            "Periods": st.column_config.NumberColumn(width="small"),
            "Strategy": st.column_config.NumberColumn(format="percent", width="small"),
            "Nifty 50": st.column_config.NumberColumn(format="percent", width="small"),
            "Excess": st.column_config.NumberColumn(format="percent", width="small"),
            "Periods with cash": st.column_config.NumberColumn(
                format="percent", width="small",
                help="Share of periods where at least one slot could not be filled",
            ),
        },
    )
    if len(split) == 2 and investable_only:
        early, recent = split.iloc[0], split.iloc[1]
        note(
            f"<b>The two halves say different things.</b> Early on, {early['cash_periods']:.0%} of "
            f"periods left a slot in cash — only a dozen exposures had a fund at all — and the "
            f"strategy trailed by {abs(early['excess']):.1%}. Recently, with cash down to "
            f"{recent['cash_periods']:.0%}, it is {recent['excess']:+.1%} against Nifty 50. "
            "The early stretch mostly measures a market where sector funds barely existed, not a "
            "failing signal — but the recent stretch is only "
            f"{int(recent['periods'])} periods, far too few to call an edge.",
            tone="amber",
        )

section("Does the answer depend on the weighting?", "Same test, different composite weights")
# Six full backtests: run it only when asked, not on every page load.
if not st.toggle("Test six weightings", value=False, key="bt_sensitivity"):
    st.caption(
        "Runs the same backtest under six composite weightings to show how much of the result "
        "is the strategy and how much is the parameter."
    )
    st.stop()

sensitivity = load_sensitivity(
    top_n=top_n or 2, months=months or 60, hold_months=hold_months or 1,
    absolute_filter=absolute_filter, investable_only=investable_only,
    require_buy=require_buy, max_rank_depth=max_rank_depth or 3,
    category=category or "All",
)
if sensitivity.empty:
    note("Not enough history to test alternative weightings.")
else:
    st.dataframe(
        sensitivity.rename(columns={
            "weighting": "Weighting", "total_return": "Strategy", "excess": "Excess",
            "max_drawdown": "Max DD", "hit_rate": "Hit rate", "turnover": "Turnover"}),
        hide_index=True, width="stretch",
        column_config={
            "Weighting": st.column_config.TextColumn(width="medium"),
            "Strategy": st.column_config.NumberColumn(format="percent", width="small"),
            "Excess": st.column_config.NumberColumn(format="percent", width="small"),
            "Max DD": st.column_config.NumberColumn(format="percent", width="small"),
            "Hit rate": st.column_config.NumberColumn(format="percent", width="small"),
            "Turnover": st.column_config.NumberColumn(format="percent", width="small"),
        },
    )
    spread = float(sensitivity["excess"].max() - sensitivity["excess"].min())
    note(
        f"<b>The weighting moves the answer by {spread:.0%}.</b> That spread comes from a "
        "parameter choice, not from the strategy — so treat any single row as noise, and do not "
        "pick the best one. Choosing a weighting because it won this sample is fitting "
        "the sample. The live board uses equal weights because that assumes nothing about which "
        "horizon predicts best, which is the honest default when the record is this short.",
        tone="amber",
    )

section("Month-by-month record")
ledger = _named(result.monthly)
ledger["Month"] = pd.to_datetime(ledger["period_end"]).dt.strftime("%b %Y")
ledger = ledger[
    ["Month", "holdings", "cash_slots", "strategy_return", "benchmark_return",
     "excess_return", "universe", "skipped"]
].rename(
    columns={
        "holdings": "Held",
        "cash_slots": "Cash",
        "strategy_return": "Strategy",
        "benchmark_return": "Nifty 50",
        "excess_return": "Excess",
        "universe": "Eligible",
        "skipped": "Passed over",
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
        "Cash": st.column_config.NumberColumn(
            width="small", help="Slots left in cash because nothing qualified"
        ),
        "Eligible": st.column_config.NumberColumn(
            width="small", help="Exposures with enough history to be ranked that period"
        ),
        "Passed over": st.column_config.TextColumn(
            width="medium", help="Higher-ranked exposures skipped, and why"
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
    "<b>Method.</b> On the last trading day of every "
    f"{int(hold_months or 1)}-month period the universe is ranked by composite momentum "
    "Z-score using only prices up to that day. The top "
    f"{top_n or 2} qualifying exposures are held, equally weighted, until the next rebalance. "
    "The return of a decision is measured entirely after the decision was made."
    + (
        " A pick must have had a buyable vehicle on that date, judged from the vehicle's own "
        f"price history. When the top name fails, the next is taken, down to rank "
        f"{max_rank_depth or 3}; past that the slot goes to cash."
        if investable_only
        else ""
    )
    + (" A pick must also satisfy the live BUY rule: Leading stage, RS ratio above 1, positive "
       "RS velocity." if require_buy else "")
    + (
        " With the absolute-momentum filter on, an exposure whose own trailing 12-month return "
        "is negative is skipped and that slot earns 0% in cash."
        if absolute_filter
        else " The absolute-momentum filter is off."
    )
)
note(
    "<b>What this is not.</b> Transaction costs are deliberately zero — no brokerage, spread, "
    "STT, expense ratio or tax — so a real book would earn less, and more so at higher turnover. "
    "These are index levels, and an index cannot be bought directly; the fund tracking it lags by "
    "its tracking difference. Funds that launched and later closed are absent, so even the "
    "investable universe carries some survivorship bias. Index reconstitution is embedded in the "
    "published series. Treat this as a sanity check on the signal, not as evidence of an edge.",
    tone="amber",
)
