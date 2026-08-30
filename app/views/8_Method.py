from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.metrics import health_summary
from app.components.theme import mobile_nav, inject_theme, note, page_header, section
from app.data import load_decisions

inject_theme()
mobile_nav("Method")
page_header(
    "How this works",
    "Method",
    "Everything the app does, in the order it does it. If a number on another page is unclear, "
    "its definition is here.",
)

health = health_summary()
decisions = load_decisions()
total = len(decisions) if not decisions.empty else 47

st.markdown(
    """
### 1. What an exposure is

The unit of analysis is an **exposure**: a sector or theme, represented by the Nifty index that
defines it — not by an ETF. Nifty Auto *is* the Automobile exposure; AUTOBEES is one way to buy
it. Keeping them apart matters: an ETF's liquidity, expense or tracking error is a property of
the fund, and must never be read as strength in the sector.

Each exposure has one canonical index. Two exposures may not share an index — NBFC and Financial
Services ex-Bank once both pointed at NIFTY FINANCIAL SERVICES EX-BANK, which meant two ranks
for one bet.
"""
)

section("2. The ranking")
st.markdown(
    """
For each exposure and each lookback **L** ∈ {1M, 3M, 6M, 12M}:

- **Return** `R_L = P_t / P_{t−L} − 1`
- **Relative return** `DM_L = R_exposure,L − R_Nifty50,L` — the part that matters. In a rising
  market almost everything is up, so ranking on raw return mostly re-ranks the market.
- **Z-score** `z_L` — the relative return standardised across the whole universe on that date.

The **composite momentum Z** is the weighted mean of the four z-scores. Weights are set once, in
`universe.json`, and the same weights drive the live board and the backtest.

> **A Z-score is standardised to a mean of exactly zero.** Roughly half the universe is negative
> by construction. A negative momentum Z means *below the universe average on that date* — not a
> loss. An exposure can be up 8% over three months and still sit at −0.3.

**Rank** is just the ordering of that composite. It is never a buy or sell trigger.
"""
)

section("3. Relative strength and the four stages")
st.markdown(
    """
Separately from the ranking, each exposure is placed in a rotation stage using **Mansfield
Relative Strength**, computed weekly:

- Price relative `RS_t = P_exposure,t / P_Nifty50,t`, sampled each Friday
- `MRS_t = 100 × (RS_t / SMA(RS_t, 52) − 1)` — how far the price relative sits above or below its
  own one-year average
- **RS ratio** `= 1 + MRS/100`. Above 1 means outperforming its own recent norm.
- **RS velocity** `=` the 13-week change in MRS. Positive means the outperformance is widening.

| Stage | RS ratio | RS velocity | Reading |
| --- | --- | --- | --- |
| **Leading** | ≥ 1 | ≥ 0 | Ahead and pulling further ahead |
| **Weakening** | ≥ 1 | < 0 | Still ahead but losing ground — leadership fading |
| **Lagging** | < 1 | < 0 | Behind and falling further behind |
| **Improving** | < 1 | ≥ 0 | Behind but catching up — an early turn |
"""
)

section("4. The decision rule")
st.markdown(
    """
| Action | Condition |
| --- | --- |
| **BUY** | Leading **and** RS ratio > 1 **and** RS velocity > 0 **and** momentum Z > 0 |
| **REDUCE / EXIT** | Weakening or Lagging **and** RS ratio < 1 **and** RS velocity < 0 |
| **WATCH / IMPROVING** | Improving stage with RS velocity newly positive |
| **WATCH** | Decision-grade, but no full confirmation either way |
| **DATA UNAVAILABLE** | No authoritative history, or a missing input |

Every condition must hold — a high rank alone never produces a BUY. Rank 1 today is
`{top}`, and it is **{action}**, which is the rule working as intended.
""".format(
        top=decisions.iloc[0]["exposure"] if not decisions.empty else "—",
        action=decisions.iloc[0]["model_action"] if not decisions.empty else "—",
    )
)

section("5. Is the strength durable?")
st.markdown(
    """
A rank says who is strongest *today*. These say whether that has ever held, and are shown on the
Exposure page:

- **Rolling CAGR** — the return of every rolling 1- and 3-year window, as a distribution
  (median, worst, share positive). A point-to-point return depends entirely on two dates.
- **Win rate** — the share of rolling 1-year windows that beat Nifty 50.
- **Win in a falling market** — the same, restricted to windows where Nifty 50 itself fell. This
  is the one that separates real sector strength from leveraged beta: a sector that only wins
  when the market rises *is* the market.
- **Alpha, Beta, R²** — does the excess return survive its beta?
- **Sharpe, Sortino** — return per unit of risk, and of downside risk only. Both assume a
  **6.5%** risk-free rate, which is an assumption, not data.
- **Max drawdown** — depth, dates, duration, and distance from the high today.
"""
)

