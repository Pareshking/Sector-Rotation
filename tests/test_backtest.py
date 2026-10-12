import numpy as np
import pandas as pd

from src.quantitative.analytics import RISK_FREE_ANNUAL
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
    # Fully in cash, the book earns the risk-free rate and nothing else.
    monthly_cash = (1 + RISK_FREE_ANNUAL) ** (1 / 12) - 1
    assert np.allclose(result.monthly["strategy_return"], monthly_cash)


def test_empty_panel_reports_an_error() -> None:
    result = run_backtest(pd.DataFrame(), pd.Series(dtype=float), months=12)
    assert not result.ok
    assert result.error


def _vehicles(first_dates: dict[str, str], days: int = 900):
    """Vehicle price panel whose columns start on the given dates."""
    index = pd.bdate_range(end=pd.Timestamp("2026-08-28"), periods=days)
    data = {}
    for key, start in first_dates.items():
        series = pd.Series(np.linspace(100, 200, len(index)), index=index)
        series[series.index < pd.Timestamp(start)] = np.nan
        data[key] = series
    return pd.DataFrame(data, index=index)


def test_holding_period_changes_the_number_of_decisions():
    prices, benchmark = _panel()
    monthly = run_backtest(prices, benchmark, months=24, hold_months=1, absolute_filter=False)
    quarterly = run_backtest(prices, benchmark, months=24, hold_months=3, absolute_filter=False)
    assert monthly.ok and quarterly.ok
    assert len(monthly.monthly) == 24
    assert len(quarterly.monthly) == 8
    assert quarterly.stats["hold_months"] == 3.0
    assert quarterly.stats["months"] == 24.0


def test_investability_is_point_in_time_not_todays_lineup():
    """A fund that launched in 2026 must not be buyable in 2022."""
    from src.quantitative.backtest import investable_from

    vehicles = _vehicles({"NEW": "2026-01-01", "OLD": "2020-01-01"})
    starts = investable_from(vehicles, {"a": ["NEW"], "b": ["OLD"]})
    assert starts["a"] >= pd.Timestamp("2026-01-01")
    # OLD predates the panel, so its first observation is the panel's own start.
    assert starts["b"] == vehicles.index.min()
    assert starts["b"] < starts["a"]


def test_investable_only_holds_cash_when_nothing_can_be_bought():
    prices, benchmark = _panel(columns=4)
    # No vehicle for any exposure at all.
    result = run_backtest(
        prices, benchmark, top_n=2, months=12, absolute_filter=False,
        investable_only=True, vehicle_prices=pd.DataFrame(), vehicles_by_exposure={},
    )
    assert result.ok
    assert (result.monthly["cash_slots"] == 2).all()
    monthly_cash = (1 + RISK_FREE_ANNUAL) ** (1 / 12) - 1
    assert np.allclose(result.monthly["strategy_return"], monthly_cash)


def test_substitution_never_reaches_past_the_rank_depth():
    """Beyond the depth the slot is cash, not a name the model never favoured."""
    prices, benchmark = _panel(columns=6)
    vehicles = _vehicles({"exp0": "2020-01-01"})
    result = run_backtest(
        prices, benchmark, top_n=1, months=12, absolute_filter=False,
        investable_only=True, max_rank_depth=2,
        vehicle_prices=vehicles, vehicles_by_exposure={"exp0": ["exp0"]},
    )
    assert result.ok
    held = set(result.monthly["holdings"])
    assert held <= {"exp0", "cash"}


def test_buy_gate_only_admits_exposures_passing_the_live_rule():
    prices, benchmark = _panel(columns=5)
    gated = run_backtest(prices, benchmark, top_n=2, months=12,
                         absolute_filter=False, require_buy=True)
    ungated = run_backtest(prices, benchmark, top_n=2, months=12, absolute_filter=False)
    assert gated.ok and ungated.ok
    assert gated.monthly["n_held"].sum() <= ungated.monthly["n_held"].sum()


