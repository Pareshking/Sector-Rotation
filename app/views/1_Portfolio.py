from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.metrics import data_health_banner, health_summary
from app.components.navigation import mobile_nav
from app.components.theme import (
    _esc,
    brand_header,
    inject_theme,
    kpi_strip,
    note,
    page_header,
    section,
)
from app.data import (
    best_vehicle,
    current_regime,
    load_decisions,
    load_index_panel,
    load_portfolio,
    strategy_config,
)
from src.portfolio.calendar import fill_date
from src.portfolio.vehicles import DEFAULT_BOOK_RUPEES, days_to_build

inject_theme()
mobile_nav("Portfolio")

live = load_portfolio()
decisions = load_decisions()
panel, _ = load_index_panel()
config = strategy_config()
regime = current_regime()
health = health_summary()

chips: list[tuple[str, str]] = []
if regime is not None:
    chips += [("Nifty 50 TRI 12M", f"{regime.benchmark_12m:+.1%}"), ("Cash 12M", f"{regime.cash_12m:.2%}")]
if live is not None:
    chips += [("Data", f"{live.data_as_of:%d %b %Y}"), ("Strategy", f"v{config.version} · {config.config_hash}")]
brand_header(
    "Dual Momentum",
    regime=regime.label if regime is not None else "",
    stats=chips,
    when=f"Updated {health.get('age', '')}" if health else "",
)
page_header("India Sector Rotation", "Portfolio", "What to hold, what to trade, and when the next decision is due.")
data_health_banner()

if live is None or decisions.empty:
    st.warning("Prepared data is not available yet. Run the data pipeline first.")
    st.stop()

target = live.target
names = decisions.set_index("exposure_id")["exposure"].to_dict()
fill = fill_date(panel.index, target.as_of) if not panel.empty else None

# --------------------------------------------------------------------------- #
# Status: a rebalance to act on, or steady holdings until the next one.
# --------------------------------------------------------------------------- #
orders = [d for d in target.decisions if d.action != "HOLD"]
if live.data_as_of <= target.as_of:
    note(
        f"<b>Rebalance at the {target.as_of:%d %b %Y} close.</b> "
        + (
            f"{len(orders)} order(s) below execute at the next session's close."
            if orders
            else "No trades: every holding is retained."
        ),
        tone="amber" if orders else "",
    )
else:
    filled = f", filled at the {fill:%d %b %Y} close" if fill is not None else ""
    note(
        f"<b>Holdings steady.</b> Last rebalance {target.as_of:%d %b %Y}{filled}. "
        f"Next scheduled rebalance on <b>{live.next_rebalance:%a %d %b %Y}</b>."
    )

kpi_strip(
    [
        ("Decision", f"{target.as_of:%d %b %Y}", "month-end close", ""),
        ("Next rebalance", f"{live.next_rebalance:%d %b %Y}", "last weekday of the month", ""),
        (
            "Holdings",
            f"{len(target.holdings)} of {config.target_holdings_n}",
            f"{target.cash_weight:.0%} in cash",
            "buy" if target.holdings else "amber",
        ),
        (
            "Market regime",
            regime.label if regime is not None else "—",
            "context only: Nifty 50 TRI vs cash, 12 months",
            "buy" if regime is not None and regime.label == "RISK-ON" else "red",
        ),
    ]
)

# --------------------------------------------------------------------------- #
# Target portfolio
# --------------------------------------------------------------------------- #
book = float(st.session_state.get("book_size", DEFAULT_BOOK_RUPEES))
bps = float(config.cost_bps_per_side)
rows, reasons = [], []
for decision in target.decisions:
    choice = best_vehicle(decision.exposure_id, target.as_of)
    traded = abs(decision.target_weight - decision.prior_weight)
    days = days_to_build(choice, decision.target_weight * book) if decision.target_weight > 0 else None
    rows.append(
        {
            "Exposure": names.get(decision.exposure_id, decision.exposure_id),
            "Best vehicle": choice.label if choice else "no buyable vehicle",
            "Target": decision.target_weight,
            "Held now": decision.prior_weight,
            "Action": decision.action,
            "Est. cost (bps of book)": traded * bps,
            "Days to build": days,
        }
    )
    reasons.append((names.get(decision.exposure_id, decision.exposure_id), decision, choice))
