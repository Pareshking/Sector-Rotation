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
from src.quantitative.relative_strength import mansfield_relative_strength, rs_momentum, rs_stage
from src.quantitative.returns import LOOKBACK_DAYS

TRADING_DAYS = 252
MIN_WINDOW_MONTHS = 12
# How far down the ranking a substitution may reach when the top name cannot be
# bought. Beyond this the slot goes to cash rather than drifting into names the
# model never actually favoured.
DEFAULT_RANK_DEPTH = 3


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


def rebalance_dates(index: pd.DatetimeIndex, months: int, hold_months: int = 1) -> list[pd.Timestamp]:
    """Period boundaries: the last trading day of every ``hold_months``-th month.

    ``months`` is the length of the test; ``hold_months`` is how long a decision
    is left alone before it is revisited.
    """
    if len(index) == 0:
        return []
    frame = pd.Series(index, index=index)
    month_ends = frame.groupby([index.year, index.month]).max().sort_values()
    dates = list(pd.DatetimeIndex(month_ends.to_numpy()))
    window = dates[-(months + 1):] if len(dates) > months else dates
    hold = max(int(hold_months), 1)
    if hold == 1:
        return window
    # Step backwards from the most recent month end so the final period is whole.
    stepped = window[::-1][::hold][::-1]
    return stepped


def signal_panel(prices: pd.DataFrame, benchmark: pd.Series) -> dict[str, pd.DataFrame]:
    """Mansfield RS ratio and velocity for every date, per exposure.

    Both inputs are backward-looking by construction — a 52-week rolling mean
    and a 13-week difference — so reading row ``t`` uses only data available on
    day ``t``. Computing the series once and indexing into it is point-in-time
    safe and far cheaper than recomputing at every rebalance.
    """
    out: dict[str, pd.DataFrame] = {}
    for column in prices.columns:
        mrs = mansfield_relative_strength(prices[column], benchmark)
        if mrs.dropna().empty:
            continue
        frame = pd.DataFrame({"ratio": 1.0 + mrs / 100.0, "velocity": rs_momentum(mrs)}).dropna()
        if not frame.empty:
            out[column] = frame
    return out


def _signal_at(panel: dict[str, pd.DataFrame], exposure_id: str, asof: pd.Timestamp):
    frame = panel.get(exposure_id)
    if frame is None:
        return None
    window = frame.loc[:asof]
    if window.empty:
        return None
    row = window.iloc[-1]
    return float(row["ratio"]), float(row["velocity"])


