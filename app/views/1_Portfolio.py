from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components import lw_chart as lw  # noqa: E402
from app.components.hcharts import correlation_heatmap  # noqa: E402
from app.components.ledger import Col, inr, ledger_table  # noqa: E402
from app.components.theme import bar_list, calendar_html, card, html_block, note, readings  # noqa: E402
from app.data import load_decisions, load_etf_prices, load_model_book, load_portfolio  # noqa: E402
from src.portfolio.book import calendar_grid  # noqa: E402

BENCH = "Nifty 50 TRI"


def _pct(value: float | None, signed: bool = True) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:+.1%}" if signed else f"{abs(value):.1%}"


def _direction(value: float | None) -> str:
    return "" if value is None or not np.isfinite(value) else ("up" if value >= 0 else "down")


def _correlation_note(mean: float) -> str:
    if mean < 0.3:
        return "they move largely independently"
    if mean < 0.6:
        return "they move partly together"
    return "they move closely together"


html_block("<h1>Portfolio</h1>")

book = load_model_book()
if not book.ok:
    note("<b>No model book yet.</b> The pipeline has not published enough history to replay one.", tone="warn")
    st.stop()

equity, bench = book.equity, book.benchmark
value = float(equity.iloc[-1])
positions = book.positions
invested = float(positions["Invested Value (₹)"].sum()) if not positions.empty else 0.0
current = float(positions["Current Value (₹)"].sum()) if not positions.empty else 0.0
unrealised = current / invested - 1.0 if invested > 0 else float("nan")
day = float(equity.iloc[-1] / equity.iloc[-2] - 1.0) if len(equity) > 1 else float("nan")
bench_day = float(bench.iloc[-1] / bench.iloc[-2] - 1.0) if len(bench) > 1 else float("nan")
total = value / book.capital - 1.0
bench_total = float(bench.iloc[-1]) / book.capital - 1.0 if not bench.empty else float("nan")
monthly = book.monthly
latest = monthly.iloc[-1] if not monthly.empty else None
month_label = pd.Period(latest["Period"], freq="M").strftime("%b") if latest is not None else ""
mtd = float(latest["Strategy"]) if latest is not None else float("nan")
mtd_bench = float(latest["Benchmark"]) if latest is not None else float("nan")

readings([
    ("Portfolio value", f"₹{inr(value)}", f"Invested: ₹{inr(book.capital)}", ""),
    ("Since inception", _pct(total), f"{BENCH} {_pct(bench_total)}", _direction(total)),
    ("Unrealised P&L", _pct(unrealised), "", _direction(unrealised)),
    ("Day P&L", _pct(day), f"{BENCH} {_pct(bench_day)}", _direction(day)),
    ("Cash / realised balance", f"₹{inr(book.cash)}", "", ""),
    (f"{month_label} return" if latest is not None and latest["Origin"] != "MTD" else "MTD return",
     _pct(mtd), f"{BENCH} {_pct(mtd_bench)}", _direction(mtd)),
])

# --------------------------------------------------------------------------- #
# Current book
# --------------------------------------------------------------------------- #
live = load_portfolio()
targets = dict(live.target.weights) if live is not None else {}
decisions = load_decisions()
ranks = decisions.set_index("exposure_id") if not decisions.empty else pd.DataFrame()
view = positions.copy()
if not view.empty:
    view["Target Weight %"] = view["exposure_id"].map(lambda e: 100.0 * float(targets.get(e, 0.0)))
    view["Weight Drift %"] = view["Weight %"] - view["Target Weight %"]
    if not ranks.empty:
        view["Rank"] = view["exposure_id"].map(pd.to_numeric(ranks.get("rank"), errors="coerce"))
        view["1M Return"] = view["exposure_id"].map(pd.to_numeric(ranks.get("return_1M"), errors="coerce") * 100.0)
with card("Current book", f"{len(view)} position{'s' if len(view) != 1 else ''} · priced {book.as_of:%d %b %Y}"):
    ledger_table(view, [
        Col("Exposure", "name"), Col("Vehicle"), Col("Current Price", "price"), Col("P&L %", "pct"),
        Col("P&L (₹)", "rupees"), Col("Weight %", "pctp"), Col("Target Weight %", "pctp"),
        Col("Weight Drift %", "pct"), Col("Day P&L (₹)", "rupees"), Col("Day P&L %", "pct"),
        Col("Current Value (₹)", "rupee"), Col("Units", "units"), Col("Entry Date", "date"),
        Col("Avg Cost", "price"), Col("Invested Value (₹)", "rupee"), Col("Holding Days", "int"),
        Col("Rank", "int"), Col("1M Return", "pct"),
    ], empty="The book is all in cash.")

# --------------------------------------------------------------------------- #
# Mix and co-movement
# --------------------------------------------------------------------------- #
with card("Exposure mix"):
    rows = [(str(r["Exposure"]), float(r["Weight %"]), f"{r['Weight %']:.1f}%", False) for _, r in view.iterrows()]
    cash_weight = 100.0 * book.cash / value if value > 0 else 0.0
    rows.append(("Cash", cash_weight, f"{cash_weight:.1f}%", True))
    html_block(bar_list(rows, scale=100.0))

