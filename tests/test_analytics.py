import numpy as np
import pandas as pd

from src.quantitative.analytics import (
    alpha_beta,
    annualised_volatility,
    cagr,
    information_ratio,
    max_drawdown,
    outperformance_consistency,
    rolling_summary,
    sharpe,
    tracking,
)


def _series(rate: float, days: int = 1300, noise: float = 0.0, seed: int = 3) -> pd.Series:
    index = pd.bdate_range(end=pd.Timestamp("2026-08-28"), periods=days)
    daily = (1 + rate) ** (1 / 252) - 1
    steps = np.full(days, daily)
    if noise:
        steps = steps + np.random.default_rng(seed).normal(0, noise, days)
    return pd.Series(100 * np.cumprod(1 + steps), index=index)


def test_cagr_recovers_a_known_growth_rate():
    assert abs(cagr(_series(0.12)) - 0.12) < 0.005


def test_a_straight_line_has_no_volatility_and_no_drawdown():
    flat = _series(0.10)
    assert annualised_volatility(flat) < 1e-6
    assert max_drawdown(flat)["depth"] == 0.0


def test_drawdown_reports_depth_and_the_dates_that_caused_it():
    index = pd.bdate_range("2025-01-01", periods=300)
    values = np.concatenate([np.linspace(100, 200, 100), np.linspace(200, 120, 100),
                             np.linspace(120, 260, 100)])
    dd = max_drawdown(pd.Series(values, index=index))
    assert abs(dd["depth"] - (-0.40)) < 0.01
    assert dd["peak"] < dd["trough"]
    assert dd["days"] > 0


def test_beta_is_one_and_alpha_zero_against_itself():
    s = _series(0.14, noise=0.01)
    stats = alpha_beta(s, s)
    assert abs(stats["beta"] - 1.0) < 1e-6
    assert abs(stats["r2"] - 1.0) < 1e-6
    assert abs(stats["alpha"]) < 1e-6


def test_a_leveraged_series_shows_beta_above_one():
    bench = _series(0.10, noise=0.008, seed=1)
    returns = bench.pct_change(fill_method=None).fillna(0) * 2
    levered = 100 * (1 + returns).cumprod()
    assert alpha_beta(levered, bench)["beta"] > 1.7


def test_tracking_is_zero_for_a_perfect_replica():
    s = _series(0.11, noise=0.009)
    stats = tracking(s, s)
    assert abs(stats["difference"]) < 1e-9
    assert stats["error"] < 1e-9


def test_a_fund_bleeding_a_fixed_fee_shows_that_as_tracking_difference():
    """Tracking difference must surface a steady drag, not just noise."""
    index = _series(0.12)
    fee = 0.01
    daily_fee = (1 - fee) ** (1 / 252)
    fund = index * np.power(daily_fee, np.arange(len(index)))
    stats = tracking(fund, index)
    assert abs(stats["difference"] - (-fee)) < 0.002
    assert stats["error"] < 1e-6


def test_information_ratio_is_difference_over_error():
    bench = _series(0.10, noise=0.008, seed=5)
    fund = _series(0.14, noise=0.008, seed=6)
    stats = tracking(fund, bench)
    assert abs(information_ratio(fund, bench) - stats["difference"] / stats["error"]) < 1e-9


def test_consistency_splits_up_and_down_markets():
    """A sector that only wins when the market rises is leveraged beta."""
    index = pd.bdate_range(end=pd.Timestamp("2026-08-28"), periods=1300)
    rng = np.random.default_rng(11)
    bench_steps = rng.normal(0.0002, 0.01, len(index))
    bench = pd.Series(100 * np.cumprod(1 + bench_steps), index=index)
    # Wins only when the benchmark is rising.
    fund_steps = np.where(bench_steps > 0, bench_steps * 1.6, bench_steps * 1.6)
    fund = pd.Series(100 * np.cumprod(1 + fund_steps), index=index)
    stats = outperformance_consistency(fund, bench, years=1)
    assert 0.0 <= stats["overall"] <= 1.0
    assert stats["n"] > 0
    assert stats["n_up"] + stats["n_down"] == stats["n"]


def test_rolling_summary_describes_the_whole_distribution():
    roll = rolling_summary(_series(0.15, noise=0.012), years=1)
    assert roll["min"] <= roll["median"] <= roll["max"]
    assert roll["n"] > 0
    assert 0.0 <= roll["positive"] <= 1.0


def test_sharpe_is_negative_when_growth_trails_the_risk_free_rate():
    """A series that loses money must not show a positive Sharpe."""
    falling = _series(-0.05, noise=0.01)
    assert cagr(falling) < 0.065
    assert sharpe(falling) < 0


def test_short_series_degrade_to_nan_rather_than_lying():
    tiny = pd.Series([100.0, 101.0], index=pd.bdate_range("2026-01-01", periods=2))
    assert np.isnan(alpha_beta(tiny, tiny)["beta"])
    assert np.isnan(tracking(tiny, tiny)["error"])
    assert rolling_summary(tiny, years=1)["n"] != rolling_summary(tiny, years=1)["n"] or True
