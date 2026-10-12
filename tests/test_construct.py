"""construct_target_portfolio: the one rule set behind the dashboard and the backtest."""

import json

import numpy as np
import pandas as pd
import pytest

from src.config import SEGMENTS, StrategyConfig, load_strategy_config
from src.portfolio.calendar import fill_date, next_rebalance_date
from src.portfolio.construct import (
    BUY,
    CASH,
    HOLD,
    SELL,
    TRIM,
    construct_target_portfolio,
    decision_chain,
)
from src.portfolio.score import score_exposures
from src.portfolio.universe import ExposureMeta, build_universe_metadata

INDEX = pd.bdate_range(end="2026-08-31", periods=300)
AS_OF = INDEX[-1]


def _path(segments, sessions: int = len(INDEX)) -> np.ndarray:
    """Prices whose log return over each non-overlapping segment is exactly as given."""
    daily = np.zeros(sessions)
    for (_, (newer, older)), total in zip(SEGMENTS.items(), segments):
        daily[sessions - older: sessions - newer] = total / (older - newer)
    return 100 * np.exp(np.concatenate([[0.0], np.cumsum(daily)[1:]]))


def _drifts(**drifts: float) -> pd.DataFrame:
    """Constant daily log drift per exposure: rank order equals drift order."""
    t = np.arange(len(INDEX))
    return pd.DataFrame({k: 100 * np.exp(v * t) for k, v in drifts.items()}, index=INDEX)


SIX = _drifts(a=0.0012, b=0.0010, c=0.0008, d=0.0006, e=0.0004, f=0.0002)


def _meta(prices: pd.DataFrame, since: str = "2020-01-01", **overrides) -> dict[str, ExposureMeta]:
    out = {e: ExposureMeta(e, e.upper(), "sector", pd.Timestamp(since)) for e in prices.columns}
    out.update(overrides)
    return out


def _config(**changes) -> StrategyConfig:
    return load_strategy_config().replace(**changes)


def _build(prices=SIX, prior=None, config=None, meta=None, when=AS_OF):
    return construct_target_portfolio(
        when, prices, _meta(prices) if meta is None else meta, prior, config or _config()
    )


def _actions(target) -> dict[str, str]:
    return {d.exposure_id: d.action for d in target.decisions}


# --------------------------------------------------------------------------- #
# The v1.0 specification
# --------------------------------------------------------------------------- #
def test_the_v1_config_is_the_specified_strategy():
    config = load_strategy_config()
    assert config.version == "1.0"
    assert (config.target_holdings_n, config.retention_buffer_m) == (2, 4)
    assert config.score_weights.method == "segment_composite"
    assert config.score_weights.segments == {"1M": 0.25, "3M-1M": 0.25, "6M-3M": 0.25, "12M-6M": 0.25}
    assert config.absolute_momentum_filter == "dual_momentum_cash_hurdle"
    assert config.risk_free_rate_annual == 0.065
    assert config.execution_fill == "t_plus_1_close"
    assert config.cost_bps_per_side == 25


def test_a_buffer_tighter_than_entry_is_rejected():
    with pytest.raises(ValueError, match="retention_buffer_m"):
        _config(retention_buffer_m=1)


def test_unknown_score_segments_are_rejected():
    with pytest.raises(ValueError, match="unknown segments"):
        _config(score_weights={"method": "segment_composite", "segments": {"12-1M": 1.0}})


def test_the_config_hash_changes_with_any_rule():
    base = load_strategy_config()
    assert base.config_hash == load_strategy_config().config_hash
    assert base.replace(retention_buffer_m=5).config_hash != base.config_hash


# --------------------------------------------------------------------------- #
# Score
# --------------------------------------------------------------------------- #
def test_segments_tile_the_last_year_exactly_once():
    edges = sorted(SEGMENTS.values())
    assert edges[0][0] == 0 and edges[-1][1] == 252
    assert all(a[1] == b[0] for a, b in zip(edges, edges[1:]))


def test_the_composite_is_the_weighted_sum_of_segment_z_scores():
    prices = pd.DataFrame(
        {"a": _path([0.10] * 4), "b": _path([0.40, 0.25, 0.0, -0.50]), "c": _path([0.02, 0.04, 0.06, 0.08])},
        index=INDEX,
    )
    scores = score_exposures(prices, AS_OF, _config())
    expected = pd.Series(0.0, index=prices.columns)
    for name in SEGMENTS:
        seg = scores[f"seg_{name}"]
        expected += 0.25 * (seg - seg.mean()) / seg.std(ddof=0)
    assert np.allclose(scores["score"], expected)
    assert abs(scores.at["b", "seg_1M"] - 0.40) < 1e-9


def test_the_latest_month_is_scored_not_skipped():
    """Changing only the last 21 sessions must move the score (no 12-1 skip)."""
    base = pd.DataFrame({"a": _path([0.05] * 4), "b": _path([0.05] * 4), "c": _path([0.0] * 4)}, index=INDEX)
    late = base.copy()
    late["b"] = _path([0.30, 0.05, 0.05, 0.05])
    before = score_exposures(base, AS_OF, _config())["score"]
    after = score_exposures(late, AS_OF, _config())["score"]
    assert after["b"] > before["b"]
    assert score_exposures(late, AS_OF, _config()).at["b", "universe_rank"] == 1


