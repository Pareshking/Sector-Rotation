"""The live target portfolio is the backtest's final holding, byte for byte.

Both come from ``construct_target_portfolio`` through ``decision_chain``. These
tests pin the three ways that could silently stop being true:

1. the backtest and the live path run different chains (different start,
   different priors, different config);
2. a decision reads data after its date, so the live call on a snapshot that
   ends at the decision differs from the backtest's call on the full panel;
3. one of the consumers (dashboard, alert tool) builds its target some other way.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.config import load_strategy_config
from src.portfolio.construct import HOLD, construct_target_portfolio
from src.portfolio.live import live_portfolio, live_portfolio_from_artifacts
from src.portfolio.universe import ExposureMeta, build_universe_metadata
from src.quantitative.backtest import run_backtest

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"


def _market(seed: int = 11, columns: int = 12, days: int = 1100):
    """Random-walk sector panel ending mid-month, so the current month is unfinished."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range(end=pd.Timestamp("2026-10-09"), periods=days)
    drift = rng.normal(0.0004, 0.0004, columns)
    vol = rng.uniform(0.008, 0.02, columns)
    prices = pd.DataFrame(
        {f"x{i:02d}": 100 * np.exp(np.cumsum(rng.normal(drift[i], vol[i], days))) for i in range(columns)},
        index=index,
    )
    benchmark = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.008, days))), index=index)
    # Funds arrive over time, as they did in India: a third investable from the
    # start, the rest launching across the window, two never.
    launches = list(index[[0] * 4 + [300, 450, 600, 700, 800, 900]]) + [None, None]
    meta = {
        e: ExposureMeta(e, e.upper(), "sector", launches[i])
        for i, e in enumerate(prices.columns)
    }
    return prices, benchmark, meta


@pytest.fixture(scope="module")
def synthetic():
    prices, benchmark, meta = _market()
    config = load_strategy_config()
    result = run_backtest(prices, benchmark, config, meta)
    live = live_portfolio(prices, meta, config)
    return prices, benchmark, meta, config, result, live


def test_the_backtest_final_holdings_equal_the_live_target_byte_for_byte(synthetic):
    _, _, _, _, result, live = synthetic
    assert result.ok and live is not None
    assert result.final_target.as_of == live.target.as_of
    assert result.final_target.to_json() == live.target.to_json()
    assert result.final_target.holdings == live.target.holdings


def test_construct_on_the_decision_date_snapshot_reproduces_it(synthetic):
    """A one-off call on prices that end at the decision close, with the chain's prior."""
    prices, _, meta, config, result, live = synthetic
    as_of = live.target.as_of
    snapshot = prices.loc[:as_of]
    assert snapshot.index.max() == as_of < prices.index.max()  # data runs past the decision
    prior = result.decisions[-2].weights
    direct = construct_target_portfolio(as_of, snapshot, meta, prior, config)
    assert direct.to_json() == live.target.to_json()


def test_the_live_target_does_not_depend_on_data_after_the_decision(synthetic):
    prices, _, meta, config, _, live = synthetic
    truncated = live_portfolio(prices.loc[: live.target.as_of], meta, config)
    assert truncated.target.to_json() == live.target.to_json()


def test_the_last_completed_period_held_the_previous_decision(synthetic):
    _, _, _, _, result, _ = synthetic
    previous = result.decisions[-2]
    last_row = result.monthly.iloc[-1]
    assert pd.Timestamp(last_row["rebalance"]) == previous.as_of
    assert last_row["holdings"] == (", ".join(previous.holdings) or "cash")


def test_the_scenario_exercises_the_retention_buffer(synthetic):
    """Parity is only meaningful if path dependence actually occurs."""
    _, _, _, config, result, _ = synthetic
    retained_below_entry = [
        d for target in result.decisions for d in target.decisions
        if d.action == HOLD and d.rank is not None and d.rank > config.target_holdings_n
    ]
    assert retained_below_entry
    assert any(target.eligible_count < 12 for target in result.decisions if target.eligible_count)


def test_parity_holds_for_every_decision_in_the_chain(synthetic):
    """Not just the last one: each live-style snapshot call matches the chain."""
    prices, _, meta, config, result, _ = synthetic
    prior = {"__cash__": 1.0}
    for target in result.decisions:
        direct = construct_target_portfolio(target.as_of, prices.loc[: target.as_of], meta, prior, config)
        assert direct.to_json() == target.to_json()
        prior = target.weights


# --------------------------------------------------------------------------- #
# The published dataset: every consumer produces the same target
# --------------------------------------------------------------------------- #
needs_data = pytest.mark.skipif(
    not (PROCESSED / "index_prices.parquet").exists(), reason="no published dataset"
)


@pytest.fixture(scope="module")
def published():
    panel = pd.read_parquet(PROCESSED / "index_prices.parquet")
    benchmark = panel.pop("__benchmark__")
    etfs = pd.read_parquet(PROCESSED / "etf_universe.parquet")
    etf_prices = pd.read_parquet(PROCESSED / "etf_prices.parquet")
    meta = build_universe_metadata(panel.columns, etfs, etf_prices)
    config = load_strategy_config()
    result = run_backtest(panel, benchmark, config, meta)
    return panel, etfs, etf_prices, meta, config, result


@needs_data
def test_on_the_published_data_the_backtest_and_live_target_agree(published):
    panel, etfs, etf_prices, meta, config, result = published
    live = live_portfolio_from_artifacts(
        panel.assign(__benchmark__=1.0), etfs, etf_prices, config=config
    )
    assert result.ok
    assert result.final_target.to_json() == live.target.to_json()
    as_of = live.target.as_of
    direct = construct_target_portfolio(as_of, panel.loc[:as_of], meta, result.decisions[-2].weights, config)
    assert direct.to_json() == live.target.to_json()


@needs_data
def test_the_alert_tool_builds_the_same_target(published):
    import tools.detect_alerts as alerts_tool

    _, _, _, _, _, result = published
    current = alerts_tool.portfolio_from(alerts_tool._working, {})
    assert current.target.to_json() == result.final_target.to_json()


@needs_data
def test_the_dashboard_holds_exactly_the_backtest_final_holdings(published):
    import app.data as app_data
    from app.components.metrics import HELD_ACTIONS

    _, _, _, _, _, result = published
    live = app_data.load_portfolio()
    assert live.target.holdings == result.final_target.holdings
    assert dict(live.target.weights) == dict(result.final_target.weights)
    decisions = app_data.load_decisions()
    held = decisions[decisions.model_action.isin(HELD_ACTIONS)]
    assert sorted(held.exposure_id) == sorted(result.final_target.holdings)
    weights = dict(zip(held.exposure_id, held.target_weight))
    assert weights == {e: result.final_target.weights[e] for e in result.final_target.holdings}
