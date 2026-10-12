"""Rebalance and fill dates, shared by the live portfolio and the backtest."""

from __future__ import annotations

import pandas as pd


def month_is_complete(last_session: pd.Timestamp) -> bool:
    """Whether the newest session in the data closes its calendar month.

    True once the data reaches the month's last weekday. When that weekday is
    an NSE holiday the month is treated as unfinished until the next month's
    first session arrives — a day late, never early.
    """
    stamp = pd.Timestamp(last_session).normalize()
    return stamp >= (stamp + pd.offsets.BMonthEnd(0)).normalize()


def rebalance_dates(
    index: pd.DatetimeIndex,
    months: int | None = None,
    hold_months: int = 1,
    include_partial: bool = False,
) -> list[pd.Timestamp]:
    """Signal dates: the last trading day of every ``hold_months``-th month.

    ``months`` limits the window to the most recent ``months`` periods
    (``None`` keeps every month in the data); ``hold_months`` is how long a
    decision is left alone before it is revisited. The newest month counts
    only once it is complete: mid-October, "the October month end" is just the
    latest close, and treating it as one adds a seven-session period that is
    then annualised as a full month. ``include_partial`` keeps it, explicitly.
    """
    if len(index) == 0:
        return []
    frame = pd.Series(index, index=index)
    month_ends = frame.groupby([index.year, index.month]).max().sort_values()
    dates = list(pd.DatetimeIndex(month_ends.to_numpy()))
    if dates and not include_partial and not month_is_complete(dates[-1]):
        dates = dates[:-1]
    window = dates[-(months + 1):] if months is not None and len(dates) > months else dates
    hold = max(int(hold_months), 1)
    if hold == 1:
        return window
    # Step backwards from the most recent month end so the final period is whole.
    return window[::-1][::hold][::-1]


def fill_date(index: pd.DatetimeIndex, signal: pd.Timestamp) -> pd.Timestamp | None:
    """The session a signal formed at the close of ``signal`` is executed (t+1 close)."""
    later = index[index > pd.Timestamp(signal)]
    return pd.Timestamp(later[0]) if len(later) else None


def next_rebalance_date(last_session: pd.Timestamp, hold_months: int = 1) -> pd.Timestamp:
    """The next month end a decision is due, as a weekday (NSE holidays not modelled)."""
    stamp = pd.Timestamp(last_session).normalize()
    this_month_end = (stamp + pd.offsets.BMonthEnd(0)).normalize()
    if stamp < this_month_end:
        return this_month_end
    return (stamp + pd.offsets.BMonthEnd(max(int(hold_months), 1))).normalize()
