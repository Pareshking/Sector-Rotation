"""The current target portfolio: the end of the strategy's own decision chain.

Called by the dashboard, the alert tool and the pipeline with the published
data. It runs the same ``decision_chain`` the backtest runs, over every
completed month in the data, and returns the last decision — so the dashboard
always shows the portfolio the backtest says the strategy holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.config import StrategyConfig, load_strategy_config
from src.portfolio.calendar import next_rebalance_date, rebalance_dates
from src.portfolio.construct import TargetPortfolio, decision_chain
from src.portfolio.universe import ExposureMeta, build_universe_metadata

UNIVERSE_PATH = Path(__file__).resolve().parents[2] / "data" / "universe" / "universe.json"


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
    cash_nav: pd.Series | None = None,
) -> LivePortfolio | None:
    config = config or load_strategy_config()
    if price_history is None or price_history.empty:
        return None
    dates = strategy_signal_dates(price_history, config)
    if not dates:
        return None
    chain = decision_chain(price_history, universe_metadata, config, dates, cash_nav=cash_nav)
    last_session = pd.Timestamp(price_history.index.max())
    return LivePortfolio(
        target=chain[-1],
        previous=chain[-2] if len(chain) > 1 else None,
        data_as_of=last_session,
        next_rebalance=next_rebalance_date(last_session, config.rebalance_months),
    )


def target_frame(target: TargetPortfolio) -> pd.DataFrame:
    """The published ``portfolio_target.parquet``: every order of the decision, plus cash.

    One row per exposure the decision touches (held, bought, trimmed or sold)
    and one ``CASH`` row, so the weights column sums to exactly 1.
    """
    from src.portfolio.construct import CASH

    rows = []
    for decision in target.decisions:
        rows.append(
            {
                "exposure_id": decision.exposure_id,
                "action": decision.action,
                "weight": float(decision.target_weight),
                "prior_weight": float(decision.prior_weight),
                "rank": decision.rank,
                "score": decision.score,
                "reason": decision.reason,
            }
        )
    prior_cash = max(0.0, 1.0 - sum(d.prior_weight for d in target.decisions))
    rows.append(
        {
            "exposure_id": CASH,
            "action": "CASH",
            "weight": float(target.cash_weight),
            "prior_weight": float(prior_cash),
            "rank": None,
            "score": None,
            "reason": "; ".join(target.notes) or "Fully invested.",
        }
    )
    frame = pd.DataFrame(rows)
    frame.insert(0, "as_of", pd.Timestamp(target.as_of))
    frame["rank"] = frame["rank"].astype("Int64")
    frame["score"] = frame["score"].astype(float)
    frame["config_version"] = target.config_version
    frame["config_hash"] = target.config_hash
    frame["cash_hurdle_12m"] = float(target.cash_hurdle_12m)
    frame["cash_hurdle_source"] = target.cash_hurdle_source
    return frame


def cash_series(frame: pd.DataFrame | None) -> pd.Series | None:
    """The ``nav`` column of a published ``cash_nav.parquet`` frame, or None."""
    if frame is None or frame.empty or "nav" not in frame.columns:
        return None
    return frame["nav"].dropna().sort_index()


def load_registry(path: str | Path = UNIVERSE_PATH):
    from src.universe.registry import UniverseRegistry

    return UniverseRegistry.from_json(path)


def live_portfolio_from_artifacts(
    index_panel: pd.DataFrame,
    registry=None,
    cash_nav: pd.Series | None = None,
    names: dict[str, str] | None = None,
    categories: dict[str, str] | None = None,
    config: StrategyConfig | None = None,
) -> LivePortfolio | None:
    """``live_portfolio`` from the published index panel (benchmark column dropped).

    Buyability comes from the registry's authoritative inception dates, never
    from the nightly fund prices.
    """
    panel = index_panel.drop(columns=["__benchmark__"], errors="ignore")
    registry = registry if registry is not None else load_registry()
    meta = build_universe_metadata(panel.columns, registry, names, categories)
    return live_portfolio(panel, meta, config, cash_nav)
