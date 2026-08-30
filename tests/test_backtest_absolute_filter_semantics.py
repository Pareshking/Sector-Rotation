import numpy as np
import pandas as pd
import pytest

import src.quantitative.backtest as backtest


def _prices(days: int = 900) -> tuple[pd.DataFrame, pd.Series]:
    index = pd.bdate_range(end=pd.Timestamp("2026-08-28"), periods=days)
    prices = pd.DataFrame(
        {
            "A_negative": np.linspace(200.0, 190.0, days),
            "B_positive": np.linspace(100.0, 120.0, days),
            "C_positive": np.linspace(100.0, 115.0, days),
            "D_positive": np.linspace(100.0, 110.0, days),
            "E_positive": np.linspace(100.0, 105.0, days),
        },
        index=index,
    )
    benchmark = pd.Series(np.linspace(100.0, 90.0, days), index=index, name="nifty50")
    return prices, benchmark


def _controlled_rank(prices: pd.DataFrame, benchmark: pd.Series) -> pd.DataFrame:
    del prices, benchmark
    names = ["A_negative", "B_positive", "C_positive", "D_positive", "E_positive"]
    return pd.DataFrame(
        {
            "momentum_z": np.linspace(5.0, 1.0, len(names)),
            "rank": range(1, len(names) + 1),
        },
        index=names,
    )


@pytest.mark.parametrize(
    ("top_n", "expected_off", "expected_on", "expected_cash"),
    [
        (1, ["A_negative"], ["B_positive"], 0),
        (2, ["A_negative", "B_positive"], ["B_positive", "C_positive"], 0),
        (3, ["A_negative", "B_positive", "C_positive"], ["B_positive", "C_positive", "D_positive"], 0),
        (5, ["A_negative", "B_positive", "C_positive", "D_positive", "E_positive"], ["B_positive", "C_positive", "D_positive", "E_positive"], 1),
    ],
)
def test_absolute_filter_replaces_negative_relative_winner(
    monkeypatch, top_n, expected_off, expected_on, expected_cash
):
    prices, benchmark = _prices()
    monkeypatch.setattr(backtest, "rank_exposures", _controlled_rank)

    off = backtest.run_backtest(prices, benchmark, top_n=top_n, months=12, absolute_filter=False)
    on = backtest.run_backtest(prices, benchmark, top_n=top_n, months=12, absolute_filter=True)

    assert off.ok and on.ok
    assert off.monthly.iloc[0]["holdings"].split(", ") == expected_off
    assert on.monthly.iloc[0]["holdings"].split(", ") == expected_on
    assert on.monthly.iloc[0]["cash_slots"] == expected_cash
    assert on.stats["cash_months"] == float(12 if expected_cash else 0)
