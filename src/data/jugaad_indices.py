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
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Callable, Mapping

import pandas as pd
import requests

import src.data._jugaad_patches  # noqa: F401 — timeout + wider date-chunking, side effects only
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
    calendar: pd.DatetimeIndex | None = None,
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
    if len(values) < MIN_OBSERVATIONS:
        return [f"only {len(values)} observations (need {MIN_OBSERVATIONS})"]
    problems: list[str] = []
    gaps = values.index.to_series().diff().dt.days
    for when, days in gaps[gaps > MAX_SESSION_GAP_DAYS].items():
        problems.append(f"{int(days)}-day hole ending {when.date()}")
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
    calendar: pd.DatetimeIndex | None,
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
            problems = completeness_problems(series, start, end, calendar)
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
    calendar: pd.DatetimeIndex | None = None,
) -> pd.Series:
    """Fetch one NSE index history. Total-return series preferred, price close accepted.

    ``series.attrs['value_type']`` records which of the two was actually served.
    When neither endpoint yields a complete series the result is empty and
    ``attrs['errors']`` says why, per endpoint.
    """
    errors: list[str] = []
    endpoints = (
        (VALUE_TRI, lambda: index_tri_raw(name, name, start, end)),
        (VALUE_CLOSE, lambda: index_raw(name, start, end)),
    )
    for value_type, fetch in endpoints:
        series, reason = _fetch_validated(f"{name} [{value_type}]", fetch, start, end, calendar)
        if series is not None:
            series = series.rename(name)
            series.attrs.update(source=SOURCE, resolved_name=name, value_type=value_type)
            return series
        errors.append(f"{value_type}: {reason}")
    empty = pd.Series(dtype="float64", name=name)
    empty.attrs["errors"] = errors
    return empty


def fetch_jugaad_canonical_indices(
    exposure_names: Mapping[str, str],
    years: int = 5,
    workers: int = 4,
    calendar: pd.DatetimeIndex | None = None,
) -> tuple[pd.DataFrame, dict[str, str], dict[str, str], dict[str, str]]:
    """Return (prices, source_by_exposure, resolved_name_by_exposure, value_type_by_exposure).

    ``prices.attrs['fetch_errors']`` maps every exposure that did not resolve to
    the reason, so a missing series is explained rather than just absent.
    """
    start = date.today() - timedelta(days=365 * years + 10)
    results: dict[str, pd.Series] = {}
    sources: dict[str, str] = {}
    resolved: dict[str, str] = {}
    value_types: dict[str, str] = {}
    errors: dict[str, str] = {}
    t0 = time.time()
    total = len(exposure_names)
    print(f"[{time.strftime('%H:%M:%S')}] Canonical indices: fetching {total}...", file=sys.stderr, flush=True)

    def one(item):
        eid, name = item
        return eid, name, fetch_jugaad_index(name, start, date.today(), calendar=calendar)

    done = 0
    with ThreadPoolExecutor(max_workers=min(workers, max(len(exposure_names), 1))) as pool:
        futures = {pool.submit(one, item): item for item in exposure_names.items()}
        for future in as_completed(futures):
            done += 1
            eid, name = futures[future]
            try:
                _, _, series = future.result()
            except Exception as exc:
                logger.exception("Canonical index %s (%s) failed", eid, name)
                errors[eid] = f"{type(exc).__name__}: {exc}"
                continue
            if len(series) >= MIN_OBSERVATIONS:
                results[eid] = series.rename(eid)
                sources[eid] = series.attrs.get("source", SOURCE)
                resolved[eid] = series.attrs.get("resolved_name", name)
                value_types[eid] = series.attrs.get("value_type", VALUE_CLOSE)
            else:
                errors[eid] = "; ".join(series.attrs.get("errors", [])) or "no usable history"
            if done % 10 == 0 or done == total:
                print(
                    f"[{time.strftime('%H:%M:%S')}] Canonical indices: {done}/{total} attempted, "
                    f"{len(results)} resolved, {time.time() - t0:.0f}s elapsed",
                    file=sys.stderr,
                    flush=True,
                )

    prices = pd.DataFrame(results).sort_index() if results else pd.DataFrame()
    prices.attrs["fetch_errors"] = errors
    return prices, sources, resolved, value_types


def fetch_benchmark(name: str = "NIFTY 50", years: int = 5) -> pd.Series:
    """Benchmark history from the same adapter as every exposure.

    Using one source for both sides keeps relative returns internally consistent;
    mixing a Yahoo benchmark with NSE exposure histories introduces a calendar
    and dividend-treatment mismatch into every relative number.

    The benchmark *is* the session calendar every exposure is checked against,
    so it is validated on its own terms: no hole longer than any NSE closure,
    and it must start at the beginning of the requested window.
    """
    start = date.today() - timedelta(days=365 * years + 10)
    series = fetch_jugaad_index(name, start, date.today())
    if not series.empty:
        lead = (series.index[0] - pd.Timestamp(start)).days
        if lead > MAX_SESSION_GAP_DAYS:
            logger.error("%s starts %d days after the requested start", name, lead)
            empty = pd.Series(dtype="float64", name=name)
            empty.attrs["errors"] = [f"first observation {series.index[0].date()} is {lead} days late"]
            return empty
    return series
