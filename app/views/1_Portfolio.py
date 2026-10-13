"""Portfolio: the Paresh app's Portfolio page (src/ui/views/portfolio_view.py), on this strategy's model book.

The layout, the components and the stylesheet are Paresh's own (``app/kit``).
What differs is only the data: a ₹20 lakh book of sector and theme funds
(``src/portfolio/book.py``) instead of a stock book, and Nifty 50 TRI as the
benchmark. The frozen-record sections are left out on purpose: the owner found
them a repeat of Calendar returns (12 Oct 2026).
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

from app.data import load_decisions, load_etf_prices, load_model_book, load_portfolio  # noqa: E402
from app.kit import page_kit as kit  # noqa: E402
from app.kit.calendar import build_grid, render_calendar_returns  # noqa: E402
from app.kit.charts import render_correlation_heatmap  # noqa: E402
from app.kit.theme import render_saas_table  # noqa: E402

BENCH = "Nifty 50 TRI"


def _correlation_note(mean: float) -> str:
    if mean < 0.3:
        return "they move largely independently"
    if mean < 0.6:
        return "they move partly together"
    return "they move closely together"


def _symbol(vehicle: str) -> str:
    """The NSE symbol of an ETF ("METAL · Mirae …" → METAL); an index fund keeps its name."""
    return str(vehicle).split(" · ")[0]


def _day(value) -> str:
    stamp = pd.to_datetime(value, errors="coerce")
    return "—" if pd.isna(stamp) else f"{stamp:%d %b %Y}"


book = load_model_book()
if not book.ok:
    kit.page_head("Portfolio", "")
    st.info("The model book could not be built: the pipeline has not published enough history yet.")
    st.stop()

capital = book.capital
equity, bench = book.equity, book.benchmark
positions = book.positions
value = float(equity.iloc[-1])
invested = float(positions["Invested Value (₹)"].sum()) if not positions.empty else 0.0
current = float(positions["Current Value (₹)"].sum()) if not positions.empty else 0.0
cash = book.cash
pnl = current - invested
pnl_pct = pnl / invested * 100.0 if invested else np.nan
day_pnl_pct = (float(equity.iloc[-1] / equity.iloc[-2]) - 1.0) * 100.0 if len(equity) > 1 else np.nan
benchmark_day = float(bench.iloc[-1] / bench.iloc[-2] - 1.0) if len(bench) > 1 else np.nan
strategy_total = value / capital - 1.0
benchmark_total = float(bench.iloc[-1]) / capital - 1.0 if not bench.empty else np.nan
monthly = book.monthly
latest = monthly.iloc[-1] if not monthly.empty else None
month = pd.Period(latest["Period"], freq="M").strftime("%b") if latest is not None else ""
strategy_mtd = float(latest["Strategy"]) if latest is not None else np.nan
benchmark_mtd = float(latest["Benchmark"]) if latest is not None else np.nan
trades = book.trades
rebalances = book.rebalances

kit.page_head("Portfolio", "")

# Six centred cards, with the benchmark as a second line where a comparable period exists.
kit.readings([
    kit.Reading("Portfolio value", f"₹{value:,.0f}", f"Invested: ₹{capital:,.0f}"),
    kit.Reading("Since inception", kit.pct(strategy_total), f"{BENCH} {kit.pct(benchmark_total)}",
                "up" if strategy_total >= 0 else "down"),
    kit.Reading("Unrealised P&L", "—" if not np.isfinite(pnl_pct) else f"{pnl_pct:+.1f}%", "",
                "" if not np.isfinite(pnl_pct) else ("up" if pnl >= 0 else "down")),
    kit.Reading("Day P&L", "—" if not np.isfinite(day_pnl_pct) else f"{day_pnl_pct:+.1f}%",
                f"{BENCH} {kit.pct(benchmark_day)}", "up" if day_pnl_pct >= 0 else "down"),
    kit.Reading("Cash / realised balance", f"₹{cash:,.0f}"),
    kit.Reading("MTD return" if latest is not None and latest["Origin"] == "MTD" else f"{month} return",
                kit.pct(strategy_mtd), f"{BENCH} {kit.pct(benchmark_mtd)}",
                "up" if strategy_mtd >= 0 else "down"),
], "Portfolio snapshot")

# One canonical table; the columns readers scan first come first.
live = load_portfolio()
targets = dict(live.target.weights) if live is not None else {}
ranks = load_decisions().set_index("exposure_id") if not load_decisions().empty else pd.DataFrame()
table = positions.copy()
if not table.empty:
    table["Symbol"] = table["Vehicle"].map(_symbol)
    table["Target Weight %"] = table["exposure_id"].map(lambda e: 100.0 * float(targets.get(e, 0.0)))
    table["Weight Drift %"] = table["Weight %"] - table["Target Weight %"]
    table["Shares"] = table["Units"]
    table["Entry Price"] = table["Avg Cost"]
    table["Sector / Industry"] = table["Exposure"]
    if not ranks.empty:
        table["Rank at Rebalance"] = table["exposure_id"].map(pd.to_numeric(ranks.get("decision_rank"), errors="coerce"))
        table["Current Rank"] = table["exposure_id"].map(pd.to_numeric(ranks.get("rank"), errors="coerce"))
        table["1M Return"] = table["exposure_id"].map(pd.to_numeric(ranks.get("return_1M"), errors="coerce"))
display_cols = [
    "Symbol", "Current Price", "P&L %", "P&L (₹)", "Weight %", "Target Weight %",
    "Weight Drift %", "Day P&L (₹)", "Day P&L %", "Current Value (₹)", "Shares",
    "Entry Date", "Entry Price", "Invested Value (₹)", "Holding Days",
    "Rank at Rebalance", "Current Rank", "1M Return", "Sector / Industry",
]
current_view = table[[c for c in display_cols if c in table.columns]].copy()
if "Entry Date" in current_view.columns:
    current_view["Entry Date"] = pd.to_datetime(current_view["Entry Date"], errors="coerce").dt.strftime("%d %b %Y").fillna("—")
for col in ("Rank at Rebalance", "Current Rank", "Holding Days"):
    if col in current_view.columns:
        current_view[col] = current_view[col].map(lambda v: int(v) if pd.notna(v) else np.nan).astype("Int64")

with kit.card("Current book", "portfolio_current", f"{len(table)} positions · priced {book.as_of:%d %b %Y}"):
    render_saas_table(current_view, max_height=620, variant="portfolio")

mix, together = st.columns(2, gap="medium")  # the owner asked for these two side by side
with mix, kit.card("Sector exposure", "portfolio_exposure"):
    rows = [(f"{r['Sector / Industry']}", float(r["Weight %"]), f"{r['Weight %']:.1f}%", False)
            for _, r in table.iterrows()]
    cash_weight = cash / value * 100.0 if value > 0 else 0.0
    rows.append(("Cash", cash_weight, f"{cash_weight:.1f}%", False))
    st.html(kit.bar_list(rows, scale=max([r[1] for r in rows] + [1.0])))

navs = load_etf_prices()
symbols = {str(r["Symbol"]): navs[r["key"]] for _, r in table.iterrows() if r.get("key") in navs.columns}
with together:
    if len(symbols) >= 2:
        returns = pd.DataFrame(symbols).dropna().pct_change().dropna().tail(90)
        corr = returns.corr()
        mean = float(corr.where(~np.eye(len(corr), dtype=bool)).stack().mean())
        with kit.card("How they move together", "portfolio_corr", f"Average {mean:.2f}, {_correlation_note(mean)}"):
            render_correlation_heatmap(corr, list(symbols))
    else:
        with kit.card("How they move together", "portfolio_corr", "90-day correlation of the holdings"):
            st.caption("One holding: nothing to compare.")

# Performance: one card, equity and drawdown together.
with kit.card("Equity & drawdown", "portfolio_equity"):
    drawdown = equity / equity.cummax() - 1.0
    gap = strategy_mtd - benchmark_mtd if np.isfinite(strategy_mtd) and np.isfinite(benchmark_mtd) else np.nan
    kit.metric_row([
        kit.Metric(f"{month} strategy", kit.pct(strategy_mtd)),
        kit.Metric(f"{month} {BENCH}", kit.pct(benchmark_mtd)),
        kit.Metric(f"{month} alpha", kit.pct(gap)),
        kit.Metric("Max drawdown", kit.pct(float(drawdown.min()), signed=False)),
    ], key="pf_equity")
    kit.equity_chart(
        equity.index, equity.tolist(),
        bench.reindex(equity.index, method="ffill").tolist() if not bench.empty else None,
        names=("Strategy", BENCH), key="portfolio_equity_curve", drawdown=drawdown.tolist(),
    )

with kit.card("Calendar returns", "portfolio_monthly", f"Strategy, {BENCH} and Alpha, per year"):
    grid = build_grid(monthly.assign(Alpha=monthly["Strategy"] - monthly["Benchmark"]),
                      {"Strategy": "Strategy", "Benchmark": BENCH, "Alpha": "Alpha"})
    render_calendar_returns(grid)
    recorded = monthly[monthly["Origin"] == "Recorded"]
    if not recorded.empty:
        first = pd.Period(recorded["Period"].iloc[0], freq="M").strftime("%b %Y")
        lead = f"{month} is month to date. " if latest is not None and latest["Origin"] == "MTD" else ""
        st.caption(f"{lead}From {first} each month is recorded as it closed; earlier months are a backfilled replay.")
    elif latest is not None and latest["Origin"] == "MTD":
        st.caption(f"{month} is month to date. Every earlier month is a backfilled replay of the live rules.")

# Activity.
with kit.card("Trades", "portfolio_trades"):
    if trades.empty:
        st.info("No trades are available yet.")
    else:
        outcome = st.pills("Outcome", ["All", "Winners", "Losers", "Open"], default="All",
                           key="portfolio_trade_outcome", label_visibility="collapsed")
        tv = trades.assign(**{"Symbol": trades["Vehicle"].map(_symbol), "Return %": trades["Return %"] / 100.0})
        if outcome == "Winners":
            tv = tv[tv["Return %"] > 0]
        elif outcome == "Losers":
            tv = tv[tv["Return %"] < 0]
        elif outcome == "Open":
            tv = tv[tv["Status"] == "Open"]
        tv = tv.assign(**{"Entry Date": tv["Entry Date"].map(_day), "Exit Date": tv["Exit Date"].map(_day)})
        cols = [c for c in ["Symbol", "Status", "Entry Date", "Entry Price", "Exit Date", "Exit Price", "Return %",
                            "Holding (Days)", "Reason for Exit"] if c in tv.columns]
        render_saas_table(tv[cols], max_height=600)
        closed = trades[trades["Status"] == "Closed"]
        wins, losses = int((closed["Return %"] > 0).sum()), int((closed["Return %"] < 0).sum())
        st.caption(f"{len(closed)} closed · {wins} winners · {losses} losers")

with kit.card("Rebalances", "portfolio_rebalances"):
    if rebalances.empty:
        st.info("No rebalances are available yet.")
    else:
        action = st.pills("Action", ["All", "Buy", "Sell", "Hold"], default="All",
                          key="portfolio_rebalance_action", label_visibility="collapsed")
        rv = rebalances.assign(**{"Symbol": rebalances["Vehicle"].map(_symbol),
                                  "Return %": rebalances["Return %"] / 100.0})
        if action in ("Buy", "Sell", "Hold"):
            rv = rv[rv["Action"].str.contains(action.upper(), na=False)]
        cols = [c for c in ["Period", "Action", "Symbol", "Price", "Weight %", "Return %", "Reason / Signal"]
                if c in rv.columns]
        render_saas_table(rv[cols], max_height=600)

with st.popover("Export", icon=":material/download:"):
    stamp = f"{book.as_of:%Y%m%d}"
    st.download_button("Holdings CSV", table.to_csv(index=False).encode(), f"portfolio_{stamp}.csv", "text/csv",
                       key="dl_port_csv")
    if not trades.empty:
        st.download_button("Trades CSV", trades.to_csv(index=False).encode(), f"portfolio_trades_{stamp}.csv",
                           "text/csv", key="dl_port_trades_csv")
    if not rebalances.empty:
        st.download_button("Rebalances CSV", rebalances.to_csv(index=False).encode(),
                           f"portfolio_rebalances_{stamp}.csv", "text/csv", key="dl_port_rebalance_csv")
    if not monthly.empty:
        st.download_button("Monthly returns CSV", monthly.to_csv(index=False).encode(),
                           f"portfolio_monthly_{stamp}.csv", "text/csv", key="dl_port_monthly_csv")
