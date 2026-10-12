"""The NSE trading-session calendar, derived from the benchmark series.

NSE publishes no machine-readable holiday calendar this project reads, but the
Nifty 50 total-return series has a value on exactly the sessions the exchange
traded. Every other series is checked against it: an index that skips a
session the benchmark has is missing data, not observing a holiday.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class TradingCalendar:
    sessions: pd.DatetimeIndex

    def __post_init__(self) -> None:
        clean = pd.DatetimeIndex(self.sessions).normalize().unique().sort_values()
        object.__setattr__(self, "sessions", clean)

    @classmethod
    def from_series(cls, series: pd.Series | pd.DataFrame) -> "TradingCalendar":
        """Sessions on which ``series`` has a value (the benchmark, in practice)."""
        frame = series.to_frame() if isinstance(series, pd.Series) else series
        return cls(frame.dropna(how="all").index)

    def __len__(self) -> int:
        return len(self.sessions)

    @property
    def first(self) -> pd.Timestamp | None:
        return self.sessions[0] if len(self.sessions) else None

    @property
    def last(self) -> pd.Timestamp | None:
        return self.sessions[-1] if len(self.sessions) else None

    def is_session(self, when) -> bool:
        return pd.Timestamp(when).normalize() in self.sessions

    def next_session(self, when) -> pd.Timestamp | None:
        """The first session strictly after ``when``: where a t+1 fill happens."""
        pos = self.sessions.searchsorted(pd.Timestamp(when).normalize(), side="right")
        return self.sessions[pos] if pos < len(self.sessions) else None

    def previous_session(self, when) -> pd.Timestamp | None:
        """The last session strictly before ``when``."""
        pos = self.sessions.searchsorted(pd.Timestamp(when).normalize(), side="left")
        return self.sessions[pos - 1] if pos > 0 else None

    def session_on_or_before(self, when) -> pd.Timestamp | None:
        pos = self.sessions.searchsorted(pd.Timestamp(when).normalize(), side="right")
        return self.sessions[pos - 1] if pos > 0 else None

    def sessions_back(self, when, count: int) -> pd.Timestamp | None:
        """The session ``count`` sessions before the last session on or before ``when``."""
        anchor = self.session_on_or_before(when)
        if anchor is None:
            return None
        pos = self.sessions.get_loc(anchor) - int(count)
        return self.sessions[max(pos, 0)]

    def between(self, start=None, end=None) -> pd.DatetimeIndex:
        """Sessions in ``[start, end]``, either bound optional."""
        mask = pd.Series(True, index=self.sessions)
        if start is not None:
            mask &= self.sessions >= pd.Timestamp(start).normalize()
        if end is not None:
            mask &= self.sessions <= pd.Timestamp(end).normalize()
        return self.sessions[mask.to_numpy()]

    def missing(self, series: pd.Series, start=None, end=None) -> pd.DatetimeIndex:
        """Expected sessions with no value in ``series``.

        Counted from the later of ``start`` and the series' first value, so an
        index launched inside the window is not missing the years before it.
        """
        values = series.dropna()
        if values.empty:
            return self.between(start, end)
        first = values.index.min()
        lower = max(pd.Timestamp(start), first) if start is not None else first
        expected = self.between(lower, end)
        return expected[~expected.isin(values.index.normalize())]