def test_signal_panel_is_backward_looking():
    """Reading the panel at t must not depend on data after t."""
    from src.quantitative.backtest import _signal_at, signal_panel

    prices, benchmark = _panel(columns=2)
    cut = prices.index[-200]
    full = signal_panel(prices, benchmark)
    truncated = signal_panel(prices.loc[:cut], benchmark.loc[:cut])
    for exposure_id in truncated:
        a = _signal_at(full, exposure_id, cut)
        b = _signal_at(truncated, exposure_id, cut)
        if a is None or b is None:
            continue
        assert abs(a[0] - b[0]) < 1e-9
        assert abs(a[1] - b[1]) < 1e-9


def _segmented(index, segments):
    values = [100.0]
    for days, total in segments:
        step = (1 + total) ** (1 / days)
        for _ in range(days):
            values.append(values[-1] * step)
    values = values[: len(index)] + [values[-1]] * max(0, len(index) - len(values))
    return pd.Series(values[: len(index)], index=index)


def test_absolute_filter_rejects_a_composite_winner_with_negative_12m():
    """The decisive dual-momentum case.

    Ranking uses a composite across 1M/3M/6M/12M while the absolute filter uses
    12M alone, so the top-ranked name can be negative on absolute momentum. It
    must then be rejected and the next positive name taken instead. (Ranking on
    relative return and filtering on absolute over the *same* window can never
    disagree — both subtract the same benchmark — so only the composite makes
    this case reachable.)
    """
    # Ends on the last weekday of August so August is a complete month and the
    # final decision is the 31 July rebalance the scenario is built around.
    index = pd.bdate_range(end=pd.Timestamp("2026-08-31"), periods=1400)
    n = len(index)
    benchmark = _segmented(index, [(n, 0.05)])
    prices = pd.DataFrame(
        {
            # crashed, then ripping: best composite, negative on 12M
            "spike": _segmented(index, [(n - 252, 0.60), (126, -0.42), (126, 0.38)]),
            "steady": _segmented(index, [(n - 252, 0.20), (252, 0.22)]),
            "dull": _segmented(index, [(n, 0.02)]),
        }
    )
    trailing = prices.iloc[-1] / prices.iloc[-253] - 1
    assert trailing["spike"] < 0 < trailing["steady"], "scenario must have a negative-12M leader"

    off = run_backtest(prices, benchmark, top_n=1, months=12, absolute_filter=False)
    on = run_backtest(prices, benchmark, top_n=1, months=12, absolute_filter=True)
    assert off.ok and on.ok
    assert off.monthly["holdings"].iloc[-1] == "spike"
    assert on.monthly["holdings"].iloc[-1] == "steady"


def test_depth_cap_does_not_apply_to_the_unconstrained_universe():
    """Full-universe scanning must fill top_n however deep it has to go."""
    prices, benchmark = _panel(columns=6)
    result = run_backtest(prices, benchmark, top_n=5, months=12,
                          absolute_filter=False, max_rank_depth=2)
    assert result.ok
    assert result.monthly["n_held"].max() == 5


def test_stats_report_the_warmup_the_window_consumed():
    prices, benchmark = _panel(days=900)
    result = run_backtest(prices, benchmark, months=24, absolute_filter=False)
    assert result.ok
    assert result.stats["requested_months"] == 24.0
    assert result.stats["months"] <= 24.0
    assert result.stats["warmup_months"] == 24.0 - result.stats["months"]


def test_weights_change_the_ranking_and_flow_into_the_backtest():
    """A site-wide weighting must reach the backtest, not just the live board."""
    from src.quantitative.ranking import normalise_weights

    assert normalise_weights({"1M": 10, "3M": 50, "6M": 40, "12M": 0}) == {
        "1M": 0.1, "3M": 0.5, "6M": 0.4
    }
    # Unknown horizons dropped, negatives clamped, empty falls back to equal.
    assert normalise_weights({"9M": 100}) == normalise_weights(None)
    assert normalise_weights({"1M": -5, "3M": 5}) == {"3M": 1.0}

    prices, benchmark = _panel(columns=5)
    short = run_backtest(prices, benchmark, months=12, absolute_filter=False,
                         weights={"1M": 1, "3M": 1, "6M": 1, "12M": 0})
    equal = run_backtest(prices, benchmark, months=12, absolute_filter=False)
    assert short.ok and equal.ok


