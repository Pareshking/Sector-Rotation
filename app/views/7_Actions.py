"""Actions: the Paresh app's Actions page (src/ui/views/actions_view.py), on this strategy's rules.

Sell the holdings that break a rule, buy the top-ranked exposures that beat
cash into the free slots, hold the rest -- worked out by the strategy's own
``construct_target_portfolio`` on today's closes (``app/data.py: load_preview``).
The orders are struck at the month-end close and filled at the next session's,
so this is a preview: a name can still move in or out before then. For the
model book or for the reader's own ETF holdings.

The layout, the components and the stylesheet are Paresh's (``app/kit``); the
cushions are this strategy's two rules: room inside the rank buffer and the
12-month return's margin over the liquid fund's. "My holdings" are kept in
this session only (Paresh keeps them in browser storage).
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

from app.components.actions import (  # noqa: E402
    STATUS_LABEL,
    UNKNOWN,
    WATCH,
    HURDLE_SCALE,
    Rules,
    assess,
    buy_orders,
    holdings_from_kite_csv,
    map_symbols,
    next_rebalance,
    parse_holdings,
    plan_rebalance,
    prior_weights,
    sessions_between,
    to_text,
)
from app.data import (  # noqa: E402
    best_vehicle,
    load_decisions,
    load_etf_prices,
    load_index_panel,
    load_model_book,
    load_portfolio,
    load_preview,
    strategy_config,
    vehicle_frame,
)
from app.kit import page_kit as kit  # noqa: E402
from app.kit.theme import render_saas_table  # noqa: E402
from src.portfolio.book import MODEL_BOOK_CAPITAL  # noqa: E402

SOURCES = ["Model book", "My holdings"]
HOLDINGS_KEY = "ac_holdings"
KITE_CAPITAL_KEY = "ac_kite_capital"
KITE_MIN_CAPITAL = 10_000
KITE_MAX_CAPITAL = 1_000_000_000
NO_FUND: tuple = (None, None, None)

# Paresh's exit-watch grid has three cushion columns (rank, 50D EMA, 52W high);
# this strategy has two, so its rows drop one track. Scoped to this page.
GRID_CSS = """<style>
.xw.sr-xw .xw-row { grid-template-columns: 150px 150px 1fr 1fr minmax(0, 1.4fr) 80px; }
@media (max-width: 900px) {
  .xw.sr-xw .xw-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .xw.sr-xw .xw-s { grid-column: 1; }
  .xw.sr-xw .xw-pill { grid-column: 2; }
}
</style>"""


def _day(t: pd.Timestamp, weekday: bool = False) -> str:
    return (f"{t:%a} " if weekday else "") + f"{t:%d %b}"


def _pct(v) -> str:
    v = pd.to_numeric(v, errors="coerce")
    return "—" if pd.isna(v) else f"{'+' if v >= 0 else '−'}{abs(float(v)) * 100:.1f}%"


def _href(symbol: str | None, label: str) -> str:
    """A fund's chart on TradingView; an index fund has no NSE symbol and no link."""
    if not symbol:
        return f"<a>{html.escape(label)}</a>"
    return f'<a href="{kit.tradingview_url(symbol)}" target="_blank" rel="noopener">{html.escape(label)}</a>'


def _who(fund: tuple, exposure: str) -> str:
    """The fund cell: an ETF by its NSE symbol over the exposure; an index fund by the exposure over its name."""
    sym, _last, name = fund
    if sym:
        return f'<span class="xw-s">{_href(sym, sym)}<small>{html.escape(exposure)}</small></span>'
    return f'<span class="xw-s">{_href(None, exposure)}<small>{html.escape(name or "")}</small></span>'


def _bar(room: float | None, ok: bool, scale: float, label: str) -> str:
    """A cushion bar: full = lots of room, short = close to the line, red = broken."""
    if not ok:
        return (f'<span class="xw-g broken"><b>{html.escape(label)}</b>'
                '<i><i style="width:100%"></i></i></span>')
    w = 0.0 if room is None or pd.isna(room) else max(4.0, min(100.0, float(room) / scale * 100))
    tone = "tight" if w < 30 else "ok"
    return (f'<span class="xw-g {tone}"><b>{html.escape(label)}</b>'
            f'<i><i style="width:{w:.0f}%"></i></i></span>')


def _ret_cell(ret) -> str:
    cls = "" if ret is None or pd.isna(ret) else ("up" if ret >= 0 else "down")
    return f'<span class="xw-ret {cls}">{_pct(ret)}</span>'