section("6. Which fund to buy")
st.markdown(
    """
An exposure with a BUY and no instrument is research, not a position. Two vehicle types are
tracked, because they are bought differently:

- **ETF** — trades on exchange at a price that can sit above or below NAV.
- **Index fund** — transacts at NAV, no spread, no premium. Often the better vehicle for a
  monthly rebalance, at the cost of intraday execution.

**Tracking difference** is the number that picks between two funds on the same index: the
annualised return the fund gave up against its index — expense ratio plus everything else, which
is what the holder actually lost. Tracking *error* only says how erratically it was given up; a
fund can have a low error and still bleed a steady 80bps.

**Premium/discount to NAV** and **turnover** come from a point-in-time NSE snapshot. On a retail
book, turnover is converted into *days to build a position* at a 10% participation cap — at a few
lakh per position most sector ETFs clear in a single day, so tracking difference and premium
matter more than liquidity.
"""
)

section("7. The backtest")
st.markdown(
    """
On the last trading day of each period the universe is ranked using **only prices up to that
day**, by the same `rank_exposures` that produces the live board. The top *N* are held until the
next rebalance, so a decision's return is earned entirely after the decision.

Three universes, each stricter than the last:

| Mode | What it measures |
| --- | --- |
| **All indices** | The signal. Buys the top-ranked index whether or not a fund existed. |
| **Buyable only** | The portfolio. A pick must have had a real fund trading **on that date**. |
| **Buyable + entry rule** | What this app would have told you. Also requires the BUY rule. |

Investability is judged from each vehicle's own price history, never from today's lineup — most
of these funds launched in 2024–25, so treating them as available in 2021 would be look-ahead of
the worst kind. When a top pick fails a test the next is taken, down to a set rank; past that the
slot goes to cash. **All indices** still ranks the full 47-exposure universe at every historical
date, including exposures whose fund did not exist yet — it measures the signal, not a portfolio
anyone could have held, precisely because it skips this gate.

**The history window is not the return window.** The ranking needs a full 12-month history before
it can choose anything, so a 60-month window yields 48 months of returns.

**A rebalance transacts at the same close used to rank it.** The signal is computed from prices
through the rebalance date, and the return is also measured from that date's close. A real order
placed after seeing that close fills at least one session later, so this is a small, favourable
timing assumption — modest at a monthly cadence, but real.

**"Buyable" means a fund existed, not that it was easy to trade.** Investability only checks price
history; it does not check historical liquidity, spread, AUM, or whether an index fund was even
open to subscriptions on that date. A rank-3 substitution in 2022 could have been in a much
thinner fund than the same name would be today.

**Transaction costs are deliberately zero.** No brokerage, spread, STT, expense or tax, so a real
book earns less — and more so at higher turnover.
"""
)
note(
    "<b>Read the sensitivity grid before trusting any single result.</b> Running the same window "
    "under six reasonable weightings moves the excess return by roughly 30 percentage points. "
    "That spread comes from a parameter, not from the strategy, so no single row is a finding — "
    "and choosing the weighting that won this sample is fitting the sample.",
    tone="amber",
)

section("8. Where the data comes from")
st.markdown(
    """
**Index histories** — NSE / NiftyIndices, retrieved through the `jugaad-data` adapter.
jugaad-data is a retrieval client, not an authority: it returns whichever series NSE serves. The
total-return endpoint is asked first and the price endpoint accepted as fallback, and which one
answered is recorded per exposure. Nothing is described as total-return unless NSE served one.
The Nifty 50 benchmark comes from the same adapter, so both sides of every relative number share
one calendar and one dividend treatment.

**Fund histories** — NSE traded prices first, then MFAPI scheme NAV, then AMFI, and Yahoo Finance
only as a last resort.

A history needs at least **250 observations** to be decision-grade. Short histories stay visible
but are never padded, extrapolated, or turned into signals. Missing data is left missing.
"""
)

if health:
    section("Current state")
    st.markdown(
        f"- **{health['decision_grade']}/{health['total']}** decision-grade histories, "
        f"all total-return\n"
        f"- **{health['etf_valid']}/{health['etf_total']}** fund price histories ingested\n"
        f"- Composite weights: equal across 1M / 3M / 6M / 12M\n"
        f"- Last refreshed **{health['updated']}**"
    )

st.caption(
    "A quantitative decision aid, not advice. Every figure here is derived from published index "
    "and NAV data; none of it anticipates a market."
)
