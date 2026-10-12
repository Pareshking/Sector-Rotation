"""A rupee model book: the strategy's decisions, bought and held in real funds.

The backtest (``src/quantitative/backtest.py``) accounts in index returns and
weights. This module replays the same decision chain as an account with a
starting capital: at each decision's fill (the session after the signal, at the
close) it sells what the decision dropped, buys what it added and resizes what
it kept back to target weight, in whole ETF units or fractional index-fund
units, through the vehicle ``choose_vehicle`` picks. Each fund is valued at its
published NAV; uninvested cash earns the liquid fund's NAV return.

Nothing here decides anything. Membership and weights are the decisions';
this only turns them into units, rupees, trades and an equity curve.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from src.portfolio.calendar import fill_date
from src.portfolio.construct import CASH, TargetPortfolio
from src.portfolio.vehicles import VehicleChoice

# The model book starts with ₹20 lakh, as the Paresh app's does (owner, 12 Oct 2026).
MODEL_BOOK_CAPITAL = 2_000_000
FFILL_SESSIONS = 5
BACKFILLED = "Backfilled"


@dataclass
class _Position:
    exposure_id: str
    key: str
    label: str
    vehicle: str
    units: float
    cost: float          # rupees paid for the units still held
    entry_date: pd.Timestamp
    entry_signal: pd.Timestamp
    priced_by: str       # "fund NAV" or "index (no fund NAV)"


@dataclass(frozen=True)
class ModelBook:
    capital: float
    as_of: pd.Timestamp | None
    last_fill: pd.Timestamp | None
    equity: pd.Series                      # account value per session, from the first fill
    benchmark: pd.Series                   # the benchmark scaled to the same capital
    cash: float
    positions: pd.DataFrame                # the current book
    trades: pd.DataFrame                   # one row per position opened, closed or still open
    rebalances: pd.DataFrame               # one row per exposure per rebalance
    monthly: pd.DataFrame                  # strategy, benchmark and alpha per month
    pending: TargetPortfolio | None = None  # a decision whose fill session has not happened yet
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.equity.empty


def _round_units(value: float, vehicle: str) -> float:
    """ETFs trade in whole units; index funds allot units to three decimals."""
    if value <= 0 or not math.isfinite(value):
        return 0.0
    return float(math.floor(value)) if vehicle == "etf" else math.floor(value * 1000) / 1000


def _cash_factor(cash_nav: pd.Series | None, index: pd.DatetimeIndex, rate: float) -> pd.Series:
    """Daily growth factor of a rupee in cash: the liquid fund's NAV, else the assumed rate."""
    fallback = (1.0 + rate) ** (1.0 / 252.0)
    if cash_nav is None or cash_nav.dropna().empty:
        return pd.Series(fallback, index=index)
    nav = pd.to_numeric(cash_nav, errors="coerce").dropna().sort_index()
    nav = nav.reindex(nav.index.union(index)).ffill().reindex(index)
    growth = (nav / nav.shift(1)).fillna(fallback)
    return growth.where(np.isfinite(growth) & (growth > 0), fallback)


