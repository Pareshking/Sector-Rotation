import numpy as np
import pandas as pd

from src.config import load_strategy_config
from src.portfolio.calendar import fill_date
from src.portfolio.construct import CASH, construct_target_portfolio
from src.portfolio.universe import ExposureMeta
from src.quantitative.analytics import RISK_FREE_ANNUAL
from src.quantitative.backtest import (
    TRADING_DAYS,
    month_is_complete,
    period_split,
    rebalance_dates,
    rolling_summary_stats,
    rolling_windows,
    run_backtest,
    traded_weight,
    turnover,
    weight_sensitivity,
)

MONTHLY_CASH = (1 + RISK_FREE_ANNUAL) ** (1 / 12) - 1


def _config(**changes):
    """v1.0 over every index (no vehicle metadata needed) unless a test says otherwise."""
    return load_strategy_config().replace(**{"require_investable": False, **changes})


def _panel(days: int = 900, columns: int = 6, end: str = "2026-08-28") -> tuple[pd.DataFrame, pd.Series]:
    index = pd.bdate_range(end=pd.Timestamp(end), periods=days)
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


def _falling(days: int = 900, end: str = "2026-08-28", columns: int = 3):
    index = pd.bdate_range(end=pd.Timestamp(end), periods=days)
    prices = pd.DataFrame({f"exp{i}": np.linspace(300, 100, days) - i for i in range(columns)}, index=index)
    return prices, pd.Series(np.linspace(300, 100, days), index=index)


# --------------------------------------------------------------------------- #
# Calendar
# --------------------------------------------------------------------------- #
def test_rebalance_dates_are_month_ends() -> None:
    index = pd.bdate_range("2025-01-01", "2026-08-28")
    dates = rebalance_dates(index, months=12)
    assert len(dates) == 13
    assert all(a < b for a, b in zip(dates, dates[1:]))
    assert len({(d.year, d.month) for d in dates}) == len(dates)


def test_an_unfinished_final_month_is_not_a_rebalance_date():
    index = pd.bdate_range("2025-01-01", "2026-10-09")
    dates = rebalance_dates(index, months=12)
    assert dates[-1] == pd.Timestamp("2026-09-30")
    assert len(dates) == 13


def test_include_partial_keeps_the_unfinished_month_explicitly():
    index = pd.bdate_range("2025-01-01", "2026-10-09")
    assert rebalance_dates(index, months=12, include_partial=True)[-1] == pd.Timestamp("2026-10-09")


def test_a_month_ending_on_its_last_weekday_is_complete():
    index = pd.bdate_range("2025-01-01", "2026-09-30")
    assert rebalance_dates(index, months=12)[-1] == pd.Timestamp("2026-09-30")


def test_a_holiday_month_end_is_complete_once_the_next_month_starts():
    assert not month_is_complete(pd.Timestamp("2026-10-29"))
    index = pd.bdate_range("2025-01-01", "2026-10-29").append(pd.DatetimeIndex(["2026-11-02"]))
    assert rebalance_dates(index, months=12)[-1] == pd.Timestamp("2026-10-29")


def test_no_window_means_every_completed_month():
    index = pd.bdate_range("2024-01-01", "2026-08-31")
    assert len(rebalance_dates(index)) == 32


# --------------------------------------------------------------------------- #
# Guards
# --------------------------------------------------------------------------- #
def test_window_shorter_than_a_year_is_rejected() -> None:
    prices, benchmark = _panel()
    result = run_backtest(prices, benchmark, _config(), months=6)
    assert not result.ok
    assert "at least 12 months" in result.error


def test_empty_panel_reports_an_error() -> None:
    result = run_backtest(pd.DataFrame(), pd.Series(dtype=float), _config(), months=12)
    assert not result.ok
    assert result.error


# --------------------------------------------------------------------------- #
# Every decision comes from construct_target_portfolio
# --------------------------------------------------------------------------- #
def test_every_period_holds_exactly_what_construct_decided():
    """No selection logic of its own: replay construct with the same priors and compare."""
    prices, benchmark = _panel()
    config = _config()
    result = run_backtest(prices, benchmark, config, months=24)
    assert result.ok
    prior = {CASH: 1.0}
    by_signal = {pd.Timestamp(r.rebalance): r.holdings for r in result.monthly.itertuples()}
    for decision in result.decisions:
        replay = construct_target_portfolio(decision.as_of, prices, None, prior, config)
        assert replay.to_json() == decision.to_json()
        if decision.as_of in by_signal:
            assert by_signal[decision.as_of] == (", ".join(decision.holdings) or "cash")
        prior = decision.weights