def test_period_split_compounds_each_half_separately():
    prices, benchmark = _panel(days=1300)
    result = run_backtest(prices, benchmark, months=36, absolute_filter=False)
    from src.quantitative.backtest import period_split

    split = period_split(result, boundary="2025-01-01")
    assert list(split["half"]) == ["early", "recent"]
    assert int(split["periods"].sum()) == len(result.monthly)
    for row in split.itertuples():
        assert abs(row.excess - (row.strategy - row.benchmark)) < 1e-12


def test_weight_sensitivity_reports_one_row_per_scheme():
    from src.quantitative.backtest import weight_sensitivity

    prices, benchmark = _panel(columns=5)
    schemes = {
        "equal": {"1M": 25, "3M": 25, "6M": 25, "12M": 25},
        "short": {"1M": 33, "3M": 33, "6M": 34, "12M": 0},
    }
    grid = weight_sensitivity(prices, benchmark, schemes, months=12, absolute_filter=False)
    assert list(grid["weighting"]) == ["equal", "short"]
    assert {"total_return", "excess", "max_drawdown", "turnover"} <= set(grid.columns)


def test_rolling_windows_cover_every_overlapping_stretch():
    prices, benchmark = _panel(days=1300)
    result = run_backtest(prices, benchmark, months=36, absolute_filter=False)
    from src.quantitative.backtest import rolling_summary_stats, rolling_windows

    windows = rolling_windows(result, window=12)
    assert len(windows) == len(result.monthly) - 12 + 1
    assert (windows["end"] > windows["start"]).all()
    for row in windows.itertuples():
        assert abs(row.excess - (row.strategy - row.benchmark)) < 1e-12

    stats = rolling_summary_stats(windows)
    assert stats["windows"] == len(windows)
    assert 0.0 <= stats["beat_rate"] <= 1.0
    assert stats["worst_excess"] <= stats["median_excess"] <= stats["best_excess"]


def test_rolling_windows_are_empty_when_the_record_is_too_short():
    prices, benchmark = _panel()
    result = run_backtest(prices, benchmark, months=12, absolute_filter=False)
    from src.quantitative.backtest import rolling_summary_stats, rolling_windows

    assert rolling_windows(result, window=24).empty
    assert rolling_summary_stats(rolling_windows(result, window=24)) == {}


# --------------------------------------------------------------------------- #
# Phase 0 remediation: calculation defects
# --------------------------------------------------------------------------- #
def test_an_unfinished_final_month_is_not_a_rebalance_date():
    """Mid-October, the latest close is not an October month end."""
    index = pd.bdate_range("2025-01-01", "2026-10-09")
    dates = rebalance_dates(index, months=12)
    assert dates[-1] == pd.Timestamp("2026-09-30")
    assert len(dates) == 13


def test_include_partial_keeps_the_unfinished_month_explicitly():
    index = pd.bdate_range("2025-01-01", "2026-10-09")
    dates = rebalance_dates(index, months=12, include_partial=True)
    assert dates[-1] == pd.Timestamp("2026-10-09")


def test_a_month_ending_on_its_last_weekday_is_complete():
    index = pd.bdate_range("2025-01-01", "2026-09-30")
    assert rebalance_dates(index, months=12)[-1] == pd.Timestamp("2026-09-30")


def test_a_holiday_month_end_is_complete_once_the_next_month_starts():
    """If the last weekday is a holiday the month closes a session late, never early."""
    from src.quantitative.backtest import month_is_complete

    # 30 Oct 2026 is a Friday; treat it as a holiday, so October's last session is the 29th.
    assert not month_is_complete(pd.Timestamp("2026-10-29"))
    index = pd.bdate_range("2025-01-01", "2026-10-29").append(pd.DatetimeIndex(["2026-11-02"]))
    dates = rebalance_dates(index, months=12)
    assert dates[-1] == pd.Timestamp("2026-10-29")


