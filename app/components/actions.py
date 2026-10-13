"""What the strategy would do at the next rebalance, and how close each holding is to a sale.

The Paresh app's ``src/engine/exit_watch.py`` and ``src/engine/actions.py``,
on this strategy's rules (``src/config/strategy.json``):

1. a holding is kept while it ranks inside the buffer (rank <= M);
2. and while its 12-month return beats the liquid fund's (the cash hurdle);
3. vacant slots are filled from ranks <= N that clear the hurdle, else left in cash.

Nothing here decides. The plan is read off a ``TargetPortfolio`` that the
strategy's own ``construct_target_portfolio`` produced on today's closes, so a
preview struck at a month-end close is that month's decision. This module only
says, per holding, how much room is left on each rule, and sizes the buys.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.portfolio.construct import CASH, SELL as SELL_ACTION

# A holding is flagged "watch" inside these margins.
WATCH_RANK_PLACES = 1         # within 1 place of the buffer (rank M-1 or M)
WATCH_HURDLE_CUSHION = 0.05   # 12M return within 5 points of cash's

# A full cushion bar: the whole buffer, or 25 points of 12M return over cash.
HURDLE_SCALE = 0.25

SELL, WATCH, CLEAR, UNKNOWN = "sell", "watch", "clear", "unknown"
STATUS_LABEL = {
    SELL: "Sold if unchanged",
    WATCH: "Watch",
    CLEAR: "Clear",
    UNKNOWN: "Not ranked",
}


@dataclass(frozen=True)
class Rules:
    top_n: int = 2
    buffer_m: int = 4


@dataclass
class Plan:
    sells: list[str]
    buys: list[str]
    holds: list[str]
    next_in_line: list[str]
    weights: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    cash_weight: float = 0.0


def prior_weights(holdings: list[str], top_n: int) -> dict[str, float]:
    """A book of ``holdings`` at one slot each (1/N), the rest in cash; empty means all cash."""
    held = list(dict.fromkeys(str(e) for e in holdings))
    if not held:
        return {CASH: 1.0}
    weights = {e: 1.0 / top_n for e in held}
    cash = 1.0 - len(held) / top_n
    if cash > 1e-12:
        weights[CASH] = cash
    return weights


def plan_rebalance(preview, holdings: list[str], *, spare: int = 4) -> Plan:
    """Sells, buys and holds of ``preview`` (a TargetPortfolio built with ``holdings`` as its prior).

    ``holdings`` not in the ranking cannot be judged and are left out of the
    plan (the page lists them separately).
    """
    ranking = preview.ranking
    weights = {k: float(v) for k, v in preview.weights.items() if k != CASH and float(v) > 1e-12}
    known = [e for e in dict.fromkeys(holdings) if e in ranking.index]
    sold = {d.exposure_id for d in preview.decisions if d.action == SELL_ACTION}
    sells = [e for e in known if e in sold or e not in weights]
    holds = [e for e in known if e in weights]
    rank = pd.to_numeric(ranking["rank"], errors="coerce")
    buys = sorted((e for e in weights if e not in known), key=lambda e: (_num(rank.get(e)), e))
    passing = ranking["hurdle_pass"].astype(bool) if "hurdle_pass" in ranking else pd.Series(True, index=ranking.index)
    order = rank[ranking["eligible"].astype(bool) & passing].dropna().sort_values(kind="mergesort")
    # A holding being sold is not "next in line" for its own slot.
    nxt = [e for e in order.index if e not in weights and e not in sells][:spare]
    return Plan(sells=sells, buys=buys, holds=holds, next_in_line=nxt,
                weights=pd.Series({e: weights[e] for e in buys + holds}, dtype=float),
                cash_weight=float(preview.weights.get(CASH, 0.0)))


def _num(value, default: float = 1e9) -> float:
    out = pd.to_numeric(value, errors="coerce")
    return default if pd.isna(out) else float(out)


def assess(preview, holdings: list[str], plan: Plan, rules: Rules = Rules()) -> pd.DataFrame:
    """One row per holding with its room on each rule and a status.

    Rank room = M - rank (places it can fall before it leaves the buffer);
    hurdle cushion = 12M return - cash's 12M return. A negative value means the
    rule is already broken. A holding the plan sells is "sell" whatever the
    reason; one not in the ranking is "unknown".
    """
    ranking, hurdle = preview.ranking, float(preview.cash_hurdle_12m)
    m = rules.buffer_m
    rows = []
    for e in dict.fromkeys(holdings):
        if e not in ranking.index:
            rows.append({"exposure_id": e, "status": UNKNOWN, "why": "not in the ranked universe"})
            continue
        r = ranking.loc[e]
        rank = pd.to_numeric(r.get("rank"), errors="coerce")
        ret = pd.to_numeric(r.get("return_12m"), errors="coerce")
        valid, eligible = bool(r.get("valid", False)), bool(r.get("eligible", False))
        room = np.nan if pd.isna(rank) else m - int(rank)
        cushion = np.nan if pd.isna(ret) else float(ret) - hurdle
        rank_ok = pd.notna(room) and room >= 0
        hurdle_ok = pd.notna(cushion) and cushion > 0

        broken, close = [], []
        if not valid:
            broken.append("no 12-month history")
        elif not eligible:
            broken.append("no buyable fund")
        else:
            if not rank_ok:
                broken.append(f"ranks #{int(rank)}, past the top {m}")
            if not hurdle_ok:
                broken.append(f"12M {_signed(ret)} is below cash {hurdle:.1%}")
        if e in plan.sells:
            status, why = SELL, "; ".join(broken) or f"more holdings than the {rules.top_n} slots"
        else:
            if rank_ok and room <= WATCH_RANK_PLACES:
                close.append(f"#{int(rank)} · {int(room)} places from the buffer")
            if hurdle_ok and cushion < WATCH_HURDLE_CUSHION:
                close.append(f"12M only {cushion * 100:.1f} pts above cash")
            status, why = (WATCH, "; ".join(close)) if close else (CLEAR, "")
        rows.append({
            "exposure_id": e, "name": r.get("name"), "rank": rank, "rank_room": room, "rank_ok": rank_ok,
            "return_12m": ret, "hurdle_cushion": cushion, "hurdle_ok": hurdle_ok,
            "status": status, "why": why,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    order = {SELL: 0, WATCH: 1, CLEAR: 2, UNKNOWN: 3}
    tight = out.apply(_tightness, axis=1, rules=rules)
    return (out.assign(_o=out["status"].map(order), _t=tight)
               .sort_values(["_o", "_t"], kind="mergesort").drop(columns=["_o", "_t"]).reset_index(drop=True))


def _tightness(row, rules: Rules) -> float:
    """The smallest room left on either rule, on one scale, for sorting."""
    vals = [row.get("hurdle_cushion")]
    room = row.get("rank_room")
    if room is not None and pd.notna(room):
        vals.append(float(room) / rules.buffer_m * HURDLE_SCALE)
    vals = [float(v) for v in vals if v is not None and pd.notna(v)]
    return min(vals) if vals else 9.0


def _signed(x) -> str:
    v = pd.to_numeric(x, errors="coerce")
    return "—" if pd.isna(v) else f"{'+' if v >= 0 else '−'}{abs(float(v)) * 100:.1f}%"


def parse_holdings(text: str) -> list[tuple[str, float | None]]:
    """Symbols with an optional buy price: "METAL 11.3, MODEFENCE@105, BANKBEES"."""
    out: list[tuple[str, float | None]] = []
    seen = set()
    for part in re.split(r"[,;\n]+", str(text or "")):
        m = re.match(r"\s*([A-Za-z0-9&._-]{1,20})\s*(?:[@:\s]\s*₹?\s*([0-9]+(?:\.[0-9]+)?))?\s*$", part)
        if not m:
            continue
        sym = m.group(1).upper()
        if sym in seen:
            continue
        seen.add(sym)
        out.append((sym, float(m.group(2)) if m.group(2) else None))
    return out[:200]


def holdings_from_kite_csv(frame: pd.DataFrame) -> list[tuple[str, float | None]]:
    """Kite Console's holdings export: Instrument, Qty., Avg. cost, ..."""
    cols = {c.strip().lower().rstrip("."): c for c in frame.columns}
    sym_col = cols.get("instrument") or cols.get("symbol") or cols.get("tradingsymbol")
    if sym_col is None:
        raise ValueError("no Instrument or Symbol column")
    cost_col = cols.get("avg. cost") or cols.get("avg cost") or cols.get("average price")
    out = []
    for _, r in frame.iterrows():
        sym = str(r[sym_col]).strip().upper().split("-")[0]
        if not sym or sym == "NAN":
            continue
        cost = pd.to_numeric(r[cost_col], errors="coerce") if cost_col else np.nan
        out.append((sym, None if pd.isna(cost) else float(cost)))
    return out


