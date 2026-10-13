"""Method: the Paresh app's Guide page (src/ui/views/guide_view.py), for this strategy.

Element by element: the page head, a strip of readings for the rules' settings,
the Guide's segmented control between handbook sections, its white cards of
numbered step tiles, kit tables for the matrices, and st.latex for the maths.
The worked example rebuilds the latest decision's score from its own numbers
and says whether it matches the score the portfolio used.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.explain import score_breakdown  # noqa: E402
from app.components.fmt import pct  # noqa: E402
from app.components.metrics import get_metadata, health_summary  # noqa: E402
from app.data import load_decisions, load_portfolio, strategy_config  # noqa: E402
from app.kit import page_kit as kit  # noqa: E402
from app.kit.theme import render_saas_table  # noqa: E402
from src.config import SEGMENTS  # noqa: E402

config = strategy_config()
live = load_portfolio()
decisions = load_decisions()
names = decisions.set_index("exposure_id")["exposure"].to_dict() if not decisions.empty else {}
n, m = int(config.target_holdings_n), int(config.retention_buffer_m)
rf = f"{config.risk_free_rate_annual:.1%}"
weights = config.score_weights.segments
fund = config.cash_proxy.name if config.cash_proxy else "none configured"

# The Guide's step tiles: a mono kicker in its accent, a title, one or two lines.
_ACCENTS = ("#4f46e5", "#067647", "#B54708", "#7c3aed", "#0284c7")


def _tiles(items: list[tuple[str, str]], kicker: str = "STEP") -> None:
    """(title, body_html) tiles; titles are escaped, bodies are trusted markup built on this page."""
    cells = "".join(
        '<div style="background:#F4F5F8;border:1px solid #E3E6EB;border-radius:8px;padding:12px">'
        f'<div style="font-family:\'Geist Mono\',monospace;font-size:11px;font-weight:700;'
        f'color:{_ACCENTS[i % len(_ACCENTS)]}">{kicker} {i + 1:02d}</div>'
        f'<div style="font-weight:600;font-size:13px;color:#0E1726;margin-top:2px">{html.escape(title)}</div>'
        f'<div style="font-size:13px;color:#5E6878;line-height:1.5;margin-top:4px">{body}</div></div>'
        for i, (title, body) in enumerate(items)
    )
    st.html('<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;'
            f'font-family:\'Geist\',sans-serif">{cells}</div>')


kit.page_head("Method", f"Strategy v{config.version} · every rule in the order it applies, then the latest decision by hand")
kit.readings([
    kit.Reading("Holdings", f"Top {n}", f"kept while rank ≤ {m}"),
    kit.Reading("Score", "4 segments", " / ".join(f"{k} {v:.0%}" for k, v in weights.items())),
    kit.Reading("Hurdle", "Liquid fund 12M", f"{rf} before its NAV history"),
    kit.Reading("Execution", "t+1 close", f"{config.cost_bps_per_side:g} bps per side"),
    kit.Reading("Config", config.config_hash, "src/config/strategy.json"),
], "Strategy settings")

SECTIONS = ["The score", "Score to portfolio", "Worked example", "Rotation", "Backtest & data"]
section = st.segmented_control("Method sections", SECTIONS, default=SECTIONS[0], key="method_nav",
                               label_visibility="collapsed") or SECTIONS[0]

# --------------------------------------------------------------------------- #
# 1. The score
# --------------------------------------------------------------------------- #
if section == "The score":
    with kit.card("The score", "md_score", "non-overlapping momentum, z-scored across the universe"):
        st.markdown("Each **exposure** is scored on the Nifty index that defines it, never on a fund. At a rebalance "
                    "close *t*, with 252 sessions of history, it gets four non-overlapping log returns:")
        st.latex(r"r^{(a,b)}_{i,t} \;=\; \ln P_{i,\,t-a} \;-\; \ln P_{i,\,t-b}")
        render_saas_table(pd.DataFrame({
            "Segment": list(SEGMENTS),
            "Sessions (a–b)": [f"{a}–{b}" for a, b in SEGMENTS.values()],
            "Covers": ["the latest month", "months 2–3", "months 4–6", "months 7–12"],
            f"Weight (v{config.version})": [f"{weights[k]:.0%}" for k in SEGMENTS],
        }))
        st.markdown("Standardised across the valid universe on that date, then combined:")
        st.latex(r"z_{i,k} \;=\; \frac{r_{i,k} - \bar r_{k}}{\sigma_{k}} \qquad\qquad S_i \;=\; \sum_{k} w_k \, z_{i,k}")
        kit.caption("The segments tile the year once, so a weight means what it says; overlapping 1M/3M/6M/12M "
                    "returns weighted the latest month about 7.9× the oldest six. The latest month is kept: industry "
                    "momentum continues at one month (Moskowitz & Grinblatt 1999). A negative score is below the "
                    "universe average, not a loss.")

# --------------------------------------------------------------------------- #
# 2. The portfolio rule
# --------------------------------------------------------------------------- #
elif section == "Score to portfolio":
    with kit.card("From score to portfolio", "md_rule", "one pure function, construct_target_portfolio"):
        _tiles([
            ("Eligible", "A full 12-month history and a mapped ETF or index fund whose first AMFI NAV is on or "
             "before <i>t</i>. Ranked by <i>S</i>."),
            ("Cash hurdle", f"Held only while its 12-month return beats the liquid fund's "
             f"({html.escape(fund)}); {rf} before its NAV history. A failing slot goes to cash."),
            ("Retention buffer", f"A holding stays while rank ≤ <b>{m}</b>; an empty slot fills from rank ≤ "
             f"<b>{n}</b>, best first."),
            ("Weights", f"Each slot is 1/{n} of the book; an unfilled slot earns the liquid fund's NAV."),
            ("Execution", f"Signal at the month-end close, fill at the next session's close; "
             f"{config.cost_bps_per_side:g} bps per side on the weight traded."),
        ])
        st.latex(
            r"\text{hold}_i \iff \Big(R^{12M}_{i,t} > R^{12M}_{\text{cash},t}\Big) \wedge "
            r"\Big(\text{rank}_i \le " + str(m) + r" \text{ if held at } t-1,\;\; \text{rank}_i \le " + str(n)
            + r" \text{ otherwise}\Big)"
        )
    with kit.card("Decisions", "md_actions", "what each label on the Portfolio and Screener means"):
        render_saas_table(pd.DataFrame({
            "Decision": ["BUY", "HOLD", "TRIM", "SELL", "NOT HELD", "DATA UNAVAILABLE"],
            "Meaning": ["Enters the target, or its weight rises", "Stays at the same weight",
                        "Stays, at a lower weight", "Leaves the target",
                        "Scored, but not in the target; the status says why", "No authoritative 12-month history"],
        }))

# --------------------------------------------------------------------------- #
# 3. Worked example: the latest decision, by hand
# --------------------------------------------------------------------------- #
elif section == "Worked example":
    with kit.card("Worked example", "md_example", "the latest decision, reproduced from its own numbers"):
        if live is None:
            kit.caption("No decision is available to work through yet.")
        else:
            target = live.target
            ranking = target.ranking
            example = target.holdings[0] if target.holdings else str(ranking["rank"].astype(float).idxmin())
            row = ranking.loc[example]
            name = names.get(example, example)
            breakdown = score_breakdown(ranking, example, weights)
            composite = float(breakdown["Contribution"].sum())
            eligible = int(ranking["eligible"].sum())
            st.markdown(f"At the **{target.as_of:%d %b %Y}** close, {int(ranking['valid'].sum())} exposures had a "
                        f"full year of history and {eligible} were eligible. Take **{name}**:")
            render_saas_table(pd.DataFrame({
                "Segment": breakdown["Segment"],
                "Sessions back": breakdown["Sessions back"],
                "Log return": breakdown["Log return"].map(lambda v: f"{v:+.4f}"),
                "Universe mean": breakdown["Universe mean"].map(lambda v: f"{v:+.4f}"),
                "Universe s.d.": breakdown["Universe s.d."].map(lambda v: f"{v:.4f}"),
                "z": breakdown["z"].map(lambda v: f"{v:+.3f}"),
                "Weight": breakdown["Weight"].map(lambda v: pct(v, 0)),
                "Contribution (w × z)": breakdown["Contribution"].map(lambda v: f"{v:+.4f}"),
            }))
            matches = abs(composite - float(row["score"])) < 1e-9
            terms = " + ".join(f"{w:.2f}×({z:+.3f})" for w, z in zip(breakdown["Weight"], breakdown["z"]))
            tex_name = "".join({"&": r"\&", "%": r"\%", "_": r"\_", "#": r"\#", "$": r"\$"}.get(c, c)
                               for c in name if c not in "\\{}")
            st.latex(rf"S_{{\text{{{tex_name}}}}} = {terms} = {composite:+.4f}")
            hurdle = float(target.cash_hurdle_12m)
            r12 = float(row["return_12m"])
            held_before = float(row.get("prior_weight", 0.0) or 0.0) > 0
            rank = int(row["rank"]) if pd.notna(row.get("rank")) else None
            needed = m if held_before else n
            decision = next((d.action for d in target.decisions if d.exposure_id == example), "NOT HELD")
            _tiles([
                ("Score", f"{composite:+.4f}, " + ("identical to the score the portfolio used." if matches
                                                  else f"against {float(row['score']):+.4f} in the decision.")),
                ("Rank", f"#{rank} of {eligible} eligible." if rank else "Not ranked: not eligible."),
                ("Hurdle", f"12-month return {r12:+.1%} against the liquid fund's {hurdle:.2%}: "
                 + ("<b>passes</b>." if r12 > hurdle else "<b>fails</b>, so the slot would go to cash.")),
                ("Buffer", ("Already held, so it stays while rank ≤ " if held_before else "Not held before, so it needs "
                            "rank ≤ ") + f"{needed}" + (": it does." if rank and rank <= needed else ".")),
                ("Result", f"<b>{html.escape(name)}: {html.escape(decision)}</b> at "
                 f"{float(target.weights.get(example, 0.0)):.0%} of the book. {html.escape(str(row.get('reason', '') or ''))}"),
            ])

# --------------------------------------------------------------------------- #
# 4. Relative rotation: display only
# --------------------------------------------------------------------------- #
elif section == "Rotation":
    with kit.card("Relative rotation", "md_rrg", "display only · since v1.0 it decides nothing"):
        st.latex(r"\text{RS}_t = \frac{P_{i,t}}{P_{\text{Nifty 50},t}}, \qquad "
                 r"\text{MRS}_t = 100\left(\frac{\text{RS}_t}{\text{SMA}_{52}(\text{RS})_t} - 1\right), \qquad "
                 r"\text{RS ratio} = 1 + \tfrac{\text{MRS}}{100}")
        render_saas_table(pd.DataFrame({
            "Quadrant": ["Leading", "Weakening", "Lagging", "Improving"],
            "RS ratio": ["≥ 1", "≥ 1", "< 1", "< 1"],
            "RS velocity": ["≥ 0", "< 0", "< 0", "≥ 0"],
        }))
        kit.caption("Weekly. RS velocity is the 13-week change in MRS. The ratio compares the RS line with its own "
                    "one-year average, not with Nifty 50 over a fixed window.")

# --------------------------------------------------------------------------- #
# 5. The backtest, and the data
# --------------------------------------------------------------------------- #
else:
    kit.note(f"v{config.version} was specified after studying this window.",
             "Treat the backtest as a check on the rules, not out-of-sample evidence.")
    with kit.card("The backtest", "md_backtest", "no rules of its own"):
        _tiles([
            ("Same decisions", "Each month-end calls the Portfolio page's decision chain on prices up to that close."),
            ("Accounting", "Fill at <i>t+1</i>, costs at the fill, cash at the liquid fund's NAV."),
            ("Investability", "From each fund's recorded inception, never from today's lineup."),
            ("Pre-launch history", "Back-calculated before an index's launch; Evidence shows it with and without."),
        ])
    health = health_summary()
    metadata = get_metadata()
    value_types = list((metadata.get("value_type_by_canonical_exposure") or {}).values())
    tri = sum(v == "TRI" for v in value_types)
    with kit.card("Where the data comes from", "md_data"):
        _tiles([
            ("Index histories", "NSE / NiftyIndices via <code>jugaad-data</code>, total-return endpoint first; "
             "BSE indices from BSE Index Services, a price index."),
            ("Funds", "NSE prices, then AMFI NAV via MFAPI (verified by ISIN), then AMFI; Yahoo last."),
            ("Decision-grade", "250 observations; short histories are never padded or extrapolated."),
        ], kicker="SOURCE")
        if health:
            kit.metric_row([
                kit.Metric("Decision-grade histories", f"{health['decision_grade']}/{health['total']}",
                           help="all total-return" if value_types and tri == len(value_types)
                           else f"{tri} of {len(value_types)} total-return"),
                kit.Metric("Fund price histories", f"{health['etf_valid']}/{health['etf_total']}"),
                kit.Metric("Last refreshed", str(health["updated"])),
            ], key="md_data")

kit.caption("A quantitative decision aid, not advice.")