def rows_html(a: pd.DataFrame, since: dict[str, float], funds: dict, rules: Rules, hurdle: float) -> str:
    out = []
    for _, r in a.iterrows():
        e = str(r["exposure_id"])
        status = r["status"]
        if status == UNKNOWN:
            out.append(
                f'<div class="xw-row unknown"><span class="xw-s">{_href(e, e)}<small>not in the universe</small></span>'
                f'<span class="xw-pill unknown">{STATUS_LABEL[UNKNOWN]}</span>'
                f'<span class="xw-why" style="grid-column: 3 / -1">No rule can be checked: '
                "no exposure is bought through this symbol.</span></div>")
            continue
        rank, room = r["rank"], r["rank_room"]
        if pd.isna(rank):
            rank_cell = _bar(None, False, 1, "off the list")
        elif room < 0:
            rank_cell = _bar(None, False, 1, f"#{int(rank)} · past {rules.buffer_m}")
        else:
            rank_cell = _bar(room, True, rules.buffer_m, f"#{int(rank)} · {int(room)} to go")
        c = r["hurdle_cushion"]
        hurdle_cell = _bar(c, bool(r["hurdle_ok"]), HURDLE_SCALE,
                           "—" if pd.isna(c) else f"{c * 100:.1f} pts cushion" if r["hurdle_ok"]
                           else f"{abs(c) * 100:.1f} pts below")
        out.append(
            f'<div class="xw-row {status}">{_who(funds.get(e, NO_FUND), str(r.get("name") or e))}'
            f'<span class="xw-pill {status}">{STATUS_LABEL[status]}</span>'
            f"{rank_cell}{hurdle_cell}"
            f'<span class="xw-why">{html.escape(r["why"] or "clear of both")}</span>'
            f"{_ret_cell(since.get(e))}</div>"
        )
    head = ('<div class="xw-row xw-head"><span>Holding</span><span>At the next rebalance</span>'
            f"<span>Rank buffer (top {rules.buffer_m})</span><span>12M vs cash ({hurdle:.1%})</span>"
            '<span>Closest to</span><span class="xw-ret">Since entry</span></div>')
    return f'<div class="xw sr-xw" role="table" aria-label="Exit watch">{head}{"".join(out)}</div>'


def sells_html(a: pd.DataFrame, sells: list[str], since: dict[str, float], funds: dict, entries) -> str:
    by = a.set_index("exposure_id")
    rows = []
    for e in sells:
        name = str(by.loc[e, "name"]) if e in by.index else e
        why = by.loc[e, "why"] if e in by.index else ""
        rows.append(
            f'<div class="ac-row sell">{_who(funds.get(e, NO_FUND), name)}'
            f'<span class="ac-why"><b>Sell</b> · {html.escape(why)}</span>'
            f'<span class="ac-when">{html.escape(entries(e))}</span>'
            f"{_ret_cell(since.get(e))}</div>")
    return f'<div class="xw">{"".join(rows)}</div>'


def buys_html(ranking: pd.DataFrame, buys: list[str], funds: dict, returns: pd.DataFrame, rules: Rules) -> str:
    rows = ['<div class="ac-row buy ac-head"><span>Fund</span><span>Rank</span><span>Why</span>'
            '<span class="n">Price</span><span class="n">3M</span><span class="n">6M</span>'
            '<span class="n">12M</span></div>']
    for e in buys:
        r = ranking.loc[e]
        price = funds.get(e, NO_FUND)[1]
        name = str(r.get("name") or e)
        price_txt = "—" if price is None or pd.isna(price) else f"₹{float(price):,.2f}"
        ret = returns.loc[e] if e in returns.index else pd.Series(dtype=float)
        rows.append(
            f'<div class="ac-row buy">{_who(funds.get(e, NO_FUND), name)}'
            f'<span class="n">#{int(r["rank"])}</span>'
            f'<span class="ac-why"><b class="up">Buy</b> · in the top {rules.top_n} and beats cash</span>'
            f'<span class="n">{price_txt}</span><span class="n up">{_pct(ret.get("return_3M"))}</span>'
            f'<span class="n up">{_pct(ret.get("return_6M"))}</span>'
            f'<span class="n up">{_pct(r.get("return_12m"))}</span></div>')
    return f'<div class="xw">{"".join(rows)}</div>'