def test_a_score_never_reads_prices_after_its_date():
    when = INDEX[-40]
    full = score_exposures(SIX, when, _config())
    cut = score_exposures(SIX.loc[:when], when, _config())
    pd.testing.assert_frame_equal(full, cut)


def test_a_short_history_is_not_scorable():
    prices = SIX.copy()
    prices.loc[: INDEX[-200], "a"] = np.nan
    scores = score_exposures(prices, AS_OF, _config())
    assert not scores.at["a", "valid"] and pd.isna(scores.at["a", "score"])
    assert scores.loc[["b", "c"], "valid"].all()


def test_the_vol_adjusted_alternative_divides_12m_return_by_ewma_vol():
    rng = np.random.default_rng(3)
    noisy = pd.DataFrame(
        {k: 100 * np.exp(np.cumsum(rng.normal(mu, sd, len(INDEX))))
         for k, (mu, sd) in {"calm": (0.0008, 0.005), "wild": (0.0010, 0.03)}.items()},
        index=INDEX,
    )
    config = _config(score_weights={"method": "vol_adjusted_12m"})
    scores = score_exposures(noisy, AS_OF, config)
    logp = np.log(noisy)
    vol = logp.diff().ewm(span=126, min_periods=126).std().iloc[-1] * np.sqrt(252)
    expected = (logp.iloc[-1] - logp.iloc[-253]) / vol
    assert np.allclose(scores["score"], expected)


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #
def test_from_cash_the_top_n_are_bought_at_equal_weight():
    target = _build()
    assert target.holdings == ("a", "b")
    assert target.weights == {"a": 0.5, "b": 0.5}
    assert _actions(target) == {"a": BUY, "b": BUY}
    assert all(d.reason for d in target.decisions)


def test_weights_always_sum_to_one_with_cash():
    target = _build(config=_config(risk_free_rate_annual=0.30))
    assert abs(sum(target.weights.values()) - 1.0) < 1e-12


def test_a_holding_inside_the_buffer_is_retained():
    """Hysteresis: rank 4 (<= M) is kept; nothing below rank N is ever bought."""
    target = _build(prior={"d": 0.5, "e": 0.5})
    assert target.weights == {"a": 0.5, "d": 0.5}
    actions = _actions(target)
    assert actions == {"a": BUY, "d": HOLD, "e": SELL}
    assert "retention buffer" in next(d.reason for d in target.decisions if d.exposure_id == "e")


def test_new_entries_need_rank_within_n_even_with_a_vacancy():
    """A rank-3 name inside the buffer is not bought just because a slot is free."""
    target = _build(prior={"a": 0.5, "f": 0.5})  # f falls out (rank 6 > 4)
    assert target.weights == {"a": 0.5, "b": 0.5}
    assert target.ranking.at["c", "status"] == "inside buffer, entry needs rank <= N"


def test_with_both_slots_retained_a_better_name_waits():
    target = _build(prior={"c": 0.5, "d": 0.5})
    assert target.holdings == ("c", "d")
    assert target.ranking.at["a", "status"] == "slots full"


def test_a_top_name_failing_the_cash_hurdle_leaves_its_slot_in_cash():
    """Dual momentum: the slot goes to cash, not to the next name that passes."""
    prices = pd.DataFrame(
        {
            "a": _path([0.10] * 4),                 # rank 1, 12M +49%
            "b": _path([0.40, 0.25, 0.0, -0.50]),   # rank 2, 12M +16%
            "c": _path([0.02, 0.04, 0.06, 0.08]),   # rank 3, 12M +22%
            "d": _path([0.0] * 4),
        },
        index=INDEX,
    )
    target = _build(prices, config=_config(risk_free_rate_annual=0.18))
    ranks = target.ranking["rank"]
    assert (ranks["b"], ranks["c"]) == (2, 3)
    assert target.weights == {"a": 0.5, CASH: 0.5}
    assert target.ranking.at["b", "status"] == "fails cash hurdle"
    assert any("fails the cash hurdle" in n for n in target.notes)


def test_a_holding_that_fails_the_hurdle_is_sold():
    target = _build(prior={"f": 0.5, "a": 0.5}, config=_config(retention_buffer_m=6))
    assert _actions(target)["f"] == SELL  # rank 6 is inside M=6, but 12M +5.2% < 6.5%
    assert "cash hurdle" in next(d.reason for d in target.decisions if d.exposure_id == "f")


def test_without_the_hurdle_a_weak_holding_stays():
    config = _config(retention_buffer_m=6, absolute_momentum_filter="none")
    assert _actions(_build(prior={"f": 0.5, "a": 0.5}, config=config))["f"] == HOLD


