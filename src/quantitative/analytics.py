"""Scheme and exposure analytics: rolling returns, risk, alpha, consistency.

Point-to-point returns are the weakest way to judge a series — they depend
entirely on two dates. Everything here is either distributional (rolling
windows) or risk-adjusted, so a sector that led once is not confused with one
that leads reliably.

Two levels are computed:

* **Exposure** against Nifty 50 — is this sector's strength durable, and is it
  strength or just beta?
* **Vehicle** against the index it tracks — tracking difference and error,
  which is how you choose between two funds on the same index.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252

# Sharpe and Sortino need a risk-free rate. This is an assumption, not data:
# roughly the Indian short-term sovereign yield. It is stated wherever the
# ratios are displayed so a reader can discount it.
RISK_FREE_ANNUAL = 0.065

WINDOWS = {"1Y": 1, "3Y": 3, "5Y": 5}


def repair_level_shifts(series: pd.Series, passes: int = 4) -> pd.Series:
    """Undo split/unit-change discontinuities before any return is computed.

    An ETF that does a 10:1 unit split shows a 90% one-day fall in raw traded
    prices. Left unrepaired it reads as a -40%/yr tracking difference against
    an index that did nothing of the sort. Only persistent level shifts of
    >=2.5x or <=0.4x are corrected — far outside normal daily equity moves.
    """
    import math

    clean = pd.to_numeric(series, errors="coerce").dropna().astype(float).sort_index()
    if len(clean) < 25:
        return clean
    for _ in range(passes):
        values = clean.to_numpy(copy=True)
        changed = False
        for i in range(10, len(values) - 10):
            previous, current = float(values[i - 1]), float(values[i])
            if previous <= 0 or current <= 0:
                continue
            day_ratio = current / previous
            pre = float(pd.Series(values[i - 10:i]).median())
            post = float(pd.Series(values[i:i + 10]).median())
            if pre <= 0:
                continue
            level_ratio = post / pre
            if not (level_ratio >= 2.5 or level_ratio <= 0.4):
                continue
            if abs(math.log(day_ratio / level_ratio)) > 0.18:
                continue
            clean.iloc[:i] *= level_ratio
            changed = True
            break
        if not changed:
            break
    return clean


def _clean(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").dropna().sort_index()


def _daily_returns(series: pd.Series) -> pd.Series:
    return _clean(series).pct_change(fill_method=None).dropna()


# --------------------------------------------------------------------------- #
# returns
# --------------------------------------------------------------------------- #
def cagr(series: pd.Series, years: float | None = None) -> float:
    values = _clean(series)
    if len(values) < 2 or values.iloc[0] <= 0:
        return float("nan")
    span = years if years else (values.index[-1] - values.index[0]).days / 365.25
    if span <= 0:
        return float("nan")
    return float((values.iloc[-1] / values.iloc[0]) ** (1 / span) - 1)


def rolling_cagr(series: pd.Series, years: int) -> pd.Series:
    """CAGR of every rolling window of ``years``, stepped daily."""
    values = _clean(series)
    window = int(years * TRADING_DAYS)
    if len(values) <= window:
        return pd.Series(dtype=float)
    ratio = values / values.shift(window)
    return (ratio ** (1 / years) - 1).dropna()


def rolling_summary(series: pd.Series, years: int) -> dict[str, float]:
    """Distribution of rolling returns: the honest way to read a track record."""
    roll = rolling_cagr(series, years)
    if roll.empty:
        return {k: float("nan") for k in ("current", "median", "mean", "min", "max", "n", "positive")}
    return {
        "current": float(roll.iloc[-1]),
        "median": float(roll.median()),
        "mean": float(roll.mean()),
        "min": float(roll.min()),
        "max": float(roll.max()),
        "n": float(len(roll)),
        "positive": float((roll > 0).mean()),
    }


# --------------------------------------------------------------------------- #
# risk
# --------------------------------------------------------------------------- #
def annualised_volatility(series: pd.Series) -> float:
    returns = _daily_returns(series)
    return float(returns.std(ddof=0) * np.sqrt(TRADING_DAYS)) if len(returns) > 1 else float("nan")


def sharpe(series: pd.Series, risk_free: float = RISK_FREE_ANNUAL) -> float:
    growth, vol = cagr(series), annualised_volatility(series)
    if not np.isfinite(growth) or not np.isfinite(vol) or vol <= 0:
        return float("nan")
    return float((growth - risk_free) / vol)


def sortino(series: pd.Series, risk_free: float = RISK_FREE_ANNUAL) -> float:
    """Like Sharpe, but only downside deviation is treated as risk."""
    returns = _daily_returns(series)
    if len(returns) < 2:
        return float("nan")
    daily_target = (1 + risk_free) ** (1 / TRADING_DAYS) - 1
    downside = (returns - daily_target).clip(upper=0)
    deviation = float(np.sqrt((downside**2).mean()) * np.sqrt(TRADING_DAYS))
    growth = cagr(series)
    if deviation <= 0 or not np.isfinite(growth):
        return float("nan")
    return float((growth - risk_free) / deviation)


def max_drawdown(series: pd.Series) -> dict[str, object]:
    values = _clean(series)
    if values.empty:
        return {"depth": float("nan"), "peak": None, "trough": None,
                "days": float("nan"), "current": float("nan")}
    drawdown = values / values.cummax() - 1.0
    trough = drawdown.idxmin()
    peak = values.loc[:trough].idxmax()
    return {
        "depth": float(drawdown.min()),
        "peak": peak,
        "trough": trough,
        "days": float((trough - peak).days),
        "current": float(drawdown.iloc[-1]),
    }


# --------------------------------------------------------------------------- #
# versus a benchmark
# --------------------------------------------------------------------------- #
def _aligned(series: pd.Series, benchmark: pd.Series) -> tuple[pd.Series, pd.Series]:
    frame = pd.concat([_clean(series).rename("a"), _clean(benchmark).rename("b")], axis=1).dropna()
    return frame["a"], frame["b"]


def alpha_beta(series: pd.Series, benchmark: pd.Series,
               risk_free: float = RISK_FREE_ANNUAL) -> dict[str, float]:
    """Annualised Jensen's alpha, beta, and R² against the benchmark.

    Beta near 1 with a high R² means the exposure is the market in disguise;
    the interesting sectors are the ones whose alpha survives their beta.
    """
    a, b = _aligned(series, benchmark)
    ra, rb = a.pct_change(fill_method=None).dropna(), b.pct_change(fill_method=None).dropna()
    joined = pd.concat([ra.rename("a"), rb.rename("b")], axis=1).dropna()
    if len(joined) < 30:
        return {"alpha": float("nan"), "beta": float("nan"), "r2": float("nan")}
    var = joined["b"].var(ddof=0)
    if var <= 0:
        return {"alpha": float("nan"), "beta": float("nan"), "r2": float("nan")}
    beta = float(joined["a"].cov(joined["b"], ddof=0) / var)
    corr = float(joined["a"].corr(joined["b"]))
    growth_a, growth_b = cagr(a), cagr(b)
    alpha = (
        float(growth_a - (risk_free + beta * (growth_b - risk_free)))
        if np.isfinite(growth_a) and np.isfinite(growth_b)
        else float("nan")
    )
    return {"alpha": alpha, "beta": beta, "r2": float(corr**2) if np.isfinite(corr) else float("nan")}


def tracking(series: pd.Series, benchmark: pd.Series) -> dict[str, float]:
    """Tracking difference and tracking error — how to pick between two funds.

    Difference is what the holder actually gave up per year; error is how
    erratically they gave it up. A fund can have a small error and still bleed
    a consistent 80bps, which is the difference that matters.
    """
    a, b = _aligned(series, benchmark)
    if len(a) < 30:
        return {"difference": float("nan"), "error": float("nan"), "years": float("nan")}
    ra = a.pct_change(fill_method=None).dropna()
    rb = b.pct_change(fill_method=None).dropna()
    active = (ra - rb).dropna()
    years = (a.index[-1] - a.index[0]).days / 365.25
    return {
        "difference": float(cagr(a) - cagr(b)),
        "error": float(active.std(ddof=0) * np.sqrt(TRADING_DAYS)),
        "years": float(years),
    }


def information_ratio(series: pd.Series, benchmark: pd.Series) -> float:
    stats = tracking(series, benchmark)
    if not np.isfinite(stats["error"]) or stats["error"] <= 0:
        return float("nan")
    return float(stats["difference"] / stats["error"])


def outperformance_consistency(series: pd.Series, benchmark: pd.Series, years: int = 1) -> dict[str, float]:
    """Share of rolling windows that beat the benchmark, split by market direction.

    A sector that only wins when the market rises is a leveraged bet on the
    market. One that also holds up when the benchmark falls is doing something
    of its own. That split is invisible in a single hit-rate.
    """
    a, b = _aligned(series, benchmark)
    ra, rb = rolling_cagr(a, years), rolling_cagr(b, years)
    joined = pd.concat([ra.rename("a"), rb.rename("b")], axis=1).dropna()
    if joined.empty:
        return {"overall": float("nan"), "upside": float("nan"), "downside": float("nan"),
                "n": 0.0, "n_up": 0.0, "n_down": 0.0}
    wins = joined["a"] > joined["b"]
    up, down = joined["b"] > 0, joined["b"] <= 0
    return {
        "overall": float(wins.mean()),
        "upside": float(wins[up].mean()) if up.any() else float("nan"),
        "downside": float(wins[down].mean()) if down.any() else float("nan"),
        "n": float(len(joined)),
        "n_up": float(up.sum()),
        "n_down": float(down.sum()),
    }


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #
@dataclass
class ExposureAnalytics:
    rolling: dict[str, dict[str, float]]
    risk: dict[str, dict[str, float]]
    drawdown: dict[str, object]
    versus: dict[str, float]
    consistency: dict[str, dict[str, float]]


def _tail_years(series: pd.Series, years: int) -> pd.Series:
    values = _clean(series)
    if values.empty:
        return values
    cutoff = values.index[-1] - pd.DateOffset(years=years)
    return values.loc[values.index >= cutoff]


def analyse_exposure(series: pd.Series, benchmark: pd.Series) -> ExposureAnalytics:
    """Everything the detail view needs for one exposure, in one pass."""
    risk = {}
    for label, years in WINDOWS.items():
        window = _tail_years(series, years)
        risk[label] = {
            "return": cagr(window),
            "volatility": annualised_volatility(window),
            "sharpe": sharpe(window),
            "sortino": sortino(window),
        }
    return ExposureAnalytics(
        rolling={f"{y}Y": rolling_summary(series, y) for y in (1, 3)},
        risk=risk,
        drawdown=max_drawdown(series),
        versus={**alpha_beta(series, benchmark), **tracking(series, benchmark),
                "information_ratio": information_ratio(series, benchmark)},
        consistency={f"{y}Y": outperformance_consistency(series, benchmark, y) for y in (1, 3)},
    )


def vehicle_tracking_table(
    prices: pd.DataFrame, vehicles: pd.DataFrame, index_series: pd.Series
) -> pd.DataFrame:
    """Tracking difference and error for every vehicle against its own index."""
    rows = []
    for row in vehicles.to_dict("records"):
        key = row.get("symbol") or row.get("name")
        if key not in getattr(prices, "columns", []):
            continue
        # Repair splits first: an unadjusted unit change would otherwise read as
        # a catastrophic tracking difference.
        stats = tracking(repair_level_shifts(prices[key]), index_series)
        rows.append({
            "symbol": row.get("symbol"),
            "name": row.get("name"),
            "vehicle": row.get("vehicle", "etf"),
            "tracking_difference": stats["difference"],
            "tracking_error": stats["error"],
            "history_years": stats["years"],
        })
    return pd.DataFrame(rows)