def investable_from(
    vehicle_prices: pd.DataFrame, vehicles_by_exposure: dict[str, list[str]] | None
) -> dict[str, pd.Timestamp]:
    """First date each exposure had a vehicle you could actually have bought.

    Investability is judged from the vehicle's own price history, not from the
    fact that it exists today. Most of these ETFs and index funds launched in
    2024-25; treating them as available in 2021 would be look-ahead of the worst
    kind — the backtest would buy instruments that did not exist yet.
    """
    starts: dict[str, pd.Timestamp] = {}
    if vehicle_prices is None or vehicle_prices.empty:
        return starts
    for exposure_id, keys in (vehicles_by_exposure or {}).items():
        firsts = [
            vehicle_prices[key].dropna().index.min()
            for key in keys
            if key in vehicle_prices.columns and not vehicle_prices[key].dropna().empty
        ]
        if firsts:
            starts[str(exposure_id)] = min(firsts)
    return starts


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
    hold_months: int = 1,
    absolute_filter: bool = True,
    absolute_lookback: str = "12M",
    investable_only: bool = False,
    require_buy: bool = False,
    max_rank_depth: int = DEFAULT_RANK_DEPTH,
    vehicle_prices: pd.DataFrame | None = None,
    vehicles_by_exposure: dict[str, list[str]] | None = None,
    weights: dict[str, float] | None = None,
) -> BacktestResult:
    """Rank periodically, hold the top ``top_n`` exposures equally weighted.

    ``investable_only`` restricts each pick to exposures that had a buyable
    vehicle *on that date*, judged from the vehicle's own price history rather
    than from the fact that it exists today. ``require_buy`` additionally
    demands the exposure satisfy the live BUY rule. When a top-ranked name
    fails either test the next one is taken, but never past ``max_rank_depth``
    — beyond that the slot goes to cash rather than drifting into names the
    model never favoured.
    """
    hold_months = max(int(hold_months), 1)
    if months < MIN_WINDOW_MONTHS:
        return BacktestResult(error=f"The backtest window must be at least {MIN_WINDOW_MONTHS} months.")
    if prices is None or prices.empty or benchmark is None or benchmark.dropna().empty:
        return BacktestResult(error="No canonical index price panel is available.")

    prices = prices.sort_index()
    benchmark = benchmark.dropna().sort_index()
    common = prices.index.intersection(benchmark.index)
    prices, benchmark = prices.loc[common], benchmark.loc[common]

    dates = rebalance_dates(prices.index, months, hold_months)
    periods_needed = max(MIN_WINDOW_MONTHS // hold_months, 1)
    if len(dates) < periods_needed + 1:
        return BacktestResult(
            error=(
                f"Only {max(len(dates) - 1, 0)} complete {hold_months}-month periods of "
                f"overlapping history are available; {periods_needed} are required."
            )
        )

    signals = signal_panel(prices, benchmark) if require_buy else {}
    starts = (
        investable_from(vehicle_prices, vehicles_by_exposure) if investable_only else {}
    )
    absolute_days = LOOKBACK_DAYS.get(absolute_lookback, LOOKBACK_DAYS["12M"])
    # The depth cap exists so a name the model never favoured cannot be bought
    # just because everything above it was unbuyable. It applies only to the
    # constrained modes; plain full-universe scanning is unbounded, as before.
    constrained = investable_only or require_buy
    depth = max(int(max_rank_depth), int(top_n)) if constrained else len(prices.columns)

    rows: list[dict[str, object]] = []
    universe: dict[pd.Timestamp, int] = {}
    previous: set[str] = set()

    for start, end in zip(dates[:-1], dates[1:]):
        candidates = _eligible(prices, start)
        universe[start] = len(candidates)
        if not candidates:
            continue

        window = prices.loc[:start, candidates]
        ranked = rank_exposures(window, benchmark.loc[:start], weights=weights)
        ranked = ranked[ranked["momentum_z"].notna()].sort_values("momentum_z", ascending=False)

        picks: list[str] = []
        skipped: list[str] = []
        for position, exposure_id in enumerate(ranked.index, start=1):
            if len(picks) >= top_n or position > depth:
                break
            exposure_id = str(exposure_id)
            series = prices[exposure_id].loc[:start].dropna()

            if investable_only:
                first = starts.get(exposure_id)
                if first is None or first > start:
                    skipped.append(f"{exposure_id}:no vehicle")
                    continue

            if require_buy:
                signal = _signal_at(signals, exposure_id, start)
                if signal is None:
                    skipped.append(f"{exposure_id}:no signal")
                    continue
                ratio, velocity = signal
                stage = rs_stage(ratio, velocity)
                if not (stage == "Leading" and ratio > 1.0 and velocity > 0):
                    skipped.append(f"{exposure_id}:not BUY")
                    continue

            if absolute_filter:
                if len(series) <= absolute_days:
                    skipped.append(f"{exposure_id}:short history")
                    continue
                trailing = series.iloc[-1] / series.iloc[-absolute_days - 1] - 1.0
                if trailing <= 0:
                    skipped.append(f"{exposure_id}:negative absolute")
                    continue

            picks.append(exposure_id)

        held = prices.loc[[start, end], picks] if picks else pd.DataFrame()
        realised = {}
        for exposure_id in picks:
            values = held[exposure_id]
            if values.isna().any() or values.iloc[0] <= 0:
                continue
            realised[exposure_id] = float(values.iloc[1] / values.iloc[0] - 1.0)

        cash_slots = top_n - len(realised)
        strategy_return = sum(realised.values()) / top_n if top_n else 0.0

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
                "skipped": "; ".join(skipped[:4]),
                **{f"holding_{i + 1}": name for i, name in enumerate(realised)},
                **{f"holding_{i + 1}_return": value for i, value in enumerate(realised.values())},
            }
        )
        previous = current

    monthly = pd.DataFrame(rows)
    if monthly.empty:
        return BacktestResult(error="No period produced a valid holding.")

    equity = pd.DataFrame(
        {
            "date": [dates[0]] + monthly["period_end"].tolist(),
            "strategy": np.concatenate([[100.0], 100.0 * (1 + monthly["strategy_return"]).cumprod()]),
            "benchmark": np.concatenate(
                [[100.0], 100.0 * (1 + monthly["benchmark_return"]).cumprod()]
            ),
        }
    ).set_index("date")

    stats = _stats(monthly, equity, hold_months)
    stats["requested_months"] = float(months)
    # The first rebalances produce nothing: no exposure has the 252 days of
    # history the ranking needs, so the window's opening year is warm-up.
    stats["warmup_months"] = float(max(months - stats["months"], 0.0))
    return BacktestResult(
        monthly=monthly,
        equity=equity,
        stats=stats,
        universe_size=pd.Series(universe).sort_index(),
    )


def _max_drawdown(curve: pd.Series) -> float:
    return float((curve / curve.cummax() - 1.0).min())


def _stats(monthly: pd.DataFrame, equity: pd.DataFrame, hold_months: int = 1) -> dict[str, float]:
    strategy = monthly["strategy_return"].astype(float)
    benchmark = monthly["benchmark_return"].astype(float)
    n = len(strategy)
    periods_per_year = 12.0 / max(hold_months, 1)
    years = n / periods_per_year
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
                "cash_periods": float((group["cash_slots"] > 0).mean()),
                "avg_universe": float(group["universe"].mean()),
            }
        )
    order = {"early": 0, "recent": 1}
    return pd.DataFrame(rows).sort_values("half", key=lambda s: s.map(order), ignore_index=True)


def weight_sensitivity(
    prices: pd.DataFrame,
    benchmark: pd.Series,
    schemes: dict[str, dict[str, float]],
    **kwargs,
) -> pd.DataFrame:
    """Run the same test under several weightings.

    If the answer swings wildly across reasonable weightings, the result is a
    property of the parameter rather than of the strategy — and picking the best
    row is fitting noise. This exists to make that visible, not to choose.
    """
    rows = []
    for label, weights in schemes.items():
        result = run_backtest(prices, benchmark, weights=weights, **kwargs)
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
    strategy actually worked — the same treatment the Durability panel gives an
    exposure, applied to the strategy itself.
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
                "cash_periods": float((chunk["cash_slots"] > 0).mean()),
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
