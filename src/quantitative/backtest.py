"""Walk-forward backtest of the strategy the dashboard shows.

Every selection and weighting decision is made by
``src.portfolio.construct.construct_target_portfolio`` through
``decision_chain`` — the same chain that produces the live target — so the
backtest has no rules of its own to drift out of sync. This module only does
the accounting:

* **Signal at t, fill at t+1.** A decision formed at the month-end close is
  executed at the next session's close (``execution_fill: t_plus_1_close``).
  The old portfolio earns the session in between, and each period runs from
  one fill to the next.
* **Costs.** ``cost_bps_per_side`` is charged on every unit of weight bought
  or sold (cash legs are free): ``cost = bps x sum_i |w_i - w_prior_i|``,
  deducted at the fill.
* **Cash** earns what the configured liquid fund's NAV returned between the two
  fills — the same series as the cash hurdle. The constant rate is used only
  for periods that start before the fund's NAV history.
* **Only completed months are periods.** The current, unfinished month is not
  a rebalance date unless ``include_partial`` asks for it, and annualisation
  uses the trading sessions actually covered.
* **Turnover** is ``0.5 * sum(|w_t - w_{t-1}|)`` over every holding *and*
  cash, against the previous target.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import numpy as np
import pandas as pd

from src.config import StrategyConfig, load_strategy_config
from src.portfolio.calendar import fill_date, month_is_complete, rebalance_dates
from src.portfolio.cash import period_return
from src.portfolio.construct import CASH, TargetPortfolio, decision_chain
from src.portfolio.score import FFILL_LIMIT
from src.portfolio.universe import ExposureMeta

__all__ = [
    "CASH",
    "BacktestResult",
    "month_is_complete",
    "period_split",
    "rebalance_dates",
    "rolling_summary_stats",
    "rolling_windows",
    "run_backtest",
    "traded_weight",
    "turnover",
    "weight_sensitivity",
]

TRADING_DAYS = 252
MIN_WINDOW_MONTHS = 12


@dataclass
class BacktestResult:
    monthly: pd.DataFrame = field(default_factory=pd.DataFrame)
    equity: pd.DataFrame = field(default_factory=pd.DataFrame)
    stats: dict[str, float] = field(default_factory=dict)
    universe_size: pd.Series = field(default_factory=lambda: pd.Series(dtype=int))
    decisions: list[TargetPortfolio] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and not self.monthly.empty

    @property
    def final_target(self) -> TargetPortfolio | None:
        """The latest decision: what the strategy holds from its next fill onwards."""
        return self.decisions[-1] if self.decisions else None


def turnover(previous: Mapping[str, float], current: Mapping[str, float]) -> float:
    """One-way turnover, ``0.5 * sum(|w_t - w_{t-1}|)``, with cash as a position.

    {A, B} -> {A, cash} sells half the book: 0.5.
    """
    keys = set(previous) | set(current)
    return 0.5 * sum(abs(current.get(k, 0.0) - previous.get(k, 0.0)) for k in keys)


def traded_weight(previous: Mapping[str, float], current: Mapping[str, float]) -> float:
    """Weight bought plus weight sold, cash leg excluded: what costs are charged on."""
    keys = (set(previous) | set(current)) - {CASH}
    return sum(abs(current.get(k, 0.0) - previous.get(k, 0.0)) for k in keys)


def _passed_over(target: TargetPortfolio, depth: int) -> str:
    ranking = target.ranking
    if ranking.empty or "rank" not in ranking:
        return ""
    held = set(target.holdings)
    ranked = ranking[ranking["rank"].notna()]
    ranked = ranked[ranked["rank"].astype(int) <= depth]
    parts = [f"{e}:{status}" for e, status in zip(ranked.index, ranked["status"]) if e not in held]
    return "; ".join(parts[:4])


def run_backtest(
    prices: pd.DataFrame,
    benchmark: pd.Series,
    config: StrategyConfig | None = None,
    universe_metadata: Mapping[str, ExposureMeta] | None = None,
    months: int | None = None,
    include_partial: bool = False,
    cash_nav: pd.Series | None = None,
) -> BacktestResult:
    """Replay the strategy over the panel and account for what it would have earned.

    ``months`` limits the history window; ``None`` uses every completed month,
    which is what the live portfolio does. When ``config.require_investable``
    is set, ``universe_metadata`` says from when each exposure was buyable; an
    exposure absent from it never is.
    """
    config = config or load_strategy_config()
    hold_months = int(config.rebalance_months)
    if months is not None and months < MIN_WINDOW_MONTHS:
        return BacktestResult(error=f"The backtest window must be at least {MIN_WINDOW_MONTHS} months.")
    if prices is None or prices.empty or benchmark is None or benchmark.dropna().empty:
        return BacktestResult(error="No canonical index price panel is available.")

    prices = prices.sort_index()
    benchmark = benchmark.dropna().sort_index()
    common = prices.index.intersection(benchmark.index)
    prices, benchmark = prices.loc[common], benchmark.loc[common]
    if prices.empty:
        return BacktestResult(error="No canonical index price panel is available.")

    dates = rebalance_dates(prices.index, months, hold_months, include_partial=include_partial)
    periods_needed = max(MIN_WINDOW_MONTHS // hold_months, 1)
    if len(dates) < periods_needed + 1:
        return BacktestResult(
            error=(
                f"Only {max(len(dates) - 1, 0)} complete {hold_months}-month periods of "
                f"overlapping history are available; {periods_needed} are required."
            )
        )

    chain = decision_chain(prices, universe_metadata, config, dates, cash_nav=cash_nav)
    marks = prices.ffill(limit=FFILL_LIMIT)
    index = prices.index
    last_session = pd.Timestamp(index[-1])
    rate = float(config.risk_free_rate_annual)
    bps = float(config.cost_bps_per_side) / 1e4

    rows: list[dict[str, object]] = []
    universe: dict[pd.Timestamp, int] = {}
    prior: Mapping[str, float] = {CASH: 1.0}
    for k, target in enumerate(chain):
        signal = pd.Timestamp(dates[k])
        universe[signal] = target.eligible_count
        weights = target.weights
        period_turnover = turnover(prior, weights)
        cost = bps * traded_weight(prior, weights)
        prior = weights
        if target.eligible_count == 0 or k + 1 >= len(chain):
            # Warm-up (nothing has a full 12-month history yet), or the latest
            # decision, whose holding period has not run yet.
            continue

        start = fill_date(index, signal)
        end = fill_date(index, pd.Timestamp(dates[k + 1]))
        partial = False
        if end is None and include_partial:
            end, partial = last_session, True
        if start is None or end is None or end <= start:
            continue

        period_years = (end - start).days / 365.25 if partial else hold_months / 12.0
        cash_return, cash_source = period_return(cash_nav, start, end, rate, period_years)
        realised: dict[str, float] = {}
        missing: list[str] = []
        for exposure_id in target.holdings:
            a, b = marks.at[start, exposure_id], marks.at[end, exposure_id]
            if pd.isna(a) or pd.isna(b) or a <= 0:
                missing.append(exposure_id)
                realised[exposure_id] = 0.0
            else:
                realised[exposure_id] = float(b / a - 1.0)
        cash_weight = float(weights.get(CASH, 0.0))
        gross = sum(weights[e] * r for e, r in realised.items()) + cash_weight * cash_return
        net = (1.0 - cost) * (1.0 + gross) - 1.0
        bench_start, bench_end = benchmark.at[start], benchmark.at[end]
        benchmark_return = float(bench_end / bench_start - 1.0) if bench_start > 0 else np.nan
        skipped = _passed_over(target, int(config.retention_buffer_m))
        if missing:
            skipped = "; ".join(filter(None, [skipped, *(f"{e}:no price at fill" for e in missing)]))

        rows.append(
            {
                "rebalance": signal,
                "fill_date": start,
                "period_end": end,
                "holdings": ", ".join(target.holdings) if target.holdings else "cash",
                "n_held": len(target.holdings),
                "cash_weight": cash_weight,
                "cash_slots": int(round(cash_weight * config.target_holdings_n)),
                "cash_return": cash_return,
                "cash_source": cash_source,
                "gross_return": gross,
                "cost": cost,
                "strategy_return": net,
                "benchmark_return": benchmark_return,
                "excess_return": net - benchmark_return,
                "turnover": period_turnover,
                "universe": target.eligible_count,
                "skipped": skipped,
                **{f"holding_{i + 1}": name for i, name in enumerate(realised)},
                **{f"holding_{i + 1}_return": value for i, value in enumerate(realised.values())},
            }
        )

    monthly = pd.DataFrame(rows)
    if monthly.empty:
        return BacktestResult(error="No period produced a valid holding.", decisions=chain)

    # The curve starts at the first fill, not at the start of the warm-up year
    # in which nothing could be held.
    equity = pd.DataFrame(
        {
            "date": [monthly["fill_date"].iloc[0]] + monthly["period_end"].tolist(),
            "strategy": np.concatenate([[100.0], 100.0 * (1 + monthly["strategy_return"]).cumprod()]),
            "benchmark": np.concatenate(
                [[100.0], 100.0 * (1 + monthly["benchmark_return"]).cumprod()]
            ),
        }
    ).set_index("date")

    first = pd.Timestamp(monthly["fill_date"].iloc[0])
    last = pd.Timestamp(monthly["period_end"].iloc[-1])
    sessions = int(((index > first) & (index <= last)).sum())
    stats = _stats(monthly, equity, hold_months, sessions=sessions, risk_free=rate)
    requested = float(months) if months is not None else float((len(dates) - 1) * hold_months)
    stats["requested_months"] = requested
    stats["warmup_months"] = float(max(requested - stats["months"], 0.0))
    stats["cash_rate"] = rate
    stats["cost_bps_per_side"] = float(config.cost_bps_per_side)
    stats["gross_total_return"] = float((1 + monthly["gross_return"]).prod() - 1.0)
    stats["total_cost"] = float(monthly["cost"].sum())
    return BacktestResult(
        monthly=monthly,
        equity=equity,
        stats=stats,
        universe_size=pd.Series(universe).sort_index(),
        decisions=chain,
    )


def _max_drawdown(curve: pd.Series) -> float:
    return float((curve / curve.cummax() - 1.0).min())


def _sharpe(growth: float, volatility: float, risk_free: float) -> float:
    if not np.isfinite(growth) or not np.isfinite(volatility) or volatility <= 0:
        return float("nan")
    return float((growth - risk_free) / volatility)


def _stats(
    monthly: pd.DataFrame,
    equity: pd.DataFrame,
    hold_months: int = 1,
    sessions: int | None = None,
    risk_free: float = 0.065,
) -> dict[str, float]:
    """Summary statistics over the periods that actually held something.

    CAGR is annualised by the trading sessions covered (``sessions / 252``)
    rather than by counting periods. Sharpe is ``(CAGR - rf) / annualised
    volatility``, the same definition as ``analytics.sharpe``.
    """
    strategy = monthly["strategy_return"].astype(float)
    benchmark = monthly["benchmark_return"].astype(float)
    n = len(strategy)
    periods_per_year = 12.0 / max(hold_months, 1)
    years = sessions / TRADING_DAYS if sessions else n / periods_per_year
    total_s = float(equity["strategy"].iloc[-1] / 100.0 - 1.0)
    total_b = float(equity["benchmark"].iloc[-1] / 100.0 - 1.0)
    vol_s = float(strategy.std(ddof=0) * np.sqrt(periods_per_year)) if n > 1 else float("nan")
    vol_b = float(benchmark.std(ddof=0) * np.sqrt(periods_per_year)) if n > 1 else float("nan")
    cagr_s = float((1 + total_s) ** (1 / years) - 1) if years > 0 and total_s > -1 else float("nan")
    cagr_b = float((1 + total_b) ** (1 / years) - 1) if years > 0 and total_b > -1 else float("nan")
    return {
        "periods": float(n),
        "months": float(n * max(hold_months, 1)),
        "hold_months": float(hold_months),
        "total_return": total_s,
        "benchmark_total_return": total_b,
        "excess_total": total_s - total_b,
        "cagr": cagr_s,
        "benchmark_cagr": cagr_b,
        "volatility": vol_s,
        "benchmark_volatility": vol_b,
        "sharpe": _sharpe(cagr_s, vol_s, risk_free),
        "benchmark_sharpe": _sharpe(cagr_b, vol_b, risk_free),
        "risk_free": float(risk_free),
        "sessions": float(sessions or 0),
        "years": float(years),
        "max_drawdown": _max_drawdown(equity["strategy"]),
        "benchmark_max_drawdown": _max_drawdown(equity["benchmark"]),
        "hit_rate": float((strategy > benchmark).mean()),
        "win_rate": float((strategy > 0).mean()),
        "best_month": float(strategy.max()),
        "worst_month": float(strategy.min()),
        "avg_turnover": float(monthly["turnover"].mean()),
        "cash_months": float((monthly["cash_weight"] > 0).sum()),
    }


def period_split(result: BacktestResult, boundary: str = "2025-01-01") -> pd.DataFrame:
    """Split the record either side of a date and compound each half.

    A single headline figure hides the thing that matters most here: the early
    years had almost nothing to buy, so a poor blended number can describe a
    strategy that was mostly in cash rather than one that was wrong.
    """
    if not result.ok:
        return pd.DataFrame()
    frame = result.monthly.copy()
    cut = pd.Timestamp(boundary)
    frame["half"] = np.where(pd.to_datetime(frame["period_end"]) < cut, "early", "recent")
    rows = []
    for label, group in frame.groupby("half", sort=False):
        if group.empty:
            continue
        strategy = float((1 + group["strategy_return"]).prod() - 1)
        bench = float((1 + group["benchmark_return"]).prod() - 1)
        rows.append(
            {
                "half": label,
                "from": pd.to_datetime(group["period_end"]).min(),
                "to": pd.to_datetime(group["period_end"]).max(),
                "periods": int(len(group)),
                "strategy": strategy,
                "benchmark": bench,
                "excess": strategy - bench,
                "cash_periods": float((group["cash_weight"] > 0).mean()),
                "avg_universe": float(group["universe"].mean()),
            }
        )
    order = {"early": 0, "recent": 1}
    return pd.DataFrame(rows).sort_values("half", key=lambda s: s.map(order), ignore_index=True)


def weight_sensitivity(
    prices: pd.DataFrame,
    benchmark: pd.Series,
    schemes: Mapping[str, StrategyConfig],
    universe_metadata: Mapping[str, ExposureMeta] | None = None,
    months: int | None = None,
    cash_nav: pd.Series | None = None,
) -> pd.DataFrame:
    """Run the same test under several score specifications.

    If the answer swings wildly across reasonable choices, the result is a
    property of the parameter rather than of the strategy — and picking the
    best row is fitting noise. This exists to make that visible, not to choose.
    """
    rows = []
    for label, config in schemes.items():
        result = run_backtest(prices, benchmark, config, universe_metadata, months=months, cash_nav=cash_nav)
        if not result.ok:
            continue
        rows.append(
            {
                "weighting": label,
                "total_return": result.stats["total_return"],
                "excess": result.stats["excess_total"],
                "max_drawdown": result.stats["max_drawdown"],
                "hit_rate": result.stats["hit_rate"],
                "turnover": result.stats["avg_turnover"],
            }
        )
    return pd.DataFrame(rows)


def rolling_windows(result: BacktestResult, window: int = 12) -> pd.DataFrame:
    """Compound every overlapping ``window``-period stretch of the record.

    One 48-month number depends entirely on when the test started and stopped.
    The distribution of every 12-month window inside it says how often the
    strategy actually worked.
    """
    if not result.ok or len(result.monthly) < window:
        return pd.DataFrame()
    frame = result.monthly.reset_index(drop=True)
    rows = []
    for start in range(len(frame) - window + 1):
        chunk = frame.iloc[start:start + window]
        strategy = float((1 + chunk["strategy_return"]).prod() - 1)
        bench = float((1 + chunk["benchmark_return"]).prod() - 1)
        rows.append(
            {
                "start": pd.to_datetime(chunk["rebalance"].iloc[0]),
                "end": pd.to_datetime(chunk["period_end"].iloc[-1]),
                "strategy": strategy,
                "benchmark": bench,
                "excess": strategy - bench,
                "cash_periods": float((chunk["cash_weight"] > 0).mean()),
            }
        )
    return pd.DataFrame(rows)


def rolling_summary_stats(windows: pd.DataFrame) -> dict[str, float]:
    """Distribution of the rolling windows: how often, not just how much."""
    if windows is None or windows.empty:
        return {}
    excess = windows["excess"].astype(float)
    strategy = windows["strategy"].astype(float)
    return {
        "windows": float(len(windows)),
        "beat_rate": float((excess > 0).mean()),
        "positive_rate": float((strategy > 0).mean()),
        "median_excess": float(excess.median()),
        "best_excess": float(excess.max()),
        "worst_excess": float(excess.min()),
        "median_strategy": float(strategy.median()),
        "worst_strategy": float(strategy.min()),
    }