def _price(symbol: str | None, key: str | None) -> float | None:
    """The fund's last NSE price, else its last published NAV."""
    vf = vehicle_frame()
    if symbol and not vf.empty and "last_price" in vf:
        p = pd.to_numeric(vf.loc[vf["symbol"] == symbol, "last_price"], errors="coerce").dropna()
        if not p.empty and float(p.iloc[0]) > 0:
            return float(p.iloc[0])
    navs = load_etf_prices()
    col = key or symbol
    if col and col in navs.columns:
        s = pd.to_numeric(navs[col], errors="coerce").dropna()
        if not s.empty:
            return float(s.iloc[-1])
    return None


def _fund(exposure_id: str, as_of: pd.Timestamp, symbol: str | None = None) -> tuple:
    """(NSE symbol, last price, fund name) of the fund held, or of the one the vehicle rule picks."""
    if symbol:
        return symbol, _price(symbol, symbol), symbol
    choice = best_vehicle(exposure_id, as_of)
    if choice is None:
        return NO_FUND
    return choice.symbol, _price(choice.symbol, choice.key), choice.name


def _entries() -> list[tuple[str, float | None]]:
    return list(st.session_state.get(HOLDINGS_KEY, []))


def _edit_holdings() -> None:
    def _save_text():
        st.session_state[HOLDINGS_KEY] = parse_holdings(st.session_state.get("xw_text", ""))

    current = to_text(_entries())
    if st.session_state.get("_xw_shown") != current:
        st.session_state["xw_text"] = current
        st.session_state["_xw_shown"] = current
    with st.container(horizontal=True, vertical_alignment="bottom", key="xw_editbar"):
        st.text_input("Your holdings", key="xw_text",
                      placeholder="ETF symbols with an optional buy price, e.g. METAL 11.3, MODEFENCE@105, BANKBEES")
        st.button("Save", type="primary", key="xw_save", on_click=_save_text)
        with st.popover("Upload from Kite", icon=":material/upload:"):
            st.caption("Kite Console → Portfolio → Holdings → Download (CSV). Symbols and "
                       "average cost are read; quantities are not stored.")
            up = st.file_uploader("Holdings CSV", type=["csv"], key="xw_csv",
                                  label_visibility="collapsed")
            if up is not None:
                try:
                    got = holdings_from_kite_csv(pd.read_csv(up))
                except Exception as exc:  # a wrong file is reported, not raised
                    st.error(f"Could not read that file: {exc}")
                else:
                    if st.button(f"Use these {len(got)} holdings", key="xw_csv_use"):
                        st.session_state[HOLDINGS_KEY] = got
                        st.rerun()
    kit.caption("Kept for this session only. Nothing is stored.")


def _candidates(preview, funds_for, returns: pd.DataFrame) -> None:
    """Paresh's qualified list, embedded: the eligible exposures that beat cash, best first."""
    ranking = preview.ranking
    passing = ranking[ranking["eligible"].astype(bool) & ranking["hurdle_pass"].astype(bool)]
    passing = passing.sort_values("rank", kind="mergesort")
    eligible = int(ranking["eligible"].astype(bool).sum())
    top_n = int(st.session_state.get("ac_cand_top_n", 10) or 10)
    view = passing.head(top_n)
    frame = pd.DataFrame({
        "Rank": view["rank"].astype(int).to_numpy(),
        "Exposure": view["name"].to_numpy(),
        "Symbol": [funds_for(e)[0] or ("Index fund" if funds_for(e)[2] else "—") for e in view.index],
        "Score": view["score"].astype(float).round(2).to_numpy(),
        "3M Return": [pd.to_numeric(returns.get("return_3M", pd.Series(dtype=float)).get(e), errors="coerce")
                      for e in view.index],
        "6M Return": [pd.to_numeric(returns.get("return_6M", pd.Series(dtype=float)).get(e), errors="coerce")
                      for e in view.index],
        "12M Return": view["return_12m"].astype(float).to_numpy(),
        "Status": view["status"].to_numpy(),
    })
    with st.container(horizontal=True, vertical_alignment="center", key="ac_cand_bar"):
        lead = f"The {len(view)} best-ranked of the" if len(view) < len(passing) else "The"
        kit.caption(f"{lead} {len(passing)} buyable exposures whose 12-month return beats cash's "
                    f"({preview.cash_hurdle_12m:.1%}).")
        st.segmented_control("Show", [5, 10, 20], default=10, required=True, key="ac_cand_top_n",
                             format_func=lambda n: f"Top {n}", label_visibility="collapsed")
        st.download_button("Export CSV", frame.to_csv(index=False).encode(),
                           f"candidates_{preview.as_of:%Y%m%d}.csv", "text/csv",
                           key="dl_ac_cand_csv", icon=":material/download:", disabled=frame.empty)
    if frame.empty:
        st.info("No buyable exposure beats cash today.")
        return
    avg3 = pd.to_numeric(frame["3M Return"], errors="coerce").mean()
    avg12 = pd.to_numeric(frame["12M Return"], errors="coerce").mean()
    kit.readings([
        kit.Reading("Candidates", f"{len(passing)}", f"of {eligible} buyable"),
        kit.Reading("Average 3M return", kit.pct(avg3), "", "up" if avg3 >= 0 else "down"),
        kit.Reading("Average 12M return", kit.pct(avg12), f"cash {preview.cash_hurdle_12m:.1%}",
                    "up" if avg12 >= 0 else "down"),
    ], "Buy candidates today")
    with kit.card("The list", "ac_cand_list", "the strategy's rank at today's close"):
        render_saas_table(frame, max_height=620)


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #
config = strategy_config()
rules = Rules(top_n=int(config.target_holdings_n), buffer_m=int(config.retention_buffer_m))
panel, _ = load_index_panel()
live = load_portfolio()
if live is None or panel.empty:
    kit.page_head("Actions", "")
    st.info("No target portfolio yet: the pipeline has not published the index prices.")
    st.stop()

