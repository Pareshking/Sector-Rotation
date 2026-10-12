from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.allocation import allocation_frame, allocation_rows, edge_frame  # noqa: E402
from app.components.tables import show_table  # noqa: E402
from app.components.theme import (  # noqa: E402
    _esc,
    action_chip,
    card_grid,
    chip,
    fmt_pct,
    fmt_rupees,
    fmt_signed,
    html_block,
    kpi_grid,
    note,
    page_header,
    section,
    status_bar,
)
from app.data import best_vehicle, load_decisions, load_index_panel, load_portfolio, strategy_config  # noqa: E402
from src.portfolio.calendar import fill_date  # noqa: E402
from src.portfolio.vehicles import DEFAULT_BOOK_RUPEES  # noqa: E402

page_header("India sector rotation", "Portfolio", "What to hold, what to trade, and when the next decision is due.")

live = load_portfolio()
decisions = load_decisions()
if live is None or decisions.empty:
    note("<b>Prepared data is not available yet.</b> Run the data pipeline first.", tone="warn")
    st.stop()

panel, _ = load_index_panel()
config = strategy_config()
target = live.target
names = decisions.set_index("exposure_id")["exposure"].to_dict()
fill = fill_date(panel.index, target.as_of) if not panel.empty else None
book = float(st.session_state.get("book_size", DEFAULT_BOOK_RUPEES))
bps = float(config.cost_bps_per_side)
n, m = int(config.target_holdings_n), int(config.retention_buffer_m)

cash_basis = (
    f"the liquid fund returned {target.cash_hurdle_12m:.2%} over the last 12 months"
    if target.cash_hurdle_source == "nav"
    else f"cash is assumed at {target.cash_hurdle_12m:.2%} (the liquid fund's NAV is not yet published)"
)
rows = allocation_rows(
    target,
    names,
    lambda exposure_id: best_vehicle(exposure_id, target.as_of),
    book,
    bps,
    config.cash_proxy.name if config.cash_proxy else "Unallocated cash",
    f"Every holding must beat this hurdle: {cash_basis}.",
)
orders = [r for r in rows if not r.is_cash and r.action != "HOLD"]
total_cost = sum(r.cost_bps for r in rows)

# --------------------------------------------------------------------------- #
# Status: steady until the next rebalance, or a rebalance to act on now.
# --------------------------------------------------------------------------- #
days_left = max((pd.Timestamp(live.next_rebalance) - pd.Timestamp(live.data_as_of)).days, 0)
if live.data_as_of <= target.as_of:
    status_bar(
        f"Rebalance at the {target.as_of:%d %b %Y} close",
        (f"{len(orders)} order(s) execute at the next session's close." if orders
         else "No trades: every holding is retained."),
        tone="warn" if orders else "accent",
        right=("Orders", str(len(orders))),
    )
else:
    filled = f", filled at the {fill:%d %b %Y} close" if fill is not None else ""
    status_bar(
        f"Holdings steady until Next Rebalance: {live.next_rebalance:%a %d %b %Y}",
        f"Last rebalance {target.as_of:%d %b %Y}{_esc(filled)}. Nothing to do until then.",
        tone="accent",
        right=("Next rebalance in", f"{days_left} days"),
    )

kpi_grid(
    [
        ("Decision", f"{target.as_of:%d %b %Y}", "month-end close", ""),
        ("Next rebalance", f"{live.next_rebalance:%d %b %Y}", "last weekday of the month", ""),
        ("Holdings", f"{len(target.holdings)} of {n}", f"{target.cash_weight:.0%} in cash", "pos" if target.holdings else "warn"),
        ("Cash hurdle · 12M", f"{target.cash_hurdle_12m:.2%}",
         "liquid fund NAV" if target.cash_hurdle_source == "nav" else "assumed rate", "info"),
        ("Rebalance cost", f"{total_cost:.1f} bps", f"{bps:g} bps per side on weight traded", ""),
    ]
)

# --------------------------------------------------------------------------- #
# Allocation cards: one per line of the target, cash included.
# --------------------------------------------------------------------------- #
section("Target allocation", f"Decision at the {target.as_of:%d %b %Y} close · strategy v{target.config_version} · {target.config_hash}")
ranking = target.ranking


