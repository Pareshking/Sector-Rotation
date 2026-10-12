"""The current target portfolio: the end of the strategy's own decision chain.

Called by the dashboard and the alert tool with the published data. It runs
the same ``decision_chain`` the backtest runs, over every completed month in
the data, and returns the last decision — so the dashboard always shows the
portfolio the backtest says the strategy holds.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.config import StrategyConfig, load_strategy_config
from src.portfolio.calendar import next_rebalance_date, rebalance_dates
from src.portfolio.construct import TargetPortfolio, decision_chain
from src.portfolio.universe import ExposureMeta, build_universe_metadata


@dataclass(frozen=True)
class LivePortfolio:
    target: TargetPortfolio
    previous: TargetPortfolio | None
    data_as_of: pd.Timestamp
    next_rebalance: pd.Timestamp


def strategy_signal_dates(price_history: pd.DataFrame, config: StrategyConfig) -> list[pd.Timestamp]:
    """Every completed rebalance date in the data: the live chain runs from the first."""
    return rebalance_dates(price_history.index, months=None, hold_months=config.rebalance_months)


def live_portfolio(
    price_history: pd.DataFrame,
    universe_metadata: dict[str, ExposureMeta] | None,
    config: StrategyConfig | None = None,
) -> LivePortfolio | None:
    config = config or load_strategy_config()
    if price_history is None or price_history.empty:
        return None
    dates = strategy_signal_dates(price_history, config)
    if not dates:
        return None
    chain = decision_chain(price_history, universe_metadata, config, dates)
    last_session = pd.Timestamp(price_history.index.max())
    return LivePortfolio(
        target=chain[-1],
        previous=chain[-2] if len(chain) > 1 else None,
        data_as_of=last_session,
        next_rebalance=next_rebalance_date(last_session, config.rebalance_months),
    )


def live_portfolio_from_artifacts(
    index_panel: pd.DataFrame,
    etf_universe: pd.DataFrame | None,
    etf_prices: pd.DataFrame | None,
    names: dict[str, str] | None = None,
    categories: dict[str, str] | None = None,
    config: StrategyConfig | None = None,
) -> LivePortfolio | None:
    """``live_portfolio`` from the published parquet files (benchmark column dropped)."""
    panel = index_panel.drop(columns=["__benchmark__"], errors="ignore")
    meta = build_universe_metadata(panel.columns, etf_universe, etf_prices, names, categories)
    return live_portfolio(panel, meta, config)