latest = pd.Timestamp(panel.index.max())
target, previous = live.target, live.previous
decided = pd.Timestamp(target.as_of).normalize() == latest.normalize()
check, fill = next_rebalance(latest, target.as_of, int(config.rebalance_months))
n_sess = sessions_between(latest, check)
timing_note = f" The {_day(check)} close is in: these are its orders." if decided else ""

head = kit.page_head(
    "Actions",
    f"Next rebalance if prices hold. Checked {_day(check)} close, fills {_day(fill)}." + timing_note,
    actions=True,
)
with head:
    source = st.segmented_control("Holdings", SOURCES, default=SOURCES[0], key="xw_source",
                                  label_visibility="collapsed") or SOURCES[0]
st.html(GRID_CSS)

decisions = load_decisions()
returns = (decisions.drop_duplicates("exposure_id").set_index("exposure_id")
           if not decisions.empty and "exposure_id" in decisions else pd.DataFrame())
held_symbol: dict[str, str] = {}

if source == "My holdings":
    _edit_holdings()
    entries = _entries()
    mapped, unknown = map_symbols(entries, vehicle_frame())
    holdings = list(mapped)
    held_symbol = {e: sym for e, (sym, _p) in mapped.items()}
    prior = prior_weights(holdings, rules.top_n)
    since = {}
    for e, (sym, cost) in mapped.items():
        last = _price(sym, sym)
        if cost and last:
            since[e] = last / cost - 1.0
    when = lambda e: ""  # noqa: E731 -- buy dates are not recorded for your holdings
    shown = holdings + unknown
else:
    book = load_model_book()
    # On a month-end close the latest decision is not filled yet: the book still
    # holds the previous one, and these are that decision's orders.
    base = (previous if decided else target)
    prior = dict(base.weights) if base is not None else {}
    holdings = list(base.holdings) if base is not None else []
    unknown = []
    positions = book.positions if book.ok else pd.DataFrame()
    since, opened = {}, {}
    if not positions.empty:
        for _, p in positions.iterrows():
            e = str(p["exposure_id"])
            held_symbol[e] = str(p["Vehicle"]).split(" · ")[0] if p.get("Type") == "ETF" else ""
            since[e] = float(p["P&L %"]) / 100.0 if pd.notna(p["P&L %"]) else float("nan")
            opened[e] = pd.to_datetime(p["Entry Date"], errors="coerce")
    when = lambda e: "" if pd.isna(opened.get(e, pd.NaT)) else f"held since {_day(opened[e])}"  # noqa: E731
    shown = holdings

preview = load_preview(prior)
_fund_cache: dict[str, tuple] = {}


def funds_for(e: str) -> tuple:
    if e not in _fund_cache:
        _fund_cache[e] = _fund(e, fill, held_symbol.get(e) or None)
    return _fund_cache[e]


def _chip(e: str, rank: int, name: str) -> str:
    sym = funds_for(e)[0]
    href = f' href="{kit.tradingview_url(sym)}" target="_blank" rel="noopener"' if sym else ""
    return (f'<a class="t50-chip"{href}><span class="t50-rank">{rank}</span>'
            f"<span>{html.escape(sym or name)}</span></a>")


if not shown and source == "My holdings":
    st.info("Add your ETF holdings above, or upload the holdings CSV from Kite, to see what to do with them.")
elif preview is None:
    st.info("No target portfolio yet: the pipeline has not published the index prices.")
