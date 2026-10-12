from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.metrics import get_metadata, health_summary
from app.components.theme import mobile_nav, inject_theme, note, page_header, section
from app.data import load_decisions, load_portfolio, strategy_config

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
config = strategy_config()
live = load_portfolio()

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

section("2. The score")
st.markdown(
    """
Every exposure with a full 12-month history is scored at the rebalance close on four
**non-overlapping** segments of its log return, counted in sessions back from that close:

| Segment | Sessions | Weight (v{version}) |
| --- | --- | --- |
| **1M** — the latest month | 0–21 | {w1} |
| **3M-1M** — months 2–3 | 21–63 | {w2} |
| **6M-3M** — months 4–6 | 63–126 | {w3} |
| **12M-6M** — months 7–12 | 126–252 | {w4} |

Each segment is **z-scored across the universe** on that date and the four are combined with the
weights above. The segments tile the year exactly once, so a weight means what it says. The
overlapping 1M/3M/6M/12M composite this replaced weighted the latest month about 7.9× the oldest
six through overlap alone. The latest month is never skipped: in this universe one-month momentum
predicts positively, as industry momentum does (Moskowitz & Grinblatt 1999), rather than
reversing as single stocks do.

> **A Z-score is standardised to a mean of exactly zero.** Roughly half the universe is negative
> by construction. A negative score means *below the universe average on that date* — not a loss.

An alternative, `vol_adjusted_12m` (12-month log return divided by the 126-session EWMA
volatility), is implemented and can be selected in `strategy.json`; v{version} does not use it.
""".format(
        version=config.version,
        w1=f"{config.score_weights.segments['1M']:.0%}",
        w2=f"{config.score_weights.segments['3M-1M']:.0%}",
        w3=f"{config.score_weights.segments['6M-3M']:.0%}",
        w4=f"{config.score_weights.segments['12M-6M']:.0%}",
    )
)

section("3. Relative strength and the four stages · display only")
st.markdown(
    """
Separately from the score, each exposure is placed in a rotation stage using **Mansfield
Relative Strength**, computed weekly. The stage describes; since strategy v1.0 it decides nothing:

- Price relative `RS_t = P_exposure,t / P_Nifty50,t`, sampled each Friday
- `MRS_t = 100 × (RS_t / SMA(RS_t, 52) − 1)` — how far the price relative sits above or below its
  own one-year average
- **RS ratio** `= 1 + MRS/100`: the RS line relative to its own 52-week moving average.
  Above 1 means the line sits above that average. It is not a comparison with Nifty 50 over a
  fixed window: an exposure can trail Nifty over twelve months and still have a ratio above 1.
- **RS velocity** `=` the 13-week change in MRS. Positive means the outperformance is widening.

| Stage | RS ratio | RS velocity | Reading |
| --- | --- | --- | --- |
| **Leading** | ≥ 1 | ≥ 0 | RS line above its 52-week average and rising |
| **Weakening** | ≥ 1 | < 0 | RS line above its 52-week average but falling — leadership fading |
| **Lagging** | < 1 | < 0 | RS line below its 52-week average and falling |
| **Improving** | < 1 | ≥ 0 | RS line below its 52-week average but rising — an early turn |
"""
)