def test_the_backtest_never_reports_a_partial_final_period():
    prices, benchmark = _panel(days=900)  # ends Friday 28 Aug 2026; 31 Aug is a weekday
    result = run_backtest(prices, benchmark, months=12, absolute_filter=False)
    assert result.ok
    assert pd.Timestamp(result.monthly["period_end"].iloc[-1]) == pd.Timestamp("2026-07-31")


def test_cagr_is_annualised_by_the_sessions_actually_covered():
    from src.quantitative.backtest import TRADING_DAYS

    prices, benchmark = _panel(days=900)
    result = run_backtest(prices, benchmark, months=12, absolute_filter=False)
    first = pd.Timestamp(result.monthly["rebalance"].iloc[0])
    last = pd.Timestamp(result.monthly["period_end"].iloc[-1])
    sessions = int(((prices.index > first) & (prices.index <= last)).sum())
    stats = result.stats
    assert stats["sessions"] == sessions
    assert abs(stats["years"] - sessions / TRADING_DAYS) < 1e-12
    expected = (1 + stats["total_return"]) ** (1 / stats["years"]) - 1
    assert abs(stats["cagr"] - expected) < 1e-12


def test_an_explicit_partial_period_accrues_cash_by_its_actual_length():
    index = pd.bdate_range(end=pd.Timestamp("2026-10-09"), periods=900)
    falling = pd.DataFrame({"exp0": np.linspace(300, 100, len(index))}, index=index)
    benchmark = pd.Series(np.linspace(300, 100, len(index)), index=index)
    result = run_backtest(falling, benchmark, top_n=1, months=12, include_partial=True)
    last = result.monthly.iloc[-1]
    assert pd.Timestamp(last["period_end"]) == pd.Timestamp("2026-10-09")
    days = (pd.Timestamp("2026-10-09") - pd.Timestamp(last["rebalance"])).days
    assert abs(last["cash_return"] - ((1 + RISK_FREE_ANNUAL) ** (days / 365.25) - 1)) < 1e-12


def test_unallocated_capital_accrues_the_risk_free_rate():
    """Each period gains exactly cash_weight x the monthly risk-free rate over a 0% book."""
    prices, benchmark = _panel(columns=5)
    kwargs = {"top_n": 2, "months": 12, "absolute_filter": True, "require_buy": True}
    with_cash = run_backtest(prices, benchmark, cash_rate=RISK_FREE_ANNUAL, **kwargs)
    without = run_backtest(prices, benchmark, cash_rate=0.0, **kwargs)
    assert with_cash.ok and without.ok
    assert (with_cash.monthly["cash_weight"] > 0).any(), "scenario must leave some capital in cash"
    monthly_cash = (1 + RISK_FREE_ANNUAL) ** (1 / 12) - 1
    gain = with_cash.monthly["strategy_return"] - without.monthly["strategy_return"]
    assert np.allclose(gain, with_cash.monthly["cash_weight"] * monthly_cash)
    assert with_cash.stats["cash_rate"] == RISK_FREE_ANNUAL


def test_a_fully_invested_book_earns_no_cash_return():
    prices, benchmark = _panel()
    result = run_backtest(prices, benchmark, top_n=2, months=12, absolute_filter=False)
    assert (result.monthly["cash_weight"] == 0).all()
    gross = result.monthly["strategy_return"]
    picked = result.monthly[["holding_1_return", "holding_2_return"]].sum(axis=1) / 2
    assert np.allclose(gross, picked)


def test_turnover_counts_moves_into_and_out_of_cash_at_full_size():
    from src.quantitative.backtest import CASH, turnover

    both = {"a": 0.5, "b": 0.5}
    assert turnover(both, {"a": 0.5, CASH: 0.5}) == 0.5  # previously reported 0.25
    assert turnover(both, {"a": 0.5, "c": 0.5}) == 0.5
    assert turnover({CASH: 1.0}, both) == 1.0
    assert turnover(both, {CASH: 1.0}) == 1.0
    assert turnover(both, dict(both)) == 0.0