def test_backtest_holds_at_most_n() -> None:
    prices, benchmark = _panel()
    result = run_backtest(prices, benchmark, _config(absolute_momentum_filter="none"), months=12)
    assert result.ok
    assert result.monthly["n_held"].max() <= 2
    assert result.stats["months"] <= 12


def test_the_holding_period_changes_the_number_of_decisions():
    prices, benchmark = _panel()
    monthly = run_backtest(prices, benchmark, _config(), months=24)
    quarterly = run_backtest(prices, benchmark, _config(rebalance_months=3), months=24)
    assert monthly.ok and quarterly.ok
    assert len(quarterly.monthly) < len(monthly.monthly)
    assert quarterly.stats["hold_months"] == 3.0


def test_investable_mode_without_any_vehicle_holds_only_cash():
    prices, benchmark = _panel(columns=4)
    result = run_backtest(prices, benchmark, _config(require_investable=True), universe_metadata={}, months=24)
    assert not result.ok  # nothing was ever eligible: every period is warm-up
    assert all(d.weights == {CASH: 1.0} for d in result.decisions)


def test_investability_is_judged_on_each_decision_date():
    prices, benchmark = _panel(columns=3)
    late = pd.Timestamp("2026-01-01")
    meta = {e: ExposureMeta(e, e, "sector", late if e == "exp2" else prices.index[0]) for e in prices}
    result = run_backtest(prices, benchmark, _config(require_investable=True), meta)
    early = result.monthly[pd.to_datetime(result.monthly["rebalance"]) < late]
    assert not early.empty
    assert not early["holdings"].str.contains("exp2").any()


def test_the_cash_hurdle_can_force_cash() -> None:
    prices, benchmark = _falling()
    result = run_backtest(prices, benchmark, _config(cost_bps_per_side=0), months=12)
    assert result.ok
    assert (result.monthly["cash_weight"] == 1.0).all()
    assert np.allclose(result.monthly["strategy_return"], MONTHLY_CASH)


def test_a_composite_winner_below_the_cash_hurdle_leaves_its_slot_in_cash():
    """Ranking uses the segment composite; the hurdle uses the 12-month return alone.

    The top-ranked name can therefore fail the hurdle. Its slot goes to cash —
    it is not handed to the next name down.
    """
    index = pd.bdate_range(end=pd.Timestamp("2026-08-31"), periods=900)
    n = len(index)

    def segmented(segments):
        values = [100.0]
        for days, total in segments:
            step = (1 + total) ** (1 / days)
            values.extend(values[-1] * step ** np.arange(1, days + 1))
        values = np.array(values[:n])
        return pd.Series(values, index=index)

    benchmark = segmented([(n, 0.05)])
    prices = pd.DataFrame(
        {
            # crashed, then ripping: best composite, negative over 12 months
            "spike": segmented([(n - 252, 0.60), (126, -0.42), (126, 0.38)]),
            "steady": segmented([(n - 252, 0.20), (252, 0.22)]),
            "dull": segmented([(n, 0.02)]),
        }
    )
    config = _config(target_holdings_n=1, retention_buffer_m=1, cost_bps_per_side=0)
    on = run_backtest(prices, benchmark, config, months=12)
    off = run_backtest(prices, benchmark, config.replace(absolute_momentum_filter="none"), months=12)
    assert on.ok and off.ok
    last_on, last_off = on.final_target, off.final_target
    assert last_off.holdings == ("spike",)
    assert last_on.holdings == ()
    assert last_on.weights == {CASH: 1.0}
    assert last_on.ranking.at["spike", "status"] == "fails cash hurdle"


# --------------------------------------------------------------------------- #
# Accounting: t+1 fills, costs, cash
# --------------------------------------------------------------------------- #
def test_a_period_runs_from_the_fill_after_its_signal_to_the_next_fill():
    """Signal at the month-end close t, executed at the close of t+1."""
    prices, benchmark = _panel()
    result = run_backtest(prices, benchmark, _config(cost_bps_per_side=0, absolute_momentum_filter="none"), months=12)
    row = result.monthly.iloc[0]
    signal, start, end = (pd.Timestamp(row[k]) for k in ("rebalance", "fill_date", "period_end"))
    assert start == fill_date(prices.index, signal) and start > signal
    next_signal = pd.Timestamp(result.monthly.iloc[1]["rebalance"])
    assert end == fill_date(prices.index, next_signal)
    held = row["holdings"].split(", ")
    expected = sum(0.5 * (prices.at[end, e] / prices.at[start, e] - 1) for e in held)
    assert abs(row["strategy_return"] - expected) < 1e-12
    bench = benchmark.at[end] / benchmark.at[start] - 1
    assert abs(row["benchmark_return"] - bench) < 1e-12


