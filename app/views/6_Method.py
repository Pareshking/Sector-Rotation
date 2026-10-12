from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.explain import score_breakdown  # noqa: E402
from app.components.metrics import get_metadata, health_summary  # noqa: E402
from app.components.tables import show_table  # noqa: E402
from app.components.theme import _esc, kpi_grid, note, page_header, section, steps  # noqa: E402
from app.data import load_decisions, load_portfolio, strategy_config  # noqa: E402
from src.config import SEGMENTS  # noqa: E402

config = strategy_config()
live = load_portfolio()
decisions = load_decisions()
names = decisions.set_index("exposure_id")["exposure"].to_dict() if not decisions.empty else {}
n, m = int(config.target_holdings_n), int(config.retention_buffer_m)
rf = f"{config.risk_free_rate_annual:.1%}"
weights = config.score_weights.segments

page_header(
    "How this works",
    f"Method · Strategy v{config.version}",
    "Every rule the strategy applies, in the order it applies them, then the latest decision worked through by hand.",
)
kpi_grid(
    [
        ("Holdings", f"Top {n}", f"kept while rank ≤ {m}", "accent"),
        ("Score", "4 segments", " / ".join(f"{k} {v:.0%}" for k, v in weights.items()), ""),
        ("Hurdle", "Liquid fund 12M", f"{rf} before its NAV history", "info"),
        ("Execution", "t+1 close", f"{config.cost_bps_per_side:g} bps per side", ""),
        ("Config", config.config_hash, "src/config/strategy.json", ""),
    ]
)

# --------------------------------------------------------------------------- #
# 1. The score
# --------------------------------------------------------------------------- #
section("1 · The score", "Non-overlapping momentum, z-scored across the universe")
st.markdown(
    "An **exposure** is a sector or theme represented by the Nifty index that defines it, never by an ETF: an ETF's "
    "liquidity or tracking error is a property of the fund, not strength in the sector. At a rebalance close *t*, "
    "every exposure with 252 sessions of history gets four **non-overlapping** log returns, counted in sessions back "
    "from *t*:"
)
st.latex(r"r^{(a,b)}_{i,t} \;=\; \ln P_{i,\,t-a} \;-\; \ln P_{i,\,t-b}")
show_table(
    pd.DataFrame(
        {
            "Segment": list(SEGMENTS),
            "Sessions (a–b)": [f"{a}–{b}" for a, b in SEGMENTS.values()],
            "Covers": ["the latest month", "months 2–3", "months 4–6", "months 7–12"],
            f"Weight (v{config.version})": [weights[k] for k in SEGMENTS],
        }
    ),
    hide_index=True,
    width="stretch",
    column_config={f"Weight (v{config.version})": st.column_config.NumberColumn(format="percent")},
)
st.markdown("Each segment is standardised across the valid universe on that date, then the four are combined:")
st.latex(r"z_{i,k} \;=\; \frac{r_{i,k} - \bar r_{k}}{\sigma_{k}} \qquad\qquad S_i \;=\; \sum_{k} w_k \, z_{i,k}")
note(
    "<b>The segments tile the year exactly once, so a weight means what it says.</b> The overlapping 1M/3M/6M/12M "
    "composite this replaced weighted the latest month about 7.9× the oldest six through overlap alone. The latest "
    "month is never skipped: industry momentum continues at one month rather than reversing as single stocks do "
    "(Moskowitz &amp; Grinblatt 1999). A z-score has mean zero by construction, so a negative score means "
    "<i>below the universe average</i>, not a loss."
)