def to_text(entries: list[tuple[str, float | None]]) -> str:
    return ", ".join(s if p is None else f"{s} {p:g}" for s, p in entries)


def map_symbols(entries: list[tuple[str, float | None]], vehicles: pd.DataFrame
                ) -> tuple[dict[str, tuple[str, float | None]], list[str]]:
    """NSE symbol -> exposure through the registry's vehicles.

    Returns {exposure_id: (symbol, buy price)} (the first fund typed for an
    exposure stands for it) and the symbols no exposure is bought through.
    """
    lookup: dict[str, str] = {}
    if vehicles is not None and not vehicles.empty and "symbol" in vehicles:
        for sym, eid in zip(vehicles["symbol"], vehicles["exposure_id"]):
            if isinstance(sym, str) and sym:
                lookup.setdefault(sym.upper(), str(eid))
    mapped: dict[str, tuple[str, float | None]] = {}
    unknown: list[str] = []
    for sym, price in entries:
        eid = lookup.get(str(sym).upper())
        if eid is None:
            unknown.append(sym)
        else:
            mapped.setdefault(eid, (sym, price))
    return mapped, unknown


def buy_orders(plan: Plan, funds: dict[str, tuple], capital: float) -> pd.DataFrame:
    """Zerodha Kite basket rows for the buys, sized at their target weight in whole ETF units.

    ``funds`` is exposure -> (NSE symbol of the chosen fund, its last price, ...).
    Only the buys: the app does not know how many units of a holding are
    owned, so a sell cannot be sized. An index fund has no NSE symbol and is
    left out (it is bought at NAV through the fund house, not on Kite).
    """
    rows = []
    for e in plan.buys:
        sym, p = tuple(funds.get(e, (None, None)))[:2]
        w =float(plan.weights.get(e, 0.0))
        if not sym or p is None or pd.isna(p) or p <= 0 or w <= 0:
            continue
        qty = int(capital * w // p)
        if qty > 0:
            rows.append({"Instrument": sym, "Exchange": "NSE", "Order Type": "MARKET",
                         "Action": "BUY", "Quantity": qty, "Price": 0,
                         "ProductType": "CNC", "TriggerPrice": 0})
    return pd.DataFrame(rows)


def next_rebalance(latest: pd.Timestamp, decided: pd.Timestamp | None, hold_months: int = 1
                   ) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The check (month-end close) and the fill (the next weekday).

    When the latest close is itself a decision date (``decided``), that close
    is the check and its fill is the next session; otherwise the next month end.
    Exchange holidays are not known here, so these are weekdays.
    """
    from src.portfolio.calendar import next_rebalance_date

    latest = pd.Timestamp(latest).normalize()
    if decided is not None and pd.Timestamp(decided).normalize() == latest:
        check = latest
    else:
        check = next_rebalance_date(latest, hold_months)
    return check, (check + pd.offsets.BDay(1)).normalize()


def sessions_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return max(0, len(pd.bdate_range(pd.Timestamp(a).normalize() + pd.Timedelta(days=1), pd.Timestamp(b).normalize())))