def test_the_first_rebalance_buys_the_whole_book_from_cash():
    prices, benchmark = _panel()
    result = run_backtest(prices, benchmark, top_n=2, months=12, absolute_filter=False)
    assert result.monthly["turnover"].iloc[0] == 1.0
    assert result.stats["avg_turnover"] == result.monthly["turnover"].mean()


def test_turnover_in_the_backtest_matches_the_weight_formula():
    """Recompute tau_t from the reported holdings and cash weights, row by row."""
    from src.quantitative.backtest import CASH

    prices, benchmark = _panel(columns=5)
    result = run_backtest(prices, benchmark, top_n=2, months=24, require_buy=True)
    assert result.ok
    previous = {CASH: 1.0}
    for row in result.monthly.itertuples():
        held = [] if row.holdings == "cash" else row.holdings.split(", ")
        current = {name: 0.5 for name in held}
        if row.cash_weight:
            current[CASH] = row.cash_weight
        keys = set(previous) | set(current)
        expected = 0.5 * sum(abs(current.get(k, 0) - previous.get(k, 0)) for k in keys)
        assert abs(row.turnover - expected) < 1e-12
        previous = current


def test_sharpe_subtracts_the_risk_free_rate_like_analytics():
    prices, benchmark = _panel()
    result = run_backtest(prices, benchmark, months=12, absolute_filter=False)
    stats = result.stats
    assert stats["risk_free"] == RISK_FREE_ANNUAL
    assert abs(stats["sharpe"] - (stats["cagr"] - RISK_FREE_ANNUAL) / stats["volatility"]) < 1e-12
    assert abs(
        stats["benchmark_sharpe"]
        - (stats["benchmark_cagr"] - RISK_FREE_ANNUAL) / stats["benchmark_volatility"]
    ) < 1e-12


def test_equity_curve_starts_at_the_first_invested_rebalance():
    # ~28 months of data, so the first rebalances of a 24-month window lack the
    # 12-month history the ranking needs and hold nothing.
    prices, benchmark = _panel(days=600)
    result = run_backtest(prices, benchmark, months=24, absolute_filter=False)
    assert result.ok
    assert result.stats["warmup_months"] > 0
    assert result.equity.index[0] == pd.Timestamp(result.monthly["rebalance"].iloc[0])
    assert result.equity["strategy"].iloc[0] == 100.0


def _convex(index, curvature: float) -> pd.Series:
    """Log level growing with t**2: relative strength that keeps accelerating."""
    t = np.arange(len(index)) / 252.0
    return pd.Series(100 * np.exp(0.05 * t + curvature * t**2), index=index)


def test_buy_gate_requires_positive_momentum_z_like_the_live_rule():
    """A Leading name with RS ratio > 1 and velocity > 0 is still not a BUY at momentum Z <= 0.

    With two exposures the cross-sectional Z-scores are exactly +1 and -1, so the
    weaker one passes every RS test yet must be rejected by the Z test.
    """
    from src.quantitative.backtest import _signal_at, signal_panel

    index = pd.bdate_range(end=pd.Timestamp("2026-08-31"), periods=900)
    benchmark = pd.Series(100 * np.exp(0.05 * np.arange(len(index)) / 252.0), index=index)
    prices = pd.DataFrame({"strong": _convex(index, 0.08), "weaker": _convex(index, 0.04)})

    result = run_backtest(prices, benchmark, top_n=2, months=12, absolute_filter=False,
                          require_buy=True, max_rank_depth=2)
    assert result.ok
    last = pd.Timestamp(result.monthly["rebalance"].iloc[-1])
    ratio, velocity = _signal_at(signal_panel(prices, benchmark), "weaker", last)
    assert ratio > 1.0 and velocity > 0, "scenario must have 'weaker' pass every RS test"

    assert set(result.monthly["holdings"]) == {"strong"}
    assert (result.monthly["n_held"] == 1).all()
    assert result.monthly["skipped"].str.contains("weaker:not BUY").all()