def _card(row) -> str:
    days = "—" if row.days_to_build is None else f"{row.days_to_build:.0f}"
    detail = [("Held now", fmt_pct(row.held, 0)), ("Est. cost", f"{row.cost_bps:.1f} bps"),
              (f"Days to build at {fmt_rupees(book)}", days)]
    if not row.is_cash and row.exposure_id in ranking.index:
        info = ranking.loc[row.exposure_id]
        detail = [("Rank", f"{int(info['rank'])}" if pd.notna(info.get("rank")) else "—"),
                  ("12M return", fmt_pct(info.get("return_12m"))),
                  ("Score", fmt_signed(info.get("score")))] + detail
    dl = "".join(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>" for k, v in detail)
    badge = chip("Cash", "info") if row.is_cash else action_chip(row.action)
    cls = "ds-card ds-card-cash" if row.is_cash else ("ds-card ds-card-active" if row.target > 0 else "ds-card")
    return (
        f'<div class="{cls}"><div class="ds-card-h"><div><div class="ds-card-t">{_esc(row.exposure)}</div>'
        f'<div class="ds-card-s">{_esc(row.vehicle)}</div></div>{badge}</div>'
        f'<div class="ds-weight"><b>{fmt_pct(row.target, 0)}</b><span>target weight</span></div>'
        f'<div class="ds-bar"><i style="width:{max(min(row.target, 1.0), 0.0) * 100:.1f}%"></i></div>'
        f'<dl class="ds-dl">{dl}</dl></div>'
    )


card_grid(_card(row) for row in rows)

with st.expander("Allocation as a table", expanded=False):
    table = allocation_frame(rows)
    show_table(
        table,
        hide_index=True,
        width="stretch",
        column_config={
            "Exposure": st.column_config.TextColumn(pinned=True),
            "Best vehicle": st.column_config.TextColumn(
                width="large", help="Least tracking difference against its own index among funds that had "
                "incepted by the decision date; without a year of tracking, the most-traded ETF."),
            "Target": st.column_config.NumberColumn(format="percent"),
            "Held now": st.column_config.NumberColumn(format="percent", help="The previous decision's target weight"),
            "Est. cost (bps of book)": st.column_config.NumberColumn(
                format="%.1f", help=f"Weight traded × {bps:g} bps per side. Liquid-fund moves are not charged."),
            "Days to build": st.column_config.NumberColumn(
                format="%.0f", help=f"At a {fmt_rupees(book)} book. An index fund fills at the next NAV; an ETF "
                "takes at most 10% of a day's NSE turnover. Change the book size on the Exposure page."),
        },
    )
    st.download_button("Download orders (CSV)", table.to_csv(index=False).encode("utf-8"),
                       file_name=f"target_{target.as_of:%Y%m%d}.csv", mime="text/csv")

# --------------------------------------------------------------------------- #
# Trade execution log: the rule behind every line.
# --------------------------------------------------------------------------- #
section("Trade execution log", "The rule that put each line here")
items = []
for row in rows:
    head = (f"{row.exposure} · {fmt_pct(row.target, 0)} of the book" if row.is_cash
            else f"{row.exposure} · {fmt_pct(row.held, 0)} → {fmt_pct(row.target, 0)}")
    vehicle = (f'<div class="ds-log-v">Vehicle: {_esc(row.vehicle_reason)}</div>' if row.vehicle_reason else "")
    badge = chip("Cash", "info") if row.is_cash else action_chip(row.action)
    items.append(
        f'<div class="ds-log-i">{badge}<div class="ds-log-t">{_esc(head)}</div>'
        f'<div class="ds-log-d">{_esc(row.reason)}</div>{vehicle}</div>'
    )
html_block(f'<div class="ds-log">{"".join(items)}</div>')

# --------------------------------------------------------------------------- #
# On the edge: what the buffer is holding, and who is next in line.
# --------------------------------------------------------------------------- #
section("On the edge", f"Ranks {n + 1}–{m}: a holding stays while it ranks {m} or better; a new entry needs {n} or better")
edge = edge_frame(target, names, n, m)
if edge.empty:
    note("No exposure ranks inside the retention buffer at this decision.")
else:
    rows_html = "".join(
        f'<div class="ds-row"><div class="ds-row-rank">#{int(r.rank)}</div>'
        f'<div class="ds-row-name">{_esc(r.exposure)}</div>'
        f'<div>{chip(r.role, "accent" if r.held else "warn")}</div>'
        f'<div class="ds-row-meta"><span>Score <b>{fmt_signed(r.score)}</b></span>'
        f'<span>12M <b>{fmt_pct(r.return_12m)}</b></span>'
        f'<span>{_esc(r.status or "—")}</span></div></div>'
        for r in edge.itertuples()
    )
    html_block(f'<div class="ds-rows">{rows_html}</div>')
    st.caption("Every other exposure is on the Rankings page.")

st.caption(
    "A quantitative decision aid, not advice. Verify the fund, its tracking difference and its premium to NAV "
    "before placing an order."
)