# --------------------------------------------------------------------------- #
# 2. The portfolio rule
# --------------------------------------------------------------------------- #
section("2 · From score to portfolio", "One pure function, construct_target_portfolio, makes every decision")
steps(
    [
        ("Eligible", "A full 12-month history and, because <code>require_investable</code> is on, a mapped ETF or index "
         "fund whose recorded inception (its first published NAV in AMFI's record) is on or before <i>t</i>. Eligible "
         "exposures are ranked by <i>S</i>."),
        ("Absolute momentum hurdle", "An exposure may be held only while its own 12-month return beats what the liquid "
         f"fund ({_esc(config.cash_proxy.name if config.cash_proxy else 'none configured')}) returned over the same 12 "
         f"months; {rf} only before the fund's NAV history. A top-ranked name that fails leaves its slot in cash."),
        ("Retention buffer", f"A current holding is kept while its rank is ≤ <b>{m}</b>; an empty slot is filled only "
         f"from ranks ≤ <b>{n}</b>, best first. The gap between {n} and {m} is what stops month-to-month churn."),
        ("Weights", f"Each slot is 1/{n} of the book; an unfilled slot is cash, earning the liquid fund's NAV."),
        ("Execution", f"Signal at the month-end close <i>t</i>, fill at the next session's close; "
         f"{config.cost_bps_per_side:g} bps per side on every unit of weight traded."),
    ]
)
st.latex(
    r"\text{hold}_i \iff \Big(R^{12M}_{i,t} > R^{12M}_{\text{cash},t}\Big) \wedge "
    r"\Big(\text{rank}_i \le " + str(m) + r" \text{ if held at } t-1,\;\; \text{rank}_i \le " + str(n)
    + r" \text{ otherwise}\Big)"
)
st.markdown(
    "| Action | Meaning |\n| --- | --- |\n| **BUY** | Enters the target, or its weight rises |\n"
    "| **HOLD** | Stays at the same weight |\n| **TRIM** | Stays, at a lower weight |\n| **SELL** | Leaves the target |\n"
    "| **NOT HELD** | Scored, but not in the target; the status says why |\n"
    "| **DATA UNAVAILABLE** | No authoritative 12-month history |"
)

# --------------------------------------------------------------------------- #
# 3. Worked example: the latest decision, by hand
# --------------------------------------------------------------------------- #
section("3 · Worked example", "The latest decision, reproduced from its own numbers")
if live is None:
    note("No decision is available to work through yet.", tone="warn")
else:
    target = live.target
    ranking = target.ranking
    example = target.holdings[0] if target.holdings else str(ranking["rank"].astype(float).idxmin())
    row = ranking.loc[example]
    name = names.get(example, example)
    breakdown = score_breakdown(ranking, example, weights)
    composite = float(breakdown["Contribution"].sum())
    st.markdown(
        f"At the **{target.as_of:%d %b %Y}** close, {int(ranking['valid'].sum())} exposures had a full year of history "
        f"and {int(ranking['eligible'].sum())} were eligible. Take **{_esc(name)}**:"
    )
    show_table(
        breakdown,
        hide_index=True,
        width="stretch",
        column_config={
            "Log return": st.column_config.NumberColumn(format="%+.4f"),
            "Universe mean": st.column_config.NumberColumn(format="%+.4f"),
            "Universe s.d.": st.column_config.NumberColumn(format="%.4f"),
            "z": st.column_config.NumberColumn(format="%+.3f"),
            "Weight": st.column_config.NumberColumn(format="percent"),
            "Contribution": st.column_config.NumberColumn(format="%+.4f", help="Weight × z"),
        },
    )
    matches = abs(composite - float(row["score"])) < 1e-9
    terms = " + ".join(f"{w:.2f}×({z:+.3f})" for w, z in zip(breakdown["Weight"], breakdown["z"]))
    tex_name = "".join({"&": r"\&", "%": r"\%", "_": r"\_", "#": r"\#", "$": r"\$"}.get(c, c) for c in name if c not in "\\{}")
    st.latex(rf"S_{{\text{{{tex_name}}}}} = {terms} = {composite:+.4f}")
    hurdle = float(target.cash_hurdle_12m)
    r12 = float(row["return_12m"])
    held_before = float(row.get("prior_weight", 0.0) or 0.0) > 0
    rank = int(row["rank"]) if pd.notna(row.get("rank")) else None
    steps(
        [
            ("Score", f"{composite:+.4f}, " + ("identical to the score the portfolio used." if matches
                                              else f"against {float(row['score']):+.4f} in the decision.")),
            ("Rank", f"#{rank} of {int(ranking['eligible'].sum())} eligible." if rank else "Not ranked: not eligible."),
            ("Hurdle", f"12-month return {r12:+.1%} against the liquid fund's {hurdle:.2%}: "
             + ("<b>passes</b>." if r12 > hurdle else "<b>fails</b>, so the slot would go to cash.")),
            ("Buffer", ("Already held, so it stays while rank ≤ " if held_before else "Not held before, so it needs rank ≤ ")
             + f"{m if held_before else n}" + (" — it does." if rank and rank <= (m if held_before else n) else ".")),
            ("Result", f"<b>{_esc(name)}: {_esc(next((d.action for d in target.decisions if d.exposure_id == example), 'NOT HELD'))}"
             f"</b> at {float(target.weights.get(example, 0.0)):.0%} of the book. {_esc(row.get('reason', ''))}"),
        ]
    )