def test_costs_are_charged_per_side_on_traded_weight():
    prices, benchmark = _panel()
    config = _config(cost_bps_per_side=25)
    result = run_backtest(prices, benchmark, config, months=24)
    free = run_backtest(prices, benchmark, config.replace(cost_bps_per_side=0), months=24)
    assert result.ok and free.ok
    for paid, gross in zip(result.monthly.itertuples(), free.monthly.itertuples()):
        assert abs(paid.gross_return - gross.strategy_return) < 1e-12
        assert abs(paid.strategy_return - ((1 - paid.cost) * (1 + paid.gross_return) - 1)) < 1e-12
    first = result.monthly.iloc[0]
    assert abs(first["cost"] - 25e-4 * 1.0) < 1e-12  # buying a full book from cash
    assert result.stats["total_cost"] == result.monthly["cost"].sum()
    assert result.stats["total_return"] < free.stats["total_return"]


def test_the_cost_basis_excludes_the_cash_leg():
    both = {"a": 0.5, "b": 0.5}
    assert traded_weight(both, {"a": 0.5, CASH: 0.5}) == 0.5  # sell b only
    assert traded_weight({CASH: 1.0}, both) == 1.0
    assert traded_weight(both, {"a": 0.5, "c": 0.5}) == 1.0  # sell b, buy c


def test_unallocated_capital_accrues_the_risk_free_rate():
    prices, benchmark = _falling()
    prices["exp0"] = np.linspace(100, 300, len(prices))  # one exposure clears the hurdle
    result = run_backtest(prices, benchmark, _config(cost_bps_per_side=0), months=12)
    assert result.ok
    assert (result.monthly["cash_weight"] == 0.5).all()
    for row in result.monthly.itertuples():
        held = row.holding_1_return
        assert abs(row.strategy_return - (0.5 * held + 0.5 * MONTHLY_CASH)) < 1e-12


def test_a_fully_invested_book_earns_no_cash_return():
    prices, benchmark = _panel()
    result = run_backtest(prices, benchmark, _config(absolute_momentum_filter="none", cost_bps_per_side=0), months=12)
    assert (result.monthly["cash_weight"] == 0).all()
    picked = result.monthly[["holding_1_return", "holding_2_return"]].sum(axis=1) / 2
    assert np.allclose(result.monthly["strategy_return"], picked)


def test_the_backtest_never_reports_a_partial_final_period():
    prices, benchmark = _panel(days=900)  # ends Friday 28 Aug 2026; 31 Aug is a weekday
    result = run_backtest(prices, benchmark, _config(), months=12)
    assert result.ok
    # Last complete signal is 31 Jul; its period has not run. The last reported
    # period is the 30 Jun decision, filled 1 Jul and closed at the 3 Aug fill.
    assert result.final_target.as_of == pd.Timestamp("2026-07-31")
    assert pd.Timestamp(result.monthly["period_end"].iloc[-1]) == pd.Timestamp("2026-08-03")


def test_an_explicit_partial_period_accrues_cash_by_its_actual_length():
    prices, benchmark = _falling(end="2026-10-09", columns=1)
    result = run_backtest(prices, benchmark, _config(cost_bps_per_side=0), months=12, include_partial=True)
    last = result.monthly.iloc[-1]
    assert pd.Timestamp(last["period_end"]) == pd.Timestamp("2026-10-09")
    days = (pd.Timestamp("2026-10-09") - pd.Timestamp(last["fill_date"])).days
    assert abs(last["cash_return"] - ((1 + RISK_FREE_ANNUAL) ** (days / 365.25) - 1)) < 1e-12


# --------------------------------------------------------------------------- #
# Turnover and statistics
# --------------------------------------------------------------------------- #
def test_turnover_counts_moves_into_and_out_of_cash_at_full_size():
    both = {"a": 0.5, "b": 0.5}
    assert turnover(both, {"a": 0.5, CASH: 0.5}) == 0.5
    assert turnover(both, {"a": 0.5, "c": 0.5}) == 0.5
    assert turnover({CASH: 1.0}, both) == 1.0
    assert turnover(both, {CASH: 1.0}) == 1.0
    assert turnover(both, dict(both)) == 0.0


