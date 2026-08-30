"""Monthly rotation backtest against Nifty 50.

Deliberate design choices, because a backtest that flatters itself is worse
than none at all:

* Ranking at each rebalance date uses ``rank_exposures`` — the *same* function
  the live dashboard uses — over a price slice that ends on that date. There is
  no separate research implementation to drift out of sync, and no future data
  in the ranking.
* An exposure is only selectable if every lookback window it is scored on is
  fully populated at that date. Otherwise a freshly launched index would be
  ranked on 1-month momentum alone and compared against names scored on four
  horizons.
* The holding period return is measured from the rebalance close to the next
  rebalance close, so the decision and the return it earns never overlap.
* Cash earns 0%. No T-bill yield is assumed, which understates the absolute-
  momentum variant slightly rather than overstating it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.quantitative.ranking import rank_exposures
from src.quantitative.returns import LOOKBACK_DAYS

TRADING_DAYS = 252
MIN_WINDOW_MONTHS = 12


@dataclass
class BacktestResult:
    monthly: pd.DataFrame = field(default_factory=pd.DataFrame)
    equity: pd.DataFrame = field(default_factory=pd.DataFrame)
    stats: dict[str, float] = field(default_factory=dict)
    universe_size: pd.Series = field(default_factory=lambda: pd.Series(dtype=int))
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and not self.monthly.empty


def rebalance_dates(index: pd.DatetimeIndex, months: int) -> list[pd.Timestamp]:
    """Last available trading day of each month, covering ``months`` + 1 points."""
    if len(index) == 0:
        return []
    frame = pd.Series(index, index=index)
    month_ends = frame.groupby([index.year, index.month]).max().sort_values()
    dates = list(pd.DatetimeIndex(month_ends.to_numpy()))
    return dates[-(months + 1):] if len(dates) > months else dates


def _eligible(prices: pd.DataFrame, asof: pd.Timestamp) -> list[str]:
    """Exposures with enough history at ``asof`` to be scored on every lookback."""
    needed = max(LOOKBACK_DAYS.values())
    window = prices.loc[:asof]
    return [column for column in window.columns if window[column].dropna().size > needed]


def run_backtest(
    prices: pd.DataFrame,
    benchmark: pd.Series,
    top_n: int = 2,
    months: int = 12,
    absolute_filter: bool = True,
    absolute_lookback: str = "12M",
) -> BacktestResult:
    """Rank monthly, hold the top ``top_n`` exposures equally weighted."""
    if months < MIN_WINDOW_MONTHS:
        return BacktestResult(error=f"The backtest window must be at least {MIN_WINDOW_MONTHS} months.")
    if prices is None or prices.empty or benchmark is None or benchmark.dropna().empty:
        return BacktestResult(error="No canonical index price panel is available.")

    prices = prices.sort_index()
    benchmark = benchmark.dropna().sort_index()
    common = prices.index.intersection(benchmark.index)
    prices, benchmark = prices.loc[common], benchmark.loc[common]

    dates = rebalance_dates(prices.index, months)
    if len(dates) < MIN_WINDOW_MONTHS + 1:
        return BacktestResult(
            error=(
                f"Only {max(len(dates) - 1, 0)} complete months of overlapping history are "
                f"available; {MIN_WINDOW_MONTHS} are required."
            )
        )

    absolute_days = LOOKBACK_DAYS.get(absolute_lookback, LOOKBACK_DAYS["12M"])
    rows: list[dict[str, object]] = []
    universe: dict[pd.Timestamp, int] = {}
    previous: set[str] = set()

    for start, end in zip(dates[:-1], dates[1:]):
        candidates = _eligible(prices, start)
        universe[start] = len(candidates)
        if not candidates:
            continue

        window = prices.loc[:start, candidates]
        ranked = rank_exposures(window, benchmark.loc[:start])
        ranked = ranked[ranked["momentum_z"].notna()].sort_values("momentum_z", ascending=False)

        picks: list[str] = []
        for exposure_id in ranked.index:
            if len(picks) >= top_n:
                break
            series = prices[exposure_id].loc[:start].dropna()
            if absolute_filter:
                if len(series) <= absolute_days:
                    continue
                trailing = series.iloc[-1] / series.iloc[-absolute_days - 1] - 1.0
                if trailing <= 0:
                    continue
            picks.append(str(exposure_id))

        held = prices.loc[[start, end], picks] if picks else pd.DataFrame()
        realised = {}
        for exposure_id in picks:
            values = held[exposure_id]
            if values.isna().any() or values.iloc[0] <= 0:
                continue
            realised[exposure_id] = float(values.iloc[1] / values.iloc[0] - 1.0)

        cash_slots = top_n - len(realised)
        gross = sum(realised.values())
        strategy_return = gross / top_n if top_n else 0.0

        bench_start, bench_end = benchmark.loc[start], benchmark.loc[end]
        benchmark_return = float(bench_end / bench_start - 1.0) if bench_start > 0 else np.nan

        current = set(realised)
        rows.append(
            {
                "rebalance": start,
                "period_end": end,
                "holdings": ", ".join(realised) if realised else "cash",
                "n_held": len(realised),
                "cash_slots": cash_slots,
                "strategy_return": strategy_return,
                "benchmark_return": benchmark_return,
                "excess_return": strategy_return - benchmark_return,
                "turnover": len(current ^ previous) / (2 * top_n) if top_n else 0.0,
                "universe": len(candidates),
                **{f"holding_{i + 1}": name for i, name in enumerate(realised)},
                **{f"holding_{i + 1}_return": value for i, value in enumerate(realised.values())},
            }
        )
        previous = current

    monthly = pd.DataFrame(rows)
    if monthly.empty:
        return BacktestResult(error="No month produced a valid holding period.")

    equity = pd.DataFrame(
        {
            "date": [dates[0]] + monthly["period_end"].tolist(),
            "strategy": np.concatenate([[100.0], 100.0 * (1 + monthly["strategy_return"]).cumprod()]),
            "benchmark": np.concatenate(
                [[100.0], 100.0 * (1 + monthly["benchmark_return"]).cumprod()]
            ),
        }
    ).set_index("date")

    return BacktestResult(
        monthly=monthly,
        equity=equity,
        stats=_stats(monthly, equity),
        universe_size=pd.Series(universe).sort_index(),
    )


def _max_drawdown(curve: pd.Series) -> float:
    return float((curve / curve.cummax() - 1.0).min())


def _stats(monthly: pd.DataFrame, equity: pd.DataFrame) -> dict[str, float]:
    strategy = monthly["strategy_return"].astype(float)
    benchmark = monthly["benchmark_return"].astype(float)
    n = len(strategy)
    years = n / 12.0
    total_s = float(equity["strategy"].iloc[-1] / 100.0 - 1.0)
    total_b = float(equity["benchmark"].iloc[-1] / 100.0 - 1.0)
    vol_s = float(strategy.std(ddof=0) * np.sqrt(12)) if n > 1 else float("nan")
    vol_b = float(benchmark.std(ddof=0) * np.sqrt(12)) if n > 1 else float("nan")
    cagr_s = float((1 + total_s) ** (1 / years) - 1) if years > 0 and total_s > -1 else float("nan")
    cagr_b = float((1 + total_b) ** (1 / years) - 1) if years > 0 and total_b > -1 else float("nan")
    return {
        "months": float(n),
        "total_return": total_s,
        "benchmark_total_return": total_b,
        "excess_total": total_s - total_b,
        "cagr": cagr_s,
        "benchmark_cagr": cagr_b,
        "volatility": vol_s,
        "benchmark_volatility": vol_b,
        "sharpe": float(cagr_s / vol_s) if vol_s and vol_s == vol_s and vol_s > 0 else float("nan"),
        "max_drawdown": _max_drawdown(equity["strategy"]),
        "benchmark_max_drawdown": _max_drawdown(equity["benchmark"]),
        "hit_rate": float((strategy > benchmark).mean()),
        "win_rate": float((strategy > 0).mean()),
        "best_month": float(strategy.max()),
        "worst_month": float(strategy.min()),
        "avg_turnover": float(monthly["turnover"].mean()),
        "cash_months": float((monthly["cash_slots"] > 0).sum()),
    }