navs = load_etf_prices()
series = {str(r["Exposure"]): navs[r["key"]] for _, r in view.iterrows() if r.get("key") in navs.columns}
if len(series) >= 2:
    returns = pd.DataFrame(series).dropna().pct_change().dropna().tail(90)
    corr = returns.corr()
    mean = float(corr.where(~np.eye(len(corr), dtype=bool)).stack().mean())
    with card("How they move together", f"Average {mean:.2f}, {_correlation_note(mean)}"):
        correlation_heatmap(corr)

# --------------------------------------------------------------------------- #
# Performance
# --------------------------------------------------------------------------- #
drawdown = equity / equity.cummax() - 1.0
with card("Equity & drawdown", f"From {equity.index[0]:%d %b %Y} · ₹{inr(book.capital)} start"):
    readings([
        (f"{month_label} strategy", _pct(mtd), "", _direction(mtd)),
        (f"{month_label} {BENCH}", _pct(mtd_bench), "", _direction(mtd_bench)),
        (f"{month_label} alpha", _pct(mtd - mtd_bench), "", _direction(mtd - mtd_bench)),
        ("Max drawdown", _pct(float(drawdown.min()), signed=False), "", "down"),
    ])
    lw.render([
        {"height": 320, "series": [
            {"name": "Strategy", "type": "line", "color": lw.INDIGO, "fmt": "rupee",
             "data": lw.series_points(equity.index, equity.tolist())},
            {"name": BENCH, "type": "line", "color": lw.GREY, "fmt": "rupee",
             "data": lw.series_points(bench.index, bench.tolist())},
        ]},
        {"height": 140, "series": [
            {"name": "Drawdown", "type": "baseline", "color": lw.RED, "negColor": lw.RED, "fmt": "pct",
             "data": lw.series_points(drawdown.index, drawdown.tolist(), scale=100.0)},
        ]},
    ], key="portfolio_equity")

with card("Calendar returns", f"Strategy, {BENCH} and alpha, per year"):
    strategy_grid = calendar_grid(monthly, "Strategy")
    bench_grid = calendar_grid(monthly, "Benchmark")
    html_block(calendar_html([("Strategy", strategy_grid), ("Nifty 50", bench_grid),
                              ("Alpha", strategy_grid - bench_grid)]))

with card("Monthly record", f"{len(monthly)} months · backfilled replay on the live rules"):
    record = monthly.assign(**{c: monthly[c] * 100.0 for c in ("Strategy", "Benchmark", "Alpha")})
    ledger_table(record.iloc[::-1], [
        Col("Period", "name"), Col("Strategy", "pct"), Col("Benchmark", "pct", BENCH), Col("Alpha", "pct"),
        Col("Origin", "badge"),
    ], max_height=420)

# --------------------------------------------------------------------------- #
# Activity
# --------------------------------------------------------------------------- #
trades = book.trades
with card("Trades"):
    outcome = st.pills("Outcome", ["All", "Winners", "Losers", "Open"], default="All",
                       key="pf_trade_outcome", label_visibility="collapsed") or "All"
    shown = trades
    if not trades.empty:
        if outcome == "Winners":
            shown = trades[trades["Return %"] > 0]
        elif outcome == "Losers":
            shown = trades[trades["Return %"] < 0]
        elif outcome == "Open":
            shown = trades[trades["Status"] == "Open"]
    ledger_table(shown, [
        Col("Exposure", "name"), Col("Vehicle"), Col("Status", "badge"), Col("Entry Date", "date"),
        Col("Entry Price", "price"), Col("Exit Date", "date"), Col("Exit Price", "price"), Col("Return %", "pct"),
        Col("Holding (Days)", "int"), Col("Reason for Exit"),
    ], wrap=("Reason for Exit",), empty="No trades match.")
    closed = trades[trades["Status"] == "Closed"] if not trades.empty else trades
    wins = int((closed["Return %"] > 0).sum()) if not closed.empty else 0
    losses = int((closed["Return %"] < 0).sum()) if not closed.empty else 0
    st.caption(f"{len(closed)} closed · {wins} winners · {losses} losers")

rebalances = book.rebalances
with card("Rebalances"):
    action = st.pills("Action", ["All", "Buy", "Sell", "Hold"], default="All",
                      key="pf_rebalance_action", label_visibility="collapsed") or "All"
    shown = rebalances
    if action != "All" and not rebalances.empty:
        shown = rebalances[rebalances["Action"].str.upper().str.contains(action.upper(), na=False)]
    ledger_table(shown, [
        Col("Period", "name"), Col("Fill Date", "date"), Col("Action", "badge"), Col("Exposure"), Col("Vehicle"),
        Col("Price", "price"), Col("Units traded", "units"), Col("Traded (₹)", "rupee"), Col("Weight %", "pctp"),
        Col("Return %", "pct"), Col("Reason / Signal"),
    ], wrap=("Reason / Signal",), empty="No rebalances match.")

with st.popover("Export", icon=":material/download:"):
    stamp = f"{book.as_of:%Y%m%d}"
    st.download_button("Holdings CSV", view.to_csv(index=False).encode(), f"portfolio_{stamp}.csv", "text/csv")
    st.download_button("Trades CSV", trades.to_csv(index=False).encode(), f"portfolio_trades_{stamp}.csv", "text/csv")
    st.download_button("Rebalances CSV", rebalances.to_csv(index=False).encode(), f"portfolio_rebalances_{stamp}.csv",
                       "text/csv")
    st.download_button("Monthly returns CSV", monthly.to_csv(index=False).encode(), f"portfolio_monthly_{stamp}.csv",
                       "text/csv")
