import numpy as np
import pandas as pd

from src.quantitative.relative_strength import mansfield_relative_strength, rs_stage
from src.quantitative.returns import period_return
from src.quantitative.ranking import cross_sectional_zscore, rank_exposures


def test_period_return() -> None:
    series = pd.Series([100.0, 105.0, 110.0])
    assert period_return(series, 1) == 110.0 / 105.0 - 1.0


def test_mansfield_is_zero_for_identical_series() -> None:
    idx = pd.bdate_range("2024-01-01", periods=100)
    series = pd.Series(np.linspace(100, 150, len(idx)), index=idx)
    result = mansfield_relative_strength(series, series, window=10).dropna()
    assert np.allclose(result.to_numpy(), 0.0)


def test_zscore_centered() -> None:
    values = pd.Series([1.0, 2.0, 3.0])
    z = cross_sectional_zscore(values)
    assert abs(z.mean()) < 1e-12
    assert z.iloc[-1] > z.iloc[0]


def test_stage_logic() -> None:
    assert rs_stage(1.1, 0.5) == "Leading"
    assert rs_stage(1.1, -0.5) == "Weakening"
    assert rs_stage(0.9, -0.5) == "Lagging"
    assert rs_stage(0.9, 0.5) == "Improving"


def test_rank_is_unique_even_when_scores_tie() -> None:
    idx = pd.bdate_range("2024-01-01", periods=320)
    benchmark = pd.Series(np.linspace(100, 140, len(idx)), index=idx)
    prices = pd.DataFrame({"Alpha": benchmark, "Beta": benchmark}, index=idx)
    result = rank_exposures(prices, benchmark)
    assert result["rank"].tolist() == [1, 2]
    assert result["rank"].is_unique
