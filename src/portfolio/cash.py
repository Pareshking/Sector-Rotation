"""Cash returns from the liquid fund's NAV, with the constant as the only fallback.

The cash hurdle and the return on unallocated capital are the same number:
what a liquid fund actually paid. The configured constant (6.5%) is used only
for dates before the fund's NAV history begins, never to paper over a gap.
"""

from __future__ import annotations

import pandas as pd

NAV = "nav"
CONSTANT = "constant"


def _nav_on_or_before(nav: pd.Series, when: pd.Timestamp) -> float | None:
    upto = nav.loc[: pd.Timestamp(when)]
    return float(upto.iloc[-1]) if len(upto) else None


def covers(nav: pd.Series | None, start: pd.Timestamp) -> bool:
    """Whether the NAV history already existed on ``start``."""
    return nav is not None and not nav.dropna().empty and pd.Timestamp(start) >= nav.dropna().index.min()


def period_return(
    nav: pd.Series | None, start: pd.Timestamp, end: pd.Timestamp, fallback_annual: float, years: float
) -> tuple[float, str]:
    """Cash return from ``start`` to ``end``: NAV ratio if the fund existed at ``start``.

    ``years`` is the period length the constant fallback compounds over.
    """
    if covers(nav, start):
        clean = nav.dropna()
        a, b = _nav_on_or_before(clean, start), _nav_on_or_before(clean, end)
        if a and b and a > 0:
            return b / a - 1.0, NAV
    return (1.0 + fallback_annual) ** years - 1.0, CONSTANT


def trailing_12m(nav: pd.Series | None, as_of: pd.Timestamp, fallback_annual: float) -> tuple[float, str]:
    """The 12-month cash return to ``as_of``: the hurdle an exposure must beat."""
    as_of = pd.Timestamp(as_of)
    start = as_of - pd.DateOffset(years=1)
    if covers(nav, start):
        return period_return(nav, start, as_of, fallback_annual, 1.0)
    return float(fallback_annual), CONSTANT