section("4. The portfolio rule")
st.markdown(
    """
One pure function, `construct_target_portfolio` (`src/portfolio/construct.py`), makes every
decision — on this dashboard, in the alerts and at every rebalance of the backtest. Its rules
are versioned in `src/config/strategy.json` (v{version}, config `{hash}`):

1. **Eligible** — a full 12-month history and, because `require_investable` is on, a mapped ETF or
   index fund that had incepted by the decision date, by its recorded inception date (its first
   published NAV in AMFI's record) — never by whether its price happened to download that night.
   Eligible exposures are ranked by score.
2. **Retention buffer** — a current holding is kept while its rank is ≤ **{m}**.
3. **Entry** — an empty slot is filled only from ranks ≤ **{n}**, best first, never deeper.
4. **Cash hurdle** — an exposure is held only while its own 12-month return beats what the
   liquid fund ({cash_name}) returned over the same 12 months — **{rf}** only before the fund's NAV
   history. A top-ranked name that fails leaves its slot in cash rather than handing
   it to a weaker name: relative momentum picks, absolute momentum decides whether to be invested.
5. **Weights** — each slot is 1/{n} of the book; unfilled slots are cash.

| Action | Meaning |
| --- | --- |
| **BUY** | Enters the target (or its weight rises) |
| **HOLD** | Stays in the target at the same weight |
| **TRIM** | Stays, at a lower weight |
| **SELL** | Leaves the target |
| **NOT HELD** | Scored, but not in the target — the status says why |
| **DATA UNAVAILABLE** | No authoritative 12-month history |

The buffer makes the strategy path-dependent — whether a rank-3 name is held depends on whether
it was held last month — so the live target is the end of the strategy's own decision chain over
every completed month in the data, the same chain the backtest replays.
{latest}
""".format(
        version=config.version,
        hash=config.config_hash,
        m=config.retention_buffer_m,
        n=config.target_holdings_n,
        rf=f"{config.risk_free_rate_annual:.1%}",
        cash_name=config.cash_proxy.name if config.cash_proxy else "none configured",
        latest=(
            f"\nThe latest decision, at the **{live.target.as_of:%d %b %Y}** close, holds "
            + (", ".join(f"**{decisions.set_index('exposure_id')['exposure'].get(e, e)}**" for e in live.target.holdings) or "**cash only**")
            + f" with {live.target.cash_weight:.0%} in cash."
            if live is not None and not decisions.empty
            else ""
        ),
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
The backtest has no rules of its own: at every month-end close it calls the same decision chain
as this dashboard, using **only prices up to that close**, and does the accounting.

**Signal at t, fill at t+1.** A decision formed at the month-end close is executed at the next
session's close. The old portfolio earns the session in between, and each period runs from one
fill to the next.

**Costs are charged.** {bps:g} bps per side on every unit of weight bought or sold, deducted at
the fill. Cash earns what the liquid fund's NAV earned between the two fills — the same series as
the hurdle — and {rf} only for periods before the fund's NAV history.

**Back-calculated history.** NSE computes an index's values back to its base date when it launches
it, so years of every new index's history were never tradable. Each index's launch date is recorded
in `universe.json` from its NSE Indices factsheet, and the Backtest page can exclude everything
before it.

Two universes:

| Mode | What it measures |
| --- | --- |
| **Strategy (buyable)** | The portfolio. A pick must have had a real fund with a price **on that date**. |
| **All indices** | The signal. The same rules over every index, whether or not a fund existed. |

Investability is judged from each vehicle's recorded inception date, never from today's lineup — most
of these funds launched in 2024–25, so treating them as available in 2021 would be look-ahead of
the worst kind.

**The history window is not the return window.** The score needs a full 12-month history before
it can choose anything, so the first year of data is warm-up.

**"Buyable" means a fund existed, not that it was easy to trade.** Investability only checks price
history; it does not check historical liquidity, spread, AUM, or whether an index fund was even
open to subscriptions on that date.

**v{version} was specified after studying this window.** The segment weights, N, the buffer and the
hurdle were fixed before this backtest was run, but by people who had looked at these four years.
Treat it as a check on the rules, not as out-of-sample evidence.
""".format(
        bps=config.cost_bps_per_side,
        rf=f"{config.risk_free_rate_annual:.1%}",
        version=config.version,
    )
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
    # Read from metadata rather than stated: both were once hard-coded and would
    # have gone on claiming "all total-return" after NSE served a price index.
    metadata = get_metadata()
    value_types = list((metadata.get("value_type_by_canonical_exposure") or {}).values())
    tri = sum(v == "TRI" for v in value_types)
    value_note = (
        "all total-return"
        if value_types and tri == len(value_types)
        else f"{tri} of {len(value_types)} total-return"
    )
    weights = config.score_weights.segments
    if config.score_weights.method != "segment_composite":
        weight_note = config.score_weights.method
    elif len(set(weights.values())) == 1:
        weight_note = "equal across " + " / ".join(weights)
    else:
        weight_note = " / ".join(f"{k} {v:.0%}" for k, v in weights.items())
    section("Current state")
    st.markdown(
        f"- **{health['decision_grade']}/{health['total']}** decision-grade histories, "
        f"{value_note}\n"
        f"- **{health['etf_valid']}/{health['etf_total']}** fund price histories ingested\n"
        f"- Strategy v{config.version} (config {config.config_hash}); score weights: {weight_note}\n"
        f"- Last refreshed **{health['updated']}**"
    )

st.caption(
    "A quantitative decision aid, not advice. Every figure here is derived from published index "
    "and NAV data; none of it anticipates a market."
)
