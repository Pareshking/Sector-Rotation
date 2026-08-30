import numpy as np
import pandas as pd

from src.quantitative.backtest import rebalance_dates, run_backtest


def _panel(days: int = 900, columns: int = 6) -> tuple[pd.DataFrame, pd.Series]:
    index = pd.bdate_range(end=pd.Timestamp("2026-08-28"), periods=days)
    rng = np.random.default_rng(7)
    frame = pd.DataFrame(
        {
            f"exp{i}": 100 * np.exp(np.cumsum(rng.normal(0.0002 + i * 0.00012, 0.009, days)))
            for i in range(columns)
        },
        index=index,
    )
    benchmark = pd.Series(
        100 * np.exp(np.cumsum(rng.normal(0.00025, 0.007, days))), index=index, name="nifty50"
    )
    return frame, benchmark


def test_rebalance_dates_are_month_ends() -> None:
    index = pd.bdate_range("2025-01-01", "2026-08-28")
    dates = rebalance_dates(index, months=12)
    assert len(dates) == 13
    assert all(a < b for a, b in zip(dates, dates[1:]))
    months = {(d.year, d.month) for d in dates}
    assert len(months) == len(dates)


def test_window_shorter_than_a_year_is_rejected() -> None:
    prices, benchmark = _panel()
    result = run_backtest(prices, benchmark, top_n=2, months=6)
    assert not result.ok
    assert "at least 12 months" in result.error


def test_backtest_holds_at_most_top_n() -> None:
    prices, benchmark = _panel()
    result = run_backtest(prices, benchmark, top_n=2, months=12, absolute_filter=False)
    assert result.ok
    assert len(result.monthly) == 12
    assert result.monthly["n_held"].max() <= 2
    assert result.stats["months"] == 12


def test_returns_are_measured_after_the_decision_date() -> None:
    """The month's return must be earned strictly after the rebalance close."""
    prices, benchmark = _panel()
    result = run_backtest(prices, benchmark, top_n=1, months=12, absolute_filter=False)
    row = result.monthly.iloc[0]
    held = row["holdings"]
    expected = (
        prices.loc[row["period_end"], held] / prices.loc[row["rebalance"], held] - 1.0
    )
    assert abs(row["strategy_return"] - expected) < 1e-12


def test_absolute_filter_can_force_cash() -> None:
    index = pd.bdate_range(end=pd.Timestamp("2026-08-28"), periods=900)
    falling = pd.DataFrame(
        {f"exp{i}": np.linspace(300, 100, len(index)) - i for i in range(3)}, index=index
    )
    benchmark = pd.Series(np.linspace(300, 100, len(index)), index=index)
    result = run_backtest(falling, benchmark, top_n=2, months=12, absolute_filter=True)
    assert result.ok
    assert (result.monthly["cash_slots"] > 0).all()
    assert result.monthly["strategy_return"].eq(0.0).all()


def test_empty_panel_reports_an_error() -> None:
    result = run_backtest(pd.DataFrame(), pd.Series(dtype=float), months=12)
    assert not result.ok
    assert result.error
