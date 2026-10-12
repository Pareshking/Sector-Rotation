"""Market regime for display: is the benchmark beating cash over the last year?

Context only. The strategy has no market-level switch; its cash hurdle is
applied to each exposure separately (``construct.py``). The regime answers the
reader's first question — is the tide going in or out — with the same two
series the hurdle uses: Nifty 50 TRI against the liquid fund.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.config import FULL_HISTORY_SESSIONS
from src.portfolio.cash import trailing_12m

RISK_ON = "RISK-ON"
RISK_OFF = "RISK-OFF"


@dataclass(frozen=True)
class Regime:
    label: str
    as_of: pd.Timestamp
    benchmark_12m: float
    cash_12m: float
    cash_source: str

    @property
    def spread(self) -> float:
        return self.benchmark_12m - self.cash_12m


def market_regime(
    benchmark: pd.Series, cash_nav: pd.Series | None, fallback_annual: float, as_of=None
) -> Regime | None:
    """RISK-ON when Nifty 50 TRI's 12-month return beats cash's over the same year.

    The benchmark's 12 months are the same 252 sessions an exposure's 12-month
    return uses; cash is the liquid fund's NAV, or the constant before it.
    """
    series = pd.to_numeric(benchmark, errors="coerce").dropna().sort_index()
    if as_of is not None:
        series = series.loc[: pd.Timestamp(as_of)]
    if len(series) <= FULL_HISTORY_SESSIONS:
        return None
    when = pd.Timestamp(series.index[-1])
    bench = float(series.iloc[-1] / series.iloc[-1 - FULL_HISTORY_SESSIONS] - 1.0)
    cash, source = trailing_12m(cash_nav, when, fallback_annual)
    return Regime(RISK_ON if bench > cash else RISK_OFF, when, bench, float(cash), source)