prior_cash = max(0.0, 1.0 - sum(d.prior_weight for d in target.decisions))
rows.append(
    {
        "Exposure": "Cash",
        "Best vehicle": config.cash_proxy.name if config.cash_proxy else "Unallocated cash",
        "Target": target.cash_weight,
        "Held now": prior_cash,
        "Action": "—",
        "Est. cost (bps of book)": 0.0,
        "Days to build": 1.0 if target.cash_weight > 0 else None,
    }
)
table = pd.DataFrame(rows)

section(
    "Target portfolio",
    f"Decision at the {target.as_of:%d %b %Y} close · Strategy v{target.config_version} · config {target.config_hash}",
)
st.dataframe(
    table,
    hide_index=True,
    width="stretch",
    column_config={
        "Exposure": st.column_config.TextColumn(width="medium", pinned=True),
        "Best vehicle": st.column_config.TextColumn(
            width="large",
            help="Least tracking difference against its own index among funds that had incepted by "
            "the decision date; without a year of tracking, the most-traded ETF.",
        ),
        "Target": st.column_config.NumberColumn(format="percent", width="small"),
        "Held now": st.column_config.NumberColumn(
            format="percent", width="small", help="The previous decision's target weight"
        ),
        "Action": st.column_config.TextColumn(width="small"),
        "Est. cost (bps of book)": st.column_config.NumberColumn(
            format="%.1f", width="small",
            help=f"Weight traded × {bps:g} bps per side. Liquid-fund moves are not charged.",
        ),
        "Days to build": st.column_config.NumberColumn(
            format="%.0f", width="small",
            help=f"At a ₹{book / 100000:.0f} lakh book. An index fund fills at the next NAV; an ETF "
            "takes at most 10% of a day's NSE turnover.",
        ),
    },
)
total_cost = float(table["Est. cost (bps of book)"].sum())
note(
    f"Estimated cost of this rebalance: <b>{total_cost:.1f} bps of the book</b> "
    f"({bps:g} bps per side on the weight traded). Book size for days-to-build: "
    f"<b>₹{book / 100000:.0f} lakh</b> (change it on the Exposure page)."
)

section("Why", "The rule that put each line here")
lines = []
for name, decision, choice in reasons:
    vehicle = f"<br><span style='color:var(--muted)'>Vehicle: {_esc(choice.reason)}</span>" if choice else ""
    lines.append(f"<b>{_esc(name)} · {decision.action}</b> — {_esc(decision.reason)}{vehicle}")
cash_basis = (
    f"the liquid fund returned {target.cash_hurdle_12m:.2%} over the last 12 months"
    if target.cash_hurdle_source == "nav"
    else f"cash is assumed at {target.cash_hurdle_12m:.2%} (the liquid fund's NAV is not yet published)"
)
lines.append(f"<b>Cash · {target.cash_weight:.0%}</b> — Hurdle for every holding: {_esc(cash_basis)}.")
note("<br><br>".join(lines))

# --------------------------------------------------------------------------- #
# On the edge: what the buffer is holding, and who is next in line.
# --------------------------------------------------------------------------- #
n, m = config.target_holdings_n, config.retention_buffer_m
ranking = target.ranking
edge = ranking[ranking["rank"].notna()]
edge = edge[(edge["rank"].astype(int) > n) & (edge["rank"].astype(int) <= m)]
section(
    "On the edge",
    f"Ranks {n + 1}–{m}: inside the retention buffer, so held names stay but new ones may not enter",
)
if edge.empty:
    st.caption("No exposure ranks inside the buffer at this decision.")
else:
    st.dataframe(
        pd.DataFrame(
            {
                "Rank": edge["rank"].astype(int).to_numpy(),
                "Exposure": [names.get(e, e) for e in edge.index],
                "Status": edge["status"].to_numpy(),
                "Score": edge["score"].astype(float).to_numpy(),
                "12M return": edge["return_12m"].astype(float).to_numpy(),
                "Held": [target.weights.get(e, 0.0) > 0 for e in edge.index],
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Score": st.column_config.NumberColumn(format="%+.2f", width="small"),
            "12M return": st.column_config.NumberColumn(format="percent", width="small"),
        },
    )
    st.caption(
        f"A holding is kept while it ranks {m} or better; a new entry needs rank {n} or better. "
        "Every other exposure is on the Rankings page."
    )

st.caption(
    "A quantitative decision aid, not advice. Verify the fund, its tracking difference and its "
    "premium to NAV before placing an order."
)
