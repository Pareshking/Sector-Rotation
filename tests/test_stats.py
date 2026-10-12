"""Deflated Sharpe ratio (Bailey & López de Prado 2014)."""

import math
from statistics import NormalDist

import numpy as np
import pandas as pd
import pytest

from src.quantitative.stats import (
    EULER_GAMMA,
    deflated_sharpe,
    expected_max_sharpe,
    probabilistic_sharpe,
)

Z = NormalDist()


def test_one_trial_expects_no_luck():
    assert expected_max_sharpe(1, 0.04) == 0.0


def test_the_expected_maximum_matches_the_formula_and_grows_with_trials():
    v, n = 1 / 46, 768
    expected = math.sqrt(v) * ((1 - EULER_GAMMA) * Z.inv_cdf(1 - 1 / n) + EULER_GAMMA * Z.inv_cdf(1 - 1 / (n * math.e)))
    assert expected_max_sharpe(n, v) == pytest.approx(expected)
    assert expected_max_sharpe(10, v) < expected_max_sharpe(100, v) < expected_max_sharpe(10_000, v)


def test_a_sharpe_equal_to_its_benchmark_is_a_coin_toss():
    assert probabilistic_sharpe(0.3, 0.3, 60, 0.0, 3.0) == pytest.approx(0.5)


def test_the_probabilistic_sharpe_matches_the_formula():
    sr, t, skew, kurt = 0.25, 48, -0.4, 4.5
    z = sr * math.sqrt(t - 1) / math.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr**2)
    assert probabilistic_sharpe(sr, 0.0, t, skew, kurt) == pytest.approx(Z.cdf(z))


def test_deflation_only_ever_lowers_the_probability():
    rng = np.random.default_rng(1)
    returns = pd.Series(rng.normal(0.01, 0.04, 60))
    one = deflated_sharpe(returns, 1)
    many = deflated_sharpe(returns, 768)
    assert one.deflated == pytest.approx(one.probabilistic)
    assert many.deflated < many.probabilistic
    assert many.benchmark_sharpe > 0


def test_zero_edge_noise_is_not_evidence_after_many_trials():
    rng = np.random.default_rng(2)
    dsr = deflated_sharpe(pd.Series(rng.normal(0.0, 0.05, 48)), 768)
    assert dsr.deflated < 0.05


def test_a_large_consistent_edge_survives_deflation():
    rng = np.random.default_rng(3)
    dsr = deflated_sharpe(pd.Series(rng.normal(0.03, 0.02, 120)), 768)
    assert dsr.deflated > 0.99


def test_the_inputs_are_measured_from_the_returns():
    rng = np.random.default_rng(4)
    returns = pd.Series(rng.normal(0.01, 0.05, 50))
    dsr = deflated_sharpe(returns, 10)
    assert dsr.observations == 50 and dsr.n_trials == 10
    assert dsr.sharpe == pytest.approx(returns.mean() / returns.std(ddof=1))
    assert dsr.kurtosis == pytest.approx(returns.kurt() + 3)


def test_too_little_data_gives_no_answer():
    assert deflated_sharpe(pd.Series([0.01, 0.02]), 10) is None
    assert deflated_sharpe(pd.Series([0.01] * 20), 10) is None  # no variance