# --------------------------------------------------------------------------- #
# 4. Display-only context, the backtest, the data
# --------------------------------------------------------------------------- #
section("4 · Relative rotation · display only", "Describes; since v1.0 it decides nothing")
st.latex(r"\text{RS}_t = \frac{P_{i,t}}{P_{\text{Nifty 50},t}}, \qquad "
         r"\text{MRS}_t = 100\left(\frac{\text{RS}_t}{\text{SMA}_{52}(\text{RS})_t} - 1\right), \qquad "
         r"\text{RS ratio} = 1 + \tfrac{\text{MRS}}{100}")
st.markdown(
    "Weekly. **RS velocity** is the 13-week change in MRS. Leading: ratio ≥ 1 and velocity ≥ 0; Weakening: ratio ≥ 1, "
    "velocity < 0; Lagging: both below; Improving: ratio < 1, velocity ≥ 0. The ratio compares the RS line with its "
    "own one-year average, not with Nifty 50 over a fixed window."
)

section("5 · The backtest", "No rules of its own")
st.markdown(
    "At every month-end close the backtest calls the same decision chain as the Portfolio page, using **only prices "
    "up to that close**, and does the accounting: fill at *t+1*, costs at the fill, cash at the liquid fund's NAV. "
    "Investability is judged from each fund's recorded inception date, never from today's lineup. Indices that launched "
    "inside the window carry back-calculated history before their launch date, and the Evidence page shows the result "
    "with and without it."
)
note(
    f"<b>v{config.version} was specified after studying this window.</b> The weights, N, the buffer and the hurdle were "
    "fixed before the backtest ran, but by people who had looked at these years. Treat it as a check on the rules, not "
    "as out-of-sample evidence, and read the sensitivity grid before trusting any single result.",
    tone="warn",
)

section("6 · Where the data comes from")
health = health_summary()
metadata = get_metadata()
value_types = list((metadata.get("value_type_by_canonical_exposure") or {}).values())
tri = sum(v == "TRI" for v in value_types)
st.markdown(
    "**Index histories:** NSE / NiftyIndices through the `jugaad-data` adapter, total-return endpoint first; which one "
    "answered is recorded per exposure. **Funds:** NSE prices, then AMFI NAV via MFAPI (verified by ISIN), then AMFI, "
    "and Yahoo only as a last resort. A history needs 250 observations to be decision-grade; short histories are "
    "never padded or extrapolated."
)
if health:
    st.markdown(
        f"- **{health['decision_grade']}/{health['total']}** decision-grade histories, "
        f"{'all total-return' if value_types and tri == len(value_types) else f'{tri} of {len(value_types)} total-return'}\n"
        f"- **{health['etf_valid']}/{health['etf_total']}** fund price histories\n"
        f"- Last refreshed **{health['updated']}**"
    )
st.caption("A quantitative decision aid, not advice.")
