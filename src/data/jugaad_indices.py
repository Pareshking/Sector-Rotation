"""NSE / NiftyIndices historical index retrieval through the jugaad-data adapter.

Provenance note: jugaad-data is a *retrieval adapter* over NSE's published index
history. It is not itself an authority, and the series it returns is not
automatically a Total Return Index. Each series therefore records which value
type was actually served — ``TRI`` when the total-return endpoint answered, or
``CLOSE`` when only the price-index endpoint did — so the UI can state what a
number is instead of implying total returns everywhere.

A series is only accepted once it is *complete*: every 90-day request chunk
must cover the trading sessions the benchmark calendar says it should. A
request that fails, or a chunk that comes back empty or truncated, is retried
with exponential backoff; what still fails is logged and recorded, never
silently dropped.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import date
from typing import Callable

import pandas as pd
import requests

import src.data._jugaad_patches  # noqa: F401 — timeout + wider date-chunking, side effects only
from src.data.calendar import TradingCalendar
import jugaad_data.util as _jugaad_util
from jugaad_data.nse.history import NSEIndexHistory

logger = logging.getLogger(__name__)

MIN_OBSERVATIONS = 60

SOURCE = "niftyindices_jugaad"
VALUE_TRI = "TRI"
VALUE_CLOSE = "CLOSE"

# Three attempts with 2s, then 4s, between them. NSE failures are usually a
# throttled or dropped connection that clears within seconds; anything longer
# is left to the workflow's 08:30 IST retry run.
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 2.0
# Network failures, timeouts (socket timeouts are OSError) and non-JSON
# responses (NSE serves an HTML block page under throttling; JSONDecodeError is
# a ValueError) are transient. Anything else is a defect and is not retried.
RETRYABLE = (requests.RequestException, OSError, ValueError)
_sleep = time.sleep

# A chunk may miss this many benchmark sessions before it counts as truncated:
# the newest session can lag the benchmark by a day, and NSE occasionally
# omits a single date for one index (Sugar & Ethanol has one such gap today).
CHUNK_MISSING_TOLERANCE = 2
CHUNK_MISSING_SHARE = 0.05
# NSE has never closed for this long. A longer hole inside a series means a
# request chunk is missing, not a holiday.
MAX_SESSION_GAP_DAYS = 10


class IncompleteSeries(ValueError):
    """A downloaded series is missing sessions it should contain."""


# NSE serves dates as "28 Aug 2026". Letting pandas infer the format is not
# safe: with ``dayfirst=True`` and no explicit format, pandas 3.x resolves the
# format from the first row and then returns NaT for every later row whose
# day-of-month is <= 12, because those are ambiguous against a month-first
# reading. That silently deletes roughly 40% of an index history instead of
# raising. Trying explicit formats first removes the ambiguity entirely.
_DATE_FORMATS = ("%d %b %Y", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d")


class _IndexClient(NSEIndexHistory):
    """jugaad's index client with its two per-chunk fetches made safe to share.

    Upstream ``_index`` / ``_index_tri`` store each response on ``self.r`` and
    then parse ``self.r`` — so when two threads use one client, a chunk can be
    parsed from the *other* thread's response. Every index requests the same
    date ranges, so a swapped chunk carries the right dates and another index's
    values, which no completeness check can see. Upstream also pickles every
    chunk to a disk cache, including empty or truncated ones, which would turn
    a retry into a re-read of the same bad chunk. These overrides parse the
    response they received, check the HTTP status, and do not cache.
    """

    def __init__(self) -> None:
        super().__init__()
        # One client per thread already gives the parallelism; chunks of one
        # series are fetched in order on that thread.
        self.workers = 1

    def _chunk(self, path_name: str, name: str, index_name: str, from_date, to_date):
        cinfo = {
            "name": name,
            "startDate": from_date.strftime("%d-%b-%Y"),
            "endDate": to_date.strftime("%d-%b-%Y"),
            "indexName": index_name,
        }
        response = self._post_json(path_name, params={"cinfo": str(cinfo).replace('"', "'")})
        response.raise_for_status()
        return response.json()

    def _index(self, symbol, from_date, to_date):
        return self._chunk("index_history", symbol, symbol, from_date, to_date)

    def _index_tri(self, name, index_name, from_date, to_date):
        return self._chunk("index_tri_history", name, index_name, from_date, to_date)


_local = threading.local()


def _client() -> _IndexClient:
    client = getattr(_local, "client", None)
    if client is None:
        client = _IndexClient()
        _local.client = client
    return client


def index_tri_raw(name, index_name, from_date, to_date):
    return _client().index_tri_raw(name, index_name, from_date, to_date)


def index_raw(symbol, from_date, to_date):
    return _client().index_raw(symbol, from_date, to_date)


def _parse_dates(values: pd.Series) -> pd.Series:
    text = values.astype("string").str.strip()
    best = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    best_hits = 0
    for fmt in _DATE_FORMATS:
        parsed = pd.to_datetime(text, format=fmt, errors="coerce")
        hits = int(parsed.notna().sum())
        if hits > best_hits:
            best, best_hits = parsed, hits
        if best_hits == len(text):
            return best
    if best_hits < len(text):
        inferred = pd.to_datetime(text, errors="coerce", dayfirst=True, format="mixed")
        if int(inferred.notna().sum()) > best_hits:
            return inferred
    return best


def _records_to_series(name: str, records) -> pd.Series:
    if records is None:
        return pd.Series(dtype="float64", name=name)
    if isinstance(records, pd.DataFrame):
        frame = records.copy()
    elif isinstance(records, list):
        frame = pd.DataFrame(records)
    else:
        return pd.Series(dtype="float64", name=name)
    if frame.empty:
        return pd.Series(dtype="float64", name=name)

    date_col = next(
        (c for c in ("HistoricalDate", "Date", "Index Date", "EOD_TIMESTAMP") if c in frame.columns),
        None,
    )
    value_col = next(
        (
            c
            for c in ("TRI", "TotalReturnsIndex", "NTR_Value", "CLOSE", "Close", "Closing Index Value")
            if c in frame.columns
        ),
        None,
    )
    if date_col is None or value_col is None:
        return pd.Series(dtype="float64", name=name)

    dates = _parse_dates(frame[date_col])
    values = pd.to_numeric(
        frame[value_col].astype("string").str.replace(",", "", regex=False), errors="coerce"
    )
    valid = dates.notna() & values.notna() & values.gt(0)
    if not valid.any():
        return pd.Series(dtype="float64", name=name)
    series = pd.Series(
        values.loc[valid].to_numpy(float), index=pd.DatetimeIndex(dates.loc[valid]), name=name
    )
    return series.groupby(level=0).last().sort_index()


def completeness_problems(
    series: pd.Series,
    start: date,
    end: date,
    calendar: pd.DatetimeIndex | TradingCalendar | None = None,
    min_observations: int = MIN_OBSERVATIONS,
) -> list[str]:
    """Why ``series`` is not a complete download of ``start``..``end``; empty when it is.

    Without a calendar only holes longer than any NSE closure are detected.
    With one (the benchmark's sessions), every request chunk — the same
    90-day windows the fetch used — is checked from the series' first
    observation onwards, so a dropped or truncated chunk is caught even when
    it is the newest one. An index that launched inside the window is not
    penalised for the years before its first value.
    """
    values = series.dropna()
    if len(values) < min_observations:
        return [f"only {len(values)} observations (need {min_observations})"]
    problems: list[str] = []
    gaps = values.index.to_series().diff().dt.days
    for when, days in gaps[gaps > MAX_SESSION_GAP_DAYS].items():
        problems.append(f"{int(days)}-day hole ending {when.date()}")
    if isinstance(calendar, TradingCalendar):
        calendar = calendar.sessions
    if calendar is None or len(calendar) == 0:
        return problems

    sessions = pd.DatetimeIndex(calendar).sort_values()
    sessions = sessions[(sessions >= values.index[0]) & (sessions <= pd.Timestamp(end))]
    present = values.index
    for chunk_start, chunk_end in _jugaad_util.break_dates(start, end):
        expected = sessions[
            (sessions >= pd.Timestamp(chunk_start)) & (sessions <= pd.Timestamp(chunk_end))
        ]
        if len(expected) == 0:
            continue
        missing = int((~expected.isin(present)).sum())
        allowed = max(CHUNK_MISSING_TOLERANCE, math.ceil(CHUNK_MISSING_SHARE * len(expected)))
        if missing > allowed:
            problems.append(
                f"chunk {chunk_start}..{chunk_end} has {len(expected) - missing}/{len(expected)} "
                "benchmark sessions"
            )
    return problems


def _fetch_validated(
    label: str,
    fetch: Callable[[], object],
    start: date,
    end: date,
    calendar: pd.DatetimeIndex | TradingCalendar | None,
    min_observations: int = MIN_OBSERVATIONS,
) -> tuple[pd.Series | None, str]:
    """Fetch, parse and validate one endpoint, retrying transient failures.

    Returns ``(series, "")`` on success or ``(None, reason)`` once retries are
    exhausted. Non-retryable exceptions are logged with their traceback and end
    the attempts for this endpoint immediately.
    """
    reason = ""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            series = _records_to_series(label, fetch())
            problems = completeness_problems(series, start, end, calendar, min_observations)
            if problems:
                raise IncompleteSeries("; ".join(problems[:3]))
            return series, ""
        except RETRYABLE as exc:
            reason = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # a defect, not a flaky network: do not retry
            logger.exception("%s: non-retryable failure", label)
            return None, f"{type(exc).__name__}: {exc}"
        if attempt < RETRY_ATTEMPTS:
            delay = RETRY_BASE_DELAY * 2 ** (attempt - 1)
            logger.warning(
                "%s: attempt %d/%d failed (%s); retrying in %.0fs",
                label, attempt, RETRY_ATTEMPTS, reason, delay,
            )
            _sleep(delay)
    logger.error("%s: giving up after %d attempts (%s)", label, RETRY_ATTEMPTS, reason)
    return None, reason


def fetch_jugaad_index(
    name: str,
    start: date,
    end: date,
    calendar: pd.DatetimeIndex | TradingCalendar | None = None,
    value_types: tuple[str, ...] = (VALUE_TRI, VALUE_CLOSE),
    min_observations: int = MIN_OBSERVATIONS,
) -> pd.Series:
    """Fetch one NSE index history. Total-return series preferred, price close accepted.

    ``series.attrs['value_type']`` records which of the two was actually served.
    When neither endpoint yields a complete series the result is empty and
    ``attrs['errors']`` says why, per endpoint.

    An incremental fetch passes the stored series' type alone in
    ``value_types``: falling back to the price index mid-history would splice
    two different series. It also lowers ``min_observations``, since a window
    of a few sessions is complete with a few values.
    """
    errors: list[str] = []
    available = {
        VALUE_TRI: lambda: index_tri_raw(name, name, start, end),
        VALUE_CLOSE: lambda: index_raw(name, start, end),
    }
    endpoints = [(kind, available[kind]) for kind in value_types if kind in available]
    for value_type, fetch in endpoints:
        series, reason = _fetch_validated(
            f"{name} [{value_type}]", fetch, start, end, calendar, min_observations
        )
        if series is not None:
            series = series.rename(name)
            series.attrs.update(source=SOURCE, resolved_name=name, value_type=value_type)
            return series
        errors.append(f"{value_type}: {reason}")
    empty = pd.Series(dtype="float64", name=name)
    empty.attrs["errors"] = errors
    return empty