def test_the_first_rebalance_buys_the_whole_book_from_cash():
    prices, benchmark = _panel()
    result = run_backtest(prices, benchmark, _config(absolute_momentum_filter="none"), months=12)
    assert result.monthly["turnover"].iloc[0] == 1.0
    assert result.stats["avg_turnover"] == result.monthly["turnover"].mean()


def test_the_buffer_reduces_turnover():
    prices, benchmark = _panel(columns=8)
    buffered = run_backtest(prices, benchmark, _config(), months=24)
    tight = run_backtest(prices, benchmark, _config(retention_buffer_m=2), months=24)
    assert buffered.stats["avg_turnover"] <= tight.stats["avg_turnover"]


def test_cagr_is_annualised_by_the_sessions_actually_covered():
    prices, benchmark = _panel(days=900)
    result = run_backtest(prices, benchmark, _config(), months=12)
    first = pd.Timestamp(result.monthly["fill_date"].iloc[0])
    last = pd.Timestamp(result.monthly["period_end"].iloc[-1])
    sessions = int(((prices.index > first) & (prices.index <= last)).sum())
    stats = result.stats
    assert stats["sessions"] == sessions
    assert abs(stats["years"] - sessions / TRADING_DAYS) < 1e-12
    assert abs(stats["cagr"] - ((1 + stats["total_return"]) ** (1 / stats["years"]) - 1)) < 1e-12


def test_sharpe_subtracts_the_risk_free_rate_like_analytics():
    prices, benchmark = _panel()
    stats = run_backtest(prices, benchmark, _config(), months=12).stats
    assert stats["risk_free"] == RISK_FREE_ANNUAL
    assert abs(stats["sharpe"] - (stats["cagr"] - RISK_FREE_ANNUAL) / stats["volatility"]) < 1e-12


def test_equity_curve_starts_at_the_first_fill():
    prices, benchmark = _panel(days=600)
    result = run_backtest(prices, benchmark, _config(), months=24)
    assert result.ok
    assert result.stats["warmup_months"] > 0
    assert result.equity.index[0] == pd.Timestamp(result.monthly["fill_date"].iloc[0])
    assert result.equity["strategy"].iloc[0] == 100.0


def test_period_split_compounds_each_half_separately():
    prices, benchmark = _panel(days=1300)
    result = run_backtest(prices, benchmark, _config(), months=36)
    split = period_split(result, boundary="2025-01-01")
    assert list(split["half"]) == ["early", "recent"]
    assert int(split["periods"].sum()) == len(result.monthly)
    for row in split.itertuples():
        assert abs(row.excess - (row.strategy - row.benchmark)) < 1e-12


def test_score_sensitivity_reports_one_row_per_scheme():
    prices, benchmark = _panel(columns=5)
    base = _config()
    schemes = {
        "equal": base,
        "recent": base.replace(score_weights={"method": "segment_composite",
                                               "segments": {"1M": 4, "3M-1M": 3, "6M-3M": 2, "12M-6M": 1}}),
        "vol": base.replace(score_weights={"method": "vol_adjusted_12m"}),
    }
    grid = weight_sensitivity(prices, benchmark, schemes, months=24)
    assert list(grid["weighting"]) == ["equal", "recent", "vol"]
    assert {"total_return", "excess", "max_drawdown", "turnover"} <= set(grid.columns)


def test_rolling_windows_cover_every_overlapping_stretch():
    prices, benchmark = _panel(days=1300)
    result = run_backtest(prices, benchmark, _config(), months=36)
    windows = rolling_windows(result, window=12)
    assert len(windows) == len(result.monthly) - 12 + 1
    assert (windows["end"] > windows["start"]).all()
    stats = rolling_summary_stats(windows)
    assert stats["windows"] == len(windows)
    assert stats["worst_excess"] <= stats["median_excess"] <= stats["best_excess"]


def test_rolling_windows_are_empty_when_the_record_is_too_short():
    prices, benchmark = _panel()
    result = run_backtest(prices, benchmark, _config(), months=12)
    assert rolling_windows(result, window=24).empty
    assert rolling_summary_stats(rolling_windows(result, window=24)) == {}


def test_rrg_history_is_backward_looking():
    """Display-only RRG panel: reading it at t must not depend on data after t."""
    from src.quantitative.relative_strength import signal_at, signal_panel

    prices, benchmark = _panel(columns=2)
    cut = prices.index[-200]
    full = signal_panel(prices, benchmark)
    truncated = signal_panel(prices.loc[:cut], benchmark.loc[:cut])
    for exposure_id in truncated:
        a, b = signal_at(full, exposure_id, cut), signal_at(truncated, exposure_id, cut)
        if a is None or b is None:
            continue
        assert abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9
