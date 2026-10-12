from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
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
from app.components.theme import (
    fmt_pct,
    inject_theme,
    kpi_strip,
    mobile_nav,
    note,
    page_header,
    section,
)
from app.data import (
    backtest_config,
    load_backtest,
    load_decisions,
    load_index_panel,
    load_sensitivity,
    strategy_config,
)

inject_theme()
mobile_nav("Backtest")
page_header(
    "Walk-Forward Backtest",
    "Backtest",
    "Every month-end decision below is made by the same function that builds the dashboard's "
    "target portfolio, using only prices up to that close; trades fill at the next session's "
    "close and pay the configured cost. This is point-in-time, not out-of-sample: strategy v1.0 "
    "was specified after studying this same window, so no result here is evidence in the way an "
    "untouched holdout would be.",
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
live_config = strategy_config()
MODES = {
    f"Strategy v{live_config.version} (buyable)": True,
    "All indices (signal only)": False,
}
live_mode = next(iter(MODES))
mode = st.segmented_control("Universe", list(MODES), default=live_mode, key="bt_mode")
investable_only = MODES.get(mode or live_mode, True)
note(
    f"<b>Strategy v{live_config.version}</b> — the live rules: a pick must have had a real ETF or "
    "index fund with a price on that date. This is the portfolio the dashboard shows.<br>"
    "<b>All indices</b> — the same rules over all 47 indices, whether or not a fund existed. It "
    "measures <i>the signal</i>, not a portfolio anyone could have held. The gap between the two "
    "is the part of the headline you could never have captured."
)

controls = st.columns(3)
top_n = controls[0].segmented_control(
    "Hold top N", [1, 2, 3, 5], default=live_config.target_holdings_n, key="bt_topn",
    help="Slots in the book, each 1/N. New entries must rank within the top N.",
)
buffer_choice = controls[1].segmented_control(
    "Retention buffer", ["M = 2N", "Off (M = N)"],
    default="M = 2N" if live_config.retention_buffer_m == 2 * live_config.target_holdings_n else "Off (M = N)",
    key="bt_buffer",
    help="A holding is kept while its rank stays within M. v1.0 uses M = 4 with N = 2.",
)
hold_months = controls[2].segmented_control(
    "Holding period", [1, 2, 3, 6], default=live_config.rebalance_months, key="bt_hold",
    help="Months a decision is left alone before it is revisited.",
)

extra = st.columns(3)
months_choice = extra[0].segmented_control(
    "History window", ["All", 24, 36, 48], default="All", key="bt_months",
    help="Months of history to draw on. The score needs a full 12-month history before it can "
    "pick anything, so the first year of the data is warm-up and holds nothing. 'All' is the "
    "window the live portfolio runs over.",
)
category = extra[1].segmented_control(
    "Which universe", ["All", "Sectors", "Themes"], default="All", key="bt_category",
    help="Sectors and themes rotate on different cycles, so they can be tested apart. "
    "Note that the combined universe is not the average of the two — breadth itself helps.",
)
cost_bps = extra[2].segmented_control(
    "Cost per side (bps)", [0, 10, 25, 50], default=int(live_config.cost_bps_per_side), key="bt_cost",
    help="Charged on every unit of weight bought or sold at each fill.",
)
toggles = st.columns(2)
absolute_filter = toggles[0].toggle(
    "Cash hurdle (dual momentum)",
    value=live_config.absolute_momentum_filter == "dual_momentum_cash_hurdle",
    key="bt_abs",
    help="Hold an exposure only while its own 12-month return beats the liquid fund's 12-month "
    f"return; otherwise its slot sits in cash, earning what the fund earned "
    f"({live_config.risk_free_rate_annual:.1%} before the fund's NAV history).",
)
exclude_backcalculated = toggles[1].toggle(
    "Exclude back-calculated index history",
    value=live_config.backfill_policy == "exclude_prelaunch",
    key="bt_backfill",
    help="An index is not eligible before its NSE launch date. Its earlier values were computed "
    "after the fact and could never have been traded on.",
)

top_n = int(top_n or live_config.target_holdings_n)
config = backtest_config(
    top_n=top_n,
    buffer_m=2 * top_n if (buffer_choice or "M = 2N") == "M = 2N" else top_n,
    hold_months=int(hold_months or live_config.rebalance_months),
    absolute_filter=absolute_filter,
    investable_only=investable_only,
    cost_bps=float(cost_bps if cost_bps is not None else live_config.cost_bps_per_side),
    exclude_backcalculated=exclude_backcalculated,
)
months = None if months_choice in (None, "All") else int(months_choice)
is_live = config.config_hash == live_config.config_hash and months is None and (category or "All") == "All"
if not is_live:
    note(
        "<b>What-if run.</b> These settings differ from the live strategy, so this is one of many "
        "configurations, not the strategy the dashboard follows. Picking the best-looking one is "
        "fitting this sample.",
        tone="amber",
    )

result = load_backtest(config, months=months, category=category or "All")
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
    """Turn 'defence:slots full; it:fails cash hurdle' into readable names."""
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
            f"CAGR {fmt_pct(stats['cagr'])} · net of costs",
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
        (
            "Costs paid",
            fmt_pct(stats["total_cost"]),
            f"{stats['cost_bps_per_side']:g} bps per side · gross {fmt_pct(stats['gross_total_return'])}",
            "",
        ),
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
if cash_periods > 0:
    note(
        f"<b>{cash_periods:.0%} of periods left at least one slot in cash</b>, because a top-ranked "
        "exposure failed the cash hurdle. Investability is judged from each vehicle's recorded "
        "inception date (its first published NAV), not from the fact that it exists today — most "
        "of these ETFs and index funds launched in 2024–25.",
        tone="amber",
    )
if not investable_only:
    note(
        "<b>All indices includes exposures with no buyable vehicle.</b> It measures the signal, "
        "not a portfolio you could have held. Switch to the strategy for what was actually "
        "purchasable on each date.",
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

section("Does the answer depend on the score?", "Same test, six score specifications")
# Six full backtests: run it only when asked, not on every page load.
if not st.toggle("Test six score specifications", value=False, key="bt_sensitivity"):
    st.caption(
        "Runs the same backtest under six score specifications — segment weightings and the "
        "volatility-adjusted alternative — to show how much of the result is the strategy and "
        "how much is the parameter."
    )
    st.stop()

sensitivity = load_sensitivity(config, months=months, category=category or "All")
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
        "the sample. v1.0 weights the four segments equally because that assumes nothing about "
        "which horizon predicts best, which is the honest default when the record is this short.",
        tone="amber",
    )

section("Month-by-month record")
ledger = _named(result.monthly)
ledger["Month"] = pd.to_datetime(ledger["period_end"]).dt.strftime("%b %Y")
ledger = ledger[
    ["Month", "holdings", "cash_slots", "turnover", "cost", "strategy_return", "benchmark_return",
     "excess_return", "universe", "skipped"]
].rename(
    columns={
        "holdings": "Held",
        "cash_slots": "Cash",
        "turnover": "Turnover",
        "cost": "Cost",
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
        "Strategy": st.column_config.NumberColumn(
            format="percent", width="small", help="Net of costs, fill to fill"
        ),
        "Nifty 50": st.column_config.NumberColumn(format="percent", width="small"),
        "Excess": st.column_config.NumberColumn(format="percent", width="small"),
        "Turnover": st.column_config.NumberColumn(format="percent", width="small"),
        "Cost": st.column_config.NumberColumn(
            format="percent", width="small", help="Cost charged at this rebalance's fill"
        ),
        "Cash": st.column_config.NumberColumn(
            width="small", help="Slots left in cash because nothing qualified"
        ),
        "Eligible": st.column_config.NumberColumn(
            width="small", help="Exposures that could be ranked (and bought) that period"
        ),
        "Passed over": st.column_config.TextColumn(
            width="medium", help="Exposures ranked within the buffer but not held, and why"
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
hurdle_text = (
    f" A slot is held only while the exposure's own 12-month return beats cash "
    f"— the liquid fund's 12-month return, or {config.risk_free_rate_annual:.1%} before its NAV "
    "history — and a top name that fails leaves its slot in cash."
    if config.absolute_momentum_filter == "dual_momentum_cash_hurdle"
    else " The cash hurdle is off."
)
note(
    "<b>Method.</b> At the close of the last trading day of every "
    f"{config.rebalance_months}-month period, <code>construct_target_portfolio</code> scores every "
    "exposure with a full 12-month history on the non-overlapping 1M, 3M-1M, 6M-3M and 12M-6M "
    "returns, ranks the eligible ones, keeps a holding while its rank is within "
    f"{config.retention_buffer_m}, and fills empty slots only from the top {config.target_holdings_n}. "
    f"Each slot is 1/{config.target_holdings_n} of the book."
    + hurdle_text
    + (
        " A pick must have had a buyable vehicle on that date, judged from its recorded inception "
        "date."
        if config.require_investable
        else " Every index is eligible, buyable or not."
    )
    + " Trades fill at the next session's close, each period runs from one fill to the next, "
    f"and every unit of weight traded costs {config.cost_bps_per_side:g} bps. Cash earns what the "
    f"liquid fund's NAV earned between fills ({config.risk_free_rate_annual:.1%} before its history), "
    "and only completed months are counted."
    + (
        " Back-calculated index history is excluded: an index is not eligible before its NSE launch date."
        if config.backfill_policy == "exclude_prelaunch"
        else " Index history before each index's NSE launch date (back-calculated) is included."
    )
)
note(
    f"<b>What this is not.</b> The {config.cost_bps_per_side:g} bps per side covers brokerage and "
    "spread only roughly; tax, an ETF's premium to NAV and impact on thin funds are not modelled, "
    "so a real book earns less. These are index levels, and an index cannot be bought directly; "
    "the fund tracking it lags by its tracking difference. Funds that launched and later closed "
    "are absent, so even the investable universe carries some survivorship bias. Index "
    "reconstitution is embedded in the published series. Treat this as a sanity check on the "
    "signal, not as evidence of an edge.",
    tone="amber",
)
