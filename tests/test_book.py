"""The rupee model book: decisions bought and held in funds, valued at NAV."""

import math

import numpy as np
import pandas as pd

from src.portfolio.book import build_model_book, calendar_grid, monthly_returns
from src.portfolio.construct import CASH, Decision, TargetPortfolio
from src.portfolio.vehicles import VehicleChoice

DAYS = pd.bdate_range("2024-01-01", "2024-04-30")


def _target(as_of: str, weights: dict[str, float], actions: dict[str, str]) -> TargetPortfolio:
    decisions = tuple(
        Decision(e, actions.get(e, "BUY"), 0.0, float(weights.get(e, 0.0)), 1, 1.0, f"{actions.get(e, 'BUY')} {e}")
        for e in sorted(set(weights) | set(actions)) if e != CASH
    )
    ranking = pd.DataFrame({"rank": [1, 2, 3]}, index=["a", "b", "c"])
    return TargetPortfolio(pd.Timestamp(as_of), weights, decisions, ranking, eligible_count=3)


def _prices(growth: dict[str, float]) -> pd.DataFrame:
    steps = np.arange(len(DAYS))
    return pd.DataFrame({k: 100.0 * (1 + g) ** steps for k, g in growth.items()}, index=DAYS)


def _vehicles(exposure_id, as_of):
    vehicle = "index_fund" if exposure_id == "c" else "etf"
    return VehicleChoice(exposure_id, exposure_id.upper(), f"{exposure_id.upper()} fund", vehicle,
                         exposure_id.upper() if vehicle == "etf" else None, 1, "test")


def _book(decisions, growth=None, cash_nav=None, cost=25.0):
    growth = growth or {"a": 0.001, "b": -0.0005, "c": 0.0008}
    index = _prices(growth)
    funds = index.rename(columns=str.upper)
    bench = pd.Series(100.0 * 1.0003 ** np.arange(len(DAYS)), index=DAYS)
    return build_model_book(decisions, index, bench, funds, _vehicles, 2_000_000, cost, cash_nav, 0.065,
                            {"a": "Alpha", "b": "Beta", "c": "Gamma"})


def test_the_book_buys_at_the_session_after_the_signal_in_whole_etf_units():
    book = _book([_target("2024-01-31", {"a": 0.5, "b": 0.5}, {})])
    assert book.equity.index[0] == pd.Timestamp("2024-02-01")
    units = book.positions.set_index("Exposure")["Units"]
    assert all(float(u).is_integer() for u in units)
    assert book.cash >= 0
    first = book.rebalances[book.rebalances["Fill Date"] == pd.Timestamp("2024-02-01")]
    assert set(first["Action"]) == {"BUY"} and len(first) == 2


def test_account_value_is_cash_plus_marked_units_every_session():
    book = _book([_target("2024-01-31", {"a": 0.5, "b": 0.5}, {})])
    marked = float(book.positions["Current Value (₹)"].sum())
    assert math.isclose(float(book.equity.iloc[-1]), book.cash + marked, rel_tol=1e-9)


def test_a_sell_closes_a_trade_with_its_reason_and_funds_the_buy():
    decisions = [
        _target("2024-01-31", {"a": 0.5, "b": 0.5}, {}),
        _target("2024-02-29", {"a": 0.5, "c": 0.5}, {"a": "HOLD", "b": "SELL", "c": "BUY"}),
    ]
    book = _book(decisions)
    closed = book.trades[book.trades["Status"] == "Closed"]
    assert list(closed["Exposure"]) == ["Beta"] and closed["Reason for Exit"].iat[0] == "SELL b"
    assert closed["Exit Date"].iat[0] == pd.Timestamp("2024-03-01")
    assert set(book.positions["Exposure"]) == {"Alpha", "Gamma"}
    gamma = book.positions.set_index("Exposure").loc["Gamma"]
    assert gamma["Type"] == "Index fund" and not float(gamma["Units"]).is_integer()
    assert book.cash >= 0


def test_costs_are_charged_on_traded_rupees():
    decisions = [_target("2024-01-31", {"a": 0.5, "b": 0.5}, {})]
    free, costly = _book(decisions, cost=0.0), _book(decisions, cost=100.0)
    assert float(costly.equity.iloc[0]) < float(free.equity.iloc[0])


def test_uninvested_cash_earns_the_liquid_fund():
    nav = pd.Series(1000.0 * 1.0002 ** np.arange(len(DAYS)), index=DAYS)
    book = _book([_target("2024-01-31", {"a": 0.5, CASH: 0.5}, {})], cash_nav=nav)
    flat = _book([_target("2024-01-31", {"a": 0.5, CASH: 0.5}, {})],
                 cash_nav=pd.Series(1000.0, index=DAYS))
    assert book.cash > flat.cash


def test_a_decision_without_a_fill_session_is_pending_not_executed():
    decisions = [_target("2024-01-31", {"a": 1.0}, {}), _target("2024-04-30", {"b": 1.0}, {"a": "SELL", "b": "BUY"})]
    book = _book(decisions)
    assert book.pending is not None and pd.Timestamp(book.pending.as_of) == pd.Timestamp("2024-04-30")
    assert set(book.positions["Exposure"]) == {"Alpha"}


def test_monthly_returns_chain_to_the_total_and_mark_the_running_month():
    equity = pd.Series([100.0, 110.0, 121.0, 127.05], index=pd.to_datetime(["2024-01-01", "2024-01-31",
                                                                               "2024-02-29", "2024-03-15"]))
    monthly = monthly_returns(equity, equity * 0 + 100.0)
    assert np.isclose(np.prod(1 + monthly["Strategy"]) - 1, 127.05 / 100.0 - 1)
    assert list(monthly["Origin"]) == ["Backfilled", "Backfilled", "MTD"]
    grid = calendar_grid(monthly)
    assert np.isclose(grid.loc[2024, "Feb"], 0.10) and np.isclose(grid.loc[2024, "Year"], 0.2705)
