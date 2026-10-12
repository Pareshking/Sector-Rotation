"""BSE index history from BSE Index Services (bseindices.com), BSE's own index arm.

Provenance note: BSE Index Services Pvt Ltd (formerly Asia Index) calculates
and publishes every BSE index; ``bseindices.com`` is its site, and the endpoint
used here is the one its index pages chart from. It is the index's owner, not a
third-party mirror.

**Value type.** That endpoint serves the *price* index only. BSE publishes total
return variants (``INSURET``, ``BSHOSPT``) to registered users only, so every
series fetched here is labelled ``CLOSE`` and is never described as total
return. Against the Nifty 50 TRI benchmark a price index understates relative
strength by roughly its dividend yield; the quality checks and the Data Health
page show the label.

A series is accepted only once it is complete against the benchmark calendar,
exactly as for NSE history (``jugaad_indices.completeness_problems``), and the
response must name the BSE index code the universe expects, so a wrong
numeric id cannot quietly return some other index. Failures are retried with
exponential backoff, then logged and recorded, never silently dropped.

The payload is a JSON string holding two JSON arrays joined by ``#@#``: a
one-row header (``Scrip`` is the BSE index code) and the dated values::

    "[{ \"Scrip\":\"INSURE\", ...}]#@#[{ \"date\":\"Tue Sep 01 2026 00:00:00\", \"value\":\"1521.41\"}, ...]"
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date

import pandas as pd
import requests

from src.data.calendar import TradingCalendar
from src.data.jugaad_indices import (
    MIN_OBSERVATIONS,
    RETRY_ATTEMPTS,
    RETRY_BASE_DELAY,
    RETRYABLE,
    VALUE_CLOSE,
    IncompleteSeries,
    completeness_problems,
)

logger = logging.getLogger(__name__)

SOURCE = "bseindices"
BASE_URL = "https://www.bseindices.com/AsiaIndexAPI/api/AsiaIndicesGraphData/w"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindices.com/",
}
TIMEOUT = 60
_DATE_FORMAT = "%a %b %d %Y %H:%M:%S"
_sleep = time.sleep


class WrongIndex(ValueError):
    """The response names a different BSE index than the one requested."""


def _url(source_id: int | str, start: date, end: date) -> str:
    # seriesid=DT with frd/tod is the page's custom date-range request.
    return (
        f"{BASE_URL}?index={int(source_id)}&flag=1&sector=&seriesid=DT"
        f"&frd={start:%Y%m%d}&tod={end:%Y%m%d}"
    )


def _get(url: str) -> object:
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def parse_payload(payload: object, name: str = "") -> tuple[str | None, pd.Series]:
    """``(index_code, series)`` from one response; the series is empty when nothing was served.

    Malformed payloads raise ``ValueError`` (retryable: a throttled or HTML
    response is transient). Rows without a positive ``value`` are dropped;
    the endpoint answers an empty window with the latest point under
    ``value1``, which is not a value for the requested dates.
    """
    text = payload if isinstance(payload, str) else json.dumps(payload) if payload is not None else ""
    if "#@#" not in text:
        raise ValueError(f"unexpected BSE Indices payload: {text[:120]!r}")
    head_text, body_text = text.split("#@#", 1)
    header = json.loads(head_text) if head_text.strip() else []
    rows = json.loads(body_text) if body_text.strip() else []
    if not isinstance(header, list) or not isinstance(rows, list):
        raise ValueError("unexpected BSE Indices payload shape")
    code = None
    if header and isinstance(header[0], dict) and header[0].get("Scrip"):
        code = str(header[0]["Scrip"]).strip().upper()
    frame = pd.DataFrame([r for r in rows if isinstance(r, dict) and "value" in r and "date" in r])
    if frame.empty:
        return code, pd.Series(dtype="float64", name=name)
    dates = pd.to_datetime(frame["date"].astype("string").str.strip(), format=_DATE_FORMAT, errors="coerce")
    values = pd.to_numeric(frame["value"].astype("string").str.replace(",", "", regex=False), errors="coerce")
    valid = dates.notna() & values.notna() & values.gt(0)
    if not valid.any():
        return code, pd.Series(dtype="float64", name=name)
    series = pd.Series(
        values.loc[valid].to_numpy(float), index=pd.DatetimeIndex(dates.loc[valid]).normalize(), name=name
    )
    return code, series.groupby(level=0).last().sort_index()


def fetch_bse_index(
    name: str,
    start: date,
    end: date,
    calendar: pd.DatetimeIndex | TradingCalendar | None = None,
    value_types: tuple[str, ...] = (VALUE_CLOSE,),
    min_observations: int = MIN_OBSERVATIONS,
    *,
    source_id: int | str,
    index_code: str,
) -> pd.Series:
    """Fetch one BSE price-index history; same contract as ``fetch_jugaad_index``.

    ``source_id`` is BSE Index Services' numeric id (``/indices-details/code/<id>``)
    and ``index_code`` the BSE index code its response must carry (``INSURE``).
    Only ``CLOSE`` is served; asking for anything else returns an empty series
    with the reason in ``attrs['errors']`` rather than a mislabelled one.
    """
    label = f"{name} [BSE {index_code}]"
    if VALUE_CLOSE not in value_types:
        empty = pd.Series(dtype="float64", name=name)
        empty.attrs["errors"] = [f"{'/'.join(map(str, value_types))}: BSE Indices serves the price index only"]
        return empty
    expected = str(index_code).strip().upper()
    url = _url(source_id, start, end)
    reason = ""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            code, series = parse_payload(_get(url), name)
            if code is not None and code != expected:
                raise WrongIndex(f"BSE id {source_id} served {code}, not {expected}")
            if code is None and not series.empty:
                raise WrongIndex(f"BSE id {source_id} served values without naming the index")
            problems = completeness_problems(series, start, end, calendar, min_observations)
            if problems:
                raise IncompleteSeries("; ".join(problems[:3]))
            series = series.rename(name)
            series.attrs.update(
                source=SOURCE, resolved_name=name, value_type=VALUE_CLOSE, index_code=expected
            )
            return series
        except WrongIndex as exc:  # a mapping error, not a flaky network: do not retry
            reason = f"{type(exc).__name__}: {exc}"
            logger.error("%s: %s", label, reason)
            break
        except RETRYABLE as exc:
            reason = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # a defect: do not retry
            logger.exception("%s: non-retryable failure", label)
            reason = f"{type(exc).__name__}: {exc}"
            break
        if attempt < RETRY_ATTEMPTS:
            delay = RETRY_BASE_DELAY * 2 ** (attempt - 1)
            logger.warning(
                "%s: attempt %d/%d failed (%s); retrying in %.0fs", label, attempt, RETRY_ATTEMPTS, reason, delay
            )
            _sleep(delay)
    else:
        logger.error("%s: giving up after %d attempts (%s)", label, RETRY_ATTEMPTS, reason)
    empty = pd.Series(dtype="float64", name=name)
    empty.attrs["errors"] = [f"{VALUE_CLOSE}: {reason}"]
    return empty