else:
    plan = plan_rebalance(preview, holdings)
    a = assess(preview, shown, plan, rules)
    funds = {e: funds_for(e) for e in list(dict.fromkeys(plan.buys + plan.holds + plan.sells))}
    n_unknown = int((a["status"] == UNKNOWN).sum()) if not a.empty else 0
    n_watch = int(a[a["exposure_id"].isin(plan.holds)]["status"].eq(WATCH).sum()) if not a.empty else 0
    cash_slots = int(round(plan.cash_weight * rules.top_n))
    kit.readings([
        kit.Reading("Sell", f"{len(plan.sells)}", "break a rule at today's close",
                    "down" if plan.sells else ""),
        kit.Reading("Buy", f"{len(plan.buys)}",
                    f"{cash_slots} slot{'s' if cash_slots != 1 else ''} in cash" if cash_slots
                    else "one for each free slot" if plan.buys else "nothing to replace",
                    "up" if plan.buys else ""),
        kit.Reading("Hold", f"{len(plan.holds)}",
                    f"{n_watch} of them close to a rule" if n_watch else "all clear of the rules",
                    "warn" if n_watch else ""),
        kit.Reading("Next rebalance", _day(check, weekday=True),
                    f"{n_sess} session{'s' if n_sess != 1 else ''} away · fills {_day(fill, weekday=True)}"),
    ], "Actions")
    if n_unknown:
        kit.note(f"{n_unknown} of your symbols {'is' if n_unknown == 1 else 'are'} not in the universe.",
                 "No rule can be checked for them; they are listed with the holds.")

    with head, st.popover("Kite basket", icon=":material/download:", type="primary"):
        capital = float(st.number_input(
            "Capital (₹)", min_value=KITE_MIN_CAPITAL, max_value=KITE_MAX_CAPITAL,
            step=100_000, value=int(MODEL_BOOK_CAPITAL), key=KITE_CAPITAL_KEY,
            help=f"₹{MODEL_BOOK_CAPITAL:,.0f} is the model book on Portfolio. "
                 "For your own holdings, enter your account's size.",
        ))
        orders = buy_orders(plan, funds, capital)
        st.download_button(
            "Download basket CSV", orders.to_csv(index=False).encode(),
            f"kite_actions_{latest:%Y%m%d}.csv", "text/csv", type="primary",
            key="dl_actions_basket", icon=":material/download:", disabled=orders.empty,
        )
        index_funds = [e for e in plan.buys if not funds.get(e, NO_FUND)[0]]
        kit.caption(f"Buy orders only, each at its target weight of ₹{capital:,.0f}, in whole ETF units. "
                    "Sells are not in the basket: sell each in full yourself."
                    + (" Index funds are bought at NAV from the fund house, not on Kite." if index_funds else ""))

    with kit.card(f"Sell {len(plan.sells)}", "ac_sell"):
        if plan.sells:
            st.html(sells_html(a, plan.sells, since, funds, when))
            kit.caption("Sell each in full. Not in the Kite basket: the app does not know how many units you hold.")
        else:
            kit.caption("Nothing breaks a rule at today's close.")

    ranking = preview.ranking
    with kit.card(f"Buy {len(plan.buys)}", "ac_buy", f"holdings stay inside the top {rules.buffer_m}"):
        if plan.buys:
            st.html(buys_html(ranking, plan.buys, funds, returns, rules))
            chips = "".join(_chip(e, int(ranking.at[e, "rank"]), str(ranking.at[e, "name"]))
                            for e in plan.next_in_line)
            if chips:
                st.html(f'<div class="ac-next"><span>Next in line, if one moves into the top {rules.top_n}:</span>'
                        f"{chips}</div>")
        elif cash_slots:
            kit.caption(f"No buys: no other top-{rules.top_n} exposure beats cash, so the free slot stays in cash.")
        else:
            kit.caption("No buys: every holding stays inside the rules.")

    holds = a[a["exposure_id"].isin(plan.holds) | (a["status"] == UNKNOWN)] if not a.empty else a
    with kit.card(f"Hold {len(plan.holds)}", "ac_hold", f"{n_watch} to watch · closest to a sale first"):
        if holds.empty:
            kit.caption("Nothing to hold.")
        else:
            st.html(rows_html(holds, since, funds, rules, float(preview.cash_hurdle_12m)))
            kit.caption(f"Rank buffer = places a holding can fall before it leaves the top {rules.buffer_m}. "
                        "12M vs cash = its 12-month return less the liquid fund's.")

if preview is not None:
    with st.expander("Buy candidates · the ranked list", expanded=False):
        _candidates(preview, funds_for, returns)