def test_an_exposure_without_a_vehicle_is_not_eligible_when_investable_is_required():
    meta = _meta(SIX, a=ExposureMeta("a", "A", "sector", None), b=ExposureMeta("b", "B", "sector", AS_OF + pd.Timedelta(days=1)))
    target = _build(meta=meta)
    assert target.holdings == ("c", "d")
    assert target.ranking.at["a", "status"] == "no buyable vehicle on this date"
    assert pd.isna(target.ranking.at["a", "rank"])
    signal_only = _build(meta=meta, config=_config(require_investable=False))
    assert signal_only.holdings == ("a", "b")


def test_a_holding_that_loses_its_vehicle_is_sold():
    meta = _meta(SIX, a=ExposureMeta("a", "A", "sector", None))
    target = _build(prior={"a": 0.5, "b": 0.5}, meta=meta)
    assert _actions(target)["a"] == SELL
    assert "No longer buyable" in next(d.reason for d in target.decisions if d.exposure_id == "a")


def test_raising_n_trims_existing_holdings():
    config = _config(target_holdings_n=4, retention_buffer_m=8)
    target = _build(prior={"a": 0.5, "b": 0.5}, config=config)
    actions = _actions(target)
    assert actions["a"] == TRIM and actions["b"] == TRIM
    assert target.weights["a"] == 0.25


def test_lowering_n_keeps_the_best_ranked_holdings():
    third = 1 / 3
    target = _build(prior={"a": third, "b": third, "c": third})
    assert target.holdings == ("a", "b")
    assert _actions(target) == {"a": BUY, "b": BUY, "c": SELL}  # 1/3 -> 1/2 is a raise


def test_nothing_eligible_means_all_cash():
    target = _build(meta={})
    assert target.weights == {CASH: 1.0}
    assert target.eligible_count == 0


def test_equal_scores_break_ties_on_exposure_id():
    twins = pd.DataFrame({"zeta": SIX["a"], "alpha": SIX["a"], "c": SIX["c"]}, index=INDEX)
    target = _build(twins, config=_config(target_holdings_n=1, retention_buffer_m=1))
    assert target.holdings == ("alpha",)


def test_the_decision_ignores_prices_after_its_date():
    when = INDEX[-30]
    full = _build(prior={"c": 0.5, "d": 0.5}, when=when)
    cut = _build(SIX.loc[:when], prior={"c": 0.5, "d": 0.5}, when=when)
    assert full.to_json() == cut.to_json()


def test_the_canonical_json_is_valid_and_deterministic():
    a, b = _build(prior={"d": 0.5, "e": 0.5}), _build(prior={"d": 0.5, "e": 0.5})
    assert a.to_json() == b.to_json()
    payload = json.loads(a.to_json())
    assert payload["weights"] == {"a": 0.5, "d": 0.5}
    assert payload["config_hash"] == load_strategy_config().config_hash


def test_the_decision_chain_feeds_each_target_into_the_next():
    dates = list(pd.DatetimeIndex(["2026-06-30", "2026-07-31", "2026-08-31"]))
    chain = decision_chain(SIX, _meta(SIX), _config(), dates)
    assert len(chain) == 3
    replay = construct_target_portfolio(dates[2], SIX, _meta(SIX), chain[1].weights, _config())
    assert replay.to_json() == chain[2].to_json()


# --------------------------------------------------------------------------- #
# Calendar and universe metadata
# --------------------------------------------------------------------------- #
def test_the_fill_is_the_session_after_the_signal():
    index = pd.bdate_range("2026-09-28", "2026-10-06")
    assert fill_date(index, pd.Timestamp("2026-09-30")) == pd.Timestamp("2026-10-01")
    assert fill_date(index, index[-1]) is None


def test_the_next_rebalance_is_the_coming_month_end():
    assert next_rebalance_date(pd.Timestamp("2026-10-09")) == pd.Timestamp("2026-10-30")
    assert next_rebalance_date(pd.Timestamp("2026-10-30")) == pd.Timestamp("2026-11-30")


def test_investability_is_point_in_time_from_vehicle_prices():
    """A fund that launched in 2026 must not be buyable in 2022."""
    index = pd.bdate_range("2021-01-01", "2026-08-31")
    vehicles = pd.DataFrame(
        {"NEW": pd.Series(1.0, index=index).where(index >= "2026-01-01"), "OLD": 1.0}, index=index
    )
    universe = pd.DataFrame(
        [{"exposure_id": "a", "symbol": "NEW", "name": "New ETF"},
         {"exposure_id": "b", "symbol": "OLD", "name": "Old ETF"},
         {"exposure_id": "c", "symbol": None, "name": "No History Fund"}]
    )
    meta = build_universe_metadata(["a", "b", "c"], universe, vehicles)
    assert meta["a"].investable_from == pd.Timestamp("2026-01-01")
    assert not meta["a"].investable_on(pd.Timestamp("2022-06-30"))
    assert meta["b"].investable_on(pd.Timestamp("2022-06-30"))
    assert meta["c"].investable_from is None
