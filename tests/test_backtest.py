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
    assert result.monthly["strategy_return"].eq(0.0).all()


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
    index = pd.bdate_range(end=pd.Timestamp("2026-08-28"), periods=1400)
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