def build_model_book(
    decisions: Sequence[TargetPortfolio],
    index_prices: pd.DataFrame,
    benchmark: pd.Series,
    fund_prices: pd.DataFrame,
    vehicle_for: Callable[[str, pd.Timestamp], VehicleChoice | None],
    capital: float,
    cost_bps_per_side: float = 25.0,
    cash_nav: pd.Series | None = None,
    risk_free_rate: float = 0.065,
    names: Mapping[str, str] | None = None,
) -> ModelBook:
    """Replay ``decisions`` as a rupee account starting with ``capital``.

    ``index_prices`` supplies the session calendar (and a fallback price for an
    exposure whose fund has no NAV on a day); ``fund_prices`` holds each fund's
    NAV keyed by vehicle key (NSE symbol, else fund name).
    """
    names = dict(names or {})
    bps = float(cost_bps_per_side) / 1e4
    sessions = pd.DatetimeIndex(index_prices.index).sort_values()
    if fund_prices is not None and not fund_prices.empty:
        # Fund NAVs publish a session or two after the index closes. Marking the
        # book past its last NAV would carry Friday's value into Monday and show
        # a day P&L of zero, so the book ends where its funds were last priced.
        sessions = sessions[sessions <= pd.Timestamp(fund_prices.dropna(how="all").index.max())]
    empty = ModelBook(float(capital), None, None, pd.Series(dtype=float), pd.Series(dtype=float), float(capital),
                      pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    live = [d for d in decisions if d.eligible_count > 0]
    if not live or sessions.empty:
        return empty

    funds = fund_prices.sort_index().reindex(fund_prices.index.union(sessions)).ffill(limit=FFILL_SESSIONS).reindex(sessions) \
        if fund_prices is not None and not fund_prices.empty else pd.DataFrame(index=sessions)
    marks = index_prices.sort_index().ffill(limit=FFILL_SESSIONS)

    fills: list[tuple[pd.Timestamp, TargetPortfolio]] = []
    pending: TargetPortfolio | None = None
    for target in live:
        when = fill_date(sessions, pd.Timestamp(target.as_of))
        if when is None:
            pending = target
        else:
            fills.append((when, target))
    if not fills:
        return ModelBook(**{**empty.__dict__, "pending": pending})

    first = fills[0][0]
    days = sessions[sessions >= first]
    growth = _cash_factor(cash_nav, days, risk_free_rate)
    by_day = {when: target for when, target in fills}

    cash = float(capital)
    held: dict[str, _Position] = {}
    trades: list[dict[str, object]] = []
    rebalances: list[dict[str, object]] = []
    values: list[float] = []
    notes: list[str] = []

    def price(position_key: str, exposure_id: str, day: pd.Timestamp) -> tuple[float, str]:
        if position_key in funds.columns:
            value = funds.at[day, position_key]
            if pd.notna(value) and value > 0:
                return float(value), "fund NAV"
        value = marks.at[day, exposure_id] if exposure_id in marks.columns else np.nan
        return (float(value), "index (no fund NAV)") if pd.notna(value) and value > 0 else (np.nan, "")

    for i, day in enumerate(days):
        if i:
            cash *= float(growth.iloc[i])
        target = by_day.get(day)
        if target is not None:
            book_value = cash + sum(
                p.units * (price(p.key, e, day)[0] if math.isfinite(price(p.key, e, day)[0]) else 0.0)
                for e, p in held.items()
            )
            decisions_by_id = {d.exposure_id: d for d in target.decisions}
            period = pd.Timestamp(target.as_of).strftime("%Y-%m")
            # Sells first, so their proceeds fund the buys.
            for exposure_id in [e for e in held if float(target.weights.get(e, 0.0)) <= 0]:
                position = held.pop(exposure_id)
                px, _ = price(position.key, exposure_id, day)
                proceeds = position.units * px if math.isfinite(px) else 0.0
                cash += proceeds - bps * proceeds
                decision = decisions_by_id.get(exposure_id)
                ret = proceeds / position.cost - 1.0 if position.cost > 0 else np.nan
                trades.append(_trade_row(position, names, "Closed", day, px, ret,
                                         decision.reason if decision else "Left the target."))
                rebalances.append(_rebalance_row(period, day, "SELL", position, px, position.units, 0.0, ret,
                                                 decision.reason if decision else "", names))
            # Resize what stays and buy what is new, each to its target weight.
            for exposure_id in target.holdings:
                weight = float(target.weights.get(exposure_id, 0.0))
                decision = decisions_by_id.get(exposure_id)
                position = held.get(exposure_id)
                if position is None:
                    choice = vehicle_for(exposure_id, pd.Timestamp(target.as_of))
                    key = choice.key if choice is not None else exposure_id
                    vehicle = choice.vehicle if choice is not None else "index_fund"
                    label = choice.label if choice is not None else f"{names.get(exposure_id, exposure_id)} index"
                    position = _Position(exposure_id, key, label, vehicle, 0.0, 0.0, day, pd.Timestamp(target.as_of), "")
                px, priced_by = price(position.key, exposure_id, day)
                if not math.isfinite(px):
                    notes.append(f"{period}: no price for {names.get(exposure_id, exposure_id)} at the "
                                 f"{day:%d %b %Y} fill; its slot stayed in cash.")
                    continue
                position.priced_by = priced_by
                units = _round_units(book_value * weight / px, position.vehicle)
                delta = units - position.units
                traded = abs(delta) * px
                if delta > 0:
                    cost_now = delta * px
                    if cost_now + bps * cost_now > cash:  # never borrow: buy what the cash allows
                        delta = _round_units(cash / (px * (1.0 + bps)), position.vehicle)
                        units, cost_now, traded = position.units + delta, delta * px, delta * px
                    cash -= cost_now + bps * cost_now
                    position.cost += cost_now
                elif delta < 0:
                    proceeds = -delta * px
                    cash += proceeds - bps * proceeds
                    position.cost *= units / position.units if position.units else 0.0
                new = exposure_id not in held
                position.units = units
                held[exposure_id] = position
                action = decision.action if decision else ("BUY" if new else "HOLD")
                mark = units * px
                ret = mark / position.cost - 1.0 if position.cost > 0 and not new else np.nan
                rebalances.append(_rebalance_row(period, day, action, position, px, delta, weight, ret,
                                                 decision.reason if decision else "", names, traded))
        values.append(cash + sum(
            p.units * (price(p.key, e, day)[0] if math.isfinite(price(p.key, e, day)[0]) else 0.0)
            for e, p in held.items()
        ))

    equity = pd.Series(values, index=days, dtype=float)
    as_of = pd.Timestamp(days[-1])
    bench = pd.to_numeric(benchmark, errors="coerce").dropna().sort_index()
    bench = bench.reindex(bench.index.union(days)).ffill().reindex(days)
    benchmark_curve = (float(capital) * bench / float(bench.iloc[0])) if bench.notna().any() and bench.iloc[0] > 0 \
        else pd.Series(dtype=float)

    positions = _positions(held, funds, marks, as_of, days, equity, names, price)
    for position in held.values():
        px, _ = price(position.key, position.exposure_id, as_of)
        ret = position.units * px / position.cost - 1.0 if position.cost > 0 and math.isfinite(px) else np.nan
        trades.append(_trade_row(position, names, "Open", None, px, ret, ""))
    trade_frame = pd.DataFrame(trades)
    if not trade_frame.empty:
        trade_frame = trade_frame.sort_values(["Entry Date", "Exposure"], ascending=[False, True]).reset_index(drop=True)
    return ModelBook(
        capital=float(capital),
        as_of=as_of,
        last_fill=fills[-1][0],
        equity=equity,
        benchmark=benchmark_curve,
        cash=float(cash),
        positions=positions,
        trades=trade_frame,
        rebalances=pd.DataFrame(rebalances).iloc[::-1].reset_index(drop=True) if rebalances else pd.DataFrame(),
        monthly=monthly_returns(equity, benchmark_curve),
        pending=pending,
        notes=tuple(notes),
    )


def _trade_row(position: _Position, names, status, exit_day, exit_px, ret, reason) -> dict[str, object]:
    entry_px = position.cost / position.units if position.units else np.nan
    end = exit_day if exit_day is not None else None
    return {
        "Exposure": names.get(position.exposure_id, position.exposure_id),
        "Vehicle": position.label,
        "Status": status,
        "Entry Date": position.entry_date,
        "Entry Price": entry_px,
        "Exit Date": end,
        "Exit Price": exit_px if status == "Closed" else np.nan,
        "Return %": ret * 100.0 if pd.notna(ret) else np.nan,
        "Holding (Days)": int(((end or position.entry_date) - position.entry_date).days) if end is not None else np.nan,
        "Reason for Exit": reason,
        "exposure_id": position.exposure_id,
    }


def _rebalance_row(period, day, action, position, px, units, weight, ret, reason, names, traded=None):
    return {
        "Period": period,
        "Fill Date": day,
        "Action": action,
        "Exposure": names.get(position.exposure_id, position.exposure_id),
        "Vehicle": position.label,
        "Price": px,
        "Units traded": units,
        "Traded (₹)": traded if traded is not None else abs(units) * px,
        "Weight %": weight * 100.0,
        "Return %": ret * 100.0 if pd.notna(ret) else np.nan,
        "Reason / Signal": reason,
    }


def _positions(held, funds, marks, as_of, days, equity, names, price) -> pd.DataFrame:
    if not held:
        return pd.DataFrame()
    total = float(equity.iloc[-1])
    previous_day = days[-2] if len(days) > 1 else None
    rows = []
    for exposure_id, p in held.items():
        px, priced_by = price(p.key, exposure_id, as_of)
        prev_px = price(p.key, exposure_id, previous_day)[0] if previous_day is not None else np.nan
        value = p.units * px if math.isfinite(px) else np.nan
        prev_value = p.units * prev_px if math.isfinite(prev_px) else np.nan
        rows.append({
            "exposure_id": exposure_id,
            "key": p.key,
            "Exposure": names.get(exposure_id, exposure_id),
            "Vehicle": p.label,
            "Type": "ETF" if p.vehicle == "etf" else "Index fund",
            "Current Price": px,
            "P&L %": (value / p.cost - 1.0) * 100.0 if p.cost > 0 and pd.notna(value) else np.nan,
            "P&L (₹)": value - p.cost if pd.notna(value) else np.nan,
            "Weight %": value / total * 100.0 if total > 0 and pd.notna(value) else np.nan,
            "Day P&L (₹)": value - prev_value if pd.notna(prev_value) and pd.notna(value) else np.nan,
            "Day P&L %": (value / prev_value - 1.0) * 100.0 if pd.notna(prev_value) and prev_value > 0 else np.nan,
            "Current Value (₹)": value,
            "Units": p.units,
            "Entry Date": p.entry_date,
            "Avg Cost": p.cost / p.units if p.units else np.nan,
            "Invested Value (₹)": p.cost,
            "Holding Days": int((as_of - p.entry_date).days),
            "Priced by": priced_by,
        })
    return pd.DataFrame(rows).sort_values(["P&L %", "Exposure"], ascending=[False, True], na_position="last") \
        .reset_index(drop=True)


def monthly_returns(equity: pd.Series, benchmark: pd.Series) -> pd.DataFrame:
    """One row per calendar month: strategy, benchmark, alpha; the running month marked MTD."""
    if equity is None or equity.empty:
        return pd.DataFrame(columns=["Period", "Strategy", "Benchmark", "Alpha", "Origin"])
    frame = pd.DataFrame({"strategy": equity, "benchmark": benchmark.reindex(equity.index)})
    month_end = frame.groupby(frame.index.to_period("M")).last()
    start = frame.iloc[[0]].copy()
    start.index = [month_end.index[0] - 1]
    chained = pd.concat([start, month_end])
    returns = chained / chained.shift(1) - 1.0
    returns = returns.iloc[1:]
    last_session = equity.index[-1]
    complete = (last_session + pd.offsets.BMonthEnd(0)).normalize() == last_session.normalize()
    origin = [BACKFILLED] * len(returns)
    if not complete:
        origin[-1] = "MTD"
    return pd.DataFrame({
        "Period": [str(p) for p in returns.index],
        "Strategy": returns["strategy"].to_numpy(),
        "Benchmark": returns["benchmark"].to_numpy(),
        "Alpha": (returns["strategy"] - returns["benchmark"]).to_numpy(),
        "Origin": origin,
    })


def calendar_grid(monthly: pd.DataFrame, column: str = "Strategy") -> pd.DataFrame:
    """Years down, months across, plus the compounded year, for one return column."""
    if monthly is None or monthly.empty:
        return pd.DataFrame()
    periods = pd.PeriodIndex(monthly["Period"], freq="M")
    frame = pd.DataFrame({"year": periods.year, "month": periods.strftime("%b"), "value": monthly[column].to_numpy()})
    order = [pd.Period(f"2000-{m:02d}", freq="M").strftime("%b") for m in range(1, 13)]
    grid = frame.pivot(index="year", columns="month", values="value").reindex(columns=order)
    grid["Year"] = frame.groupby("year")["value"].apply(lambda s: float(np.prod(1.0 + s.dropna()) - 1.0))
    grid.index.name = None
    return grid.sort_index(ascending=False)


__all__ = ["BACKFILLED", "MODEL_BOOK_CAPITAL", "ModelBook", "build_model_book", "calendar_grid", "monthly_returns", "CASH"]
