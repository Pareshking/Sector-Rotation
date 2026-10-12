"""How much a backtest's Sharpe ratio survives having been chosen among many.

Bailey & López de Prado (2014), "The Deflated Sharpe Ratio": the probability
that the true Sharpe ratio is above zero, after allowing for the highest
Sharpe ratio one would expect to find by luck among ``n_trials`` strategies
with no edge at all, and for the non-normality of the returns.

    SR0 = sqrt(V) * ((1 - g) * Z(1 - 1/N) + g * Z(1 - 1/(N e)))
    DSR = Phi( (SR - SR0) * sqrt(T - 1) / sqrt(1 - skew * SR + (kurt - 1) / 4 * SR^2) )

with ``g`` the Euler-Mascheroni constant and ``V`` the variance of the Sharpe
estimates across trials. That variance is not observed here, so it is set to
``1 / (T - 1)``, the sampling variance of a Sharpe ratio estimated from ``T``
observations when the true Sharpe is zero. Sharpe ratios are per period
(monthly), not annualised.

Standard library only: ``statistics.NormalDist`` gives Phi and its inverse.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import pandas as pd

EULER_GAMMA = 0.5772156649015329
_NORMAL = NormalDist()


@dataclass(frozen=True)
class DeflatedSharpe:
    sharpe: float  # per period
    benchmark_sharpe: float  # SR0: the best Sharpe expected from luck alone
    probabilistic: float  # PSR against zero: no deflation
    deflated: float  # DSR: PSR against SR0
    observations: int
    n_trials: int
    skew: float
    kurtosis: float


def expected_max_sharpe(n_trials: int, variance: float) -> float:
    """The highest Sharpe ratio expected among ``n_trials`` zero-edge strategies."""
    n = max(int(n_trials), 1)
    if n == 1:
        return 0.0
    return math.sqrt(variance) * (
        (1 - EULER_GAMMA) * _NORMAL.inv_cdf(1 - 1 / n)
        + EULER_GAMMA * _NORMAL.inv_cdf(1 - 1 / (n * math.e))
    )


def probabilistic_sharpe(sharpe: float, against: float, observations: int, skew: float, kurtosis: float) -> float:
    """P(true Sharpe > ``against``) given an estimate from ``observations`` periods."""
    denominator = 1 - skew * sharpe + (kurtosis - 1) / 4 * sharpe**2
    if observations < 2 or denominator <= 0:
        return float("nan")
    return _NORMAL.cdf((sharpe - against) * math.sqrt(observations - 1) / math.sqrt(denominator))


def deflated_sharpe(excess_returns: pd.Series, n_trials: int) -> DeflatedSharpe | None:
    """Deflated Sharpe ratio of per-period returns in excess of cash."""
    values = pd.to_numeric(excess_returns, errors="coerce").dropna().astype(float)
    t = len(values)
    std = float(values.std(ddof=1)) if t > 1 else 0.0
    # A constant series has a standard deviation of floating-point noise, not
    # zero, which would turn its Sharpe ratio into ~1e15.
    if t < 3 or std <= 1e-12 * max(1.0, abs(float(values.mean()))):
        return None
    sharpe = float(values.mean() / std)
    skew = float(values.skew())
    kurtosis = float(values.kurt()) + 3.0  # pandas reports excess kurtosis
    sr0 = expected_max_sharpe(n_trials, 1.0 / (t - 1))
    return DeflatedSharpe(
        sharpe=sharpe,
        benchmark_sharpe=sr0,
        probabilistic=probabilistic_sharpe(sharpe, 0.0, t, skew, kurtosis),
        deflated=probabilistic_sharpe(sharpe, sr0, t, skew, kurtosis),
        observations=t,
        n_trials=int(n_trials),
        skew=skew,
        kurtosis=kurtosis,
    )
