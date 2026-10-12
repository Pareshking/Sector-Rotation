"""NSE listed-ETF snapshot: traded value, NAV, and premium/discount.

AUM, expense ratio and tracking error are not published on any endpoint this
project can reach, so they stay null rather than being invented. What NSE does
publish is the part that most often decides whether a signal is actually
actionable: whether the ETF trades at all, and whether it trades near its NAV.

A persistent premium is a real, permanent cost to a buyer — a thinly traded
sector ETF at a 2% premium hands back two years of the index's edge on entry.
This is a point-in-time snapshot taken when the pipeline runs, not a history,
and it is labelled as such wherever it is displayed. When NSE refuses the
request, the last snapshot it did serve is carried forward with its own
timestamp for up to ``MAX_CARRY_FORWARD_DAYS``, rather than replaced by blanks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd
import requests

ETF_API = "https://www.nseindia.com/api/etf"
REFERER = "https://www.nseindia.com/market-data/exchange-traded-funds-etf"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Sector-Rotation/1.0)",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = (10, 45)
ATTEMPTS = 3
RETRY_PAUSE_SECONDS = 20.0
# NSE intermittently refuses cloud runners. A snapshot this old is still a fair
# guide to whether an ETF trades at all; an older one is dropped, not shown.
MAX_CARRY_FORWARD_DAYS = 14

COLUMNS = [
    "symbol",
    "traded_value",
    "traded_quantity",
    "last_price",
    "nav",
    "premium_discount_pct",
    "week52_high",
    "week52_low",
    "snapshot_utc",
]


def _number(value: object) -> float:
    try:
        text = str(value).replace(",", "").strip()
        return float(text) if text and text.lower() not in {"-", "none", "nan"} else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _parse(rows: list[dict], stamp: str) -> pd.DataFrame:
    records = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        price, nav = _number(row.get("ltP")), _number(row.get("nav"))
        premium = (price / nav - 1.0) * 100.0 if price == price and nav == nav and nav > 0 else float("nan")
        records.append(
            {
                "symbol": symbol,
                "traded_value": _number(row.get("trdVal")),
                "traded_quantity": _number(row.get("qty")),
                "last_price": price,
                "nav": nav,
                "premium_discount_pct": premium,
                "week52_high": _number(row.get("wkhi")),
                "week52_low": _number(row.get("wklo")),
                "snapshot_utc": stamp,
            }
        )
    return pd.DataFrame(records, columns=COLUMNS) if records else pd.DataFrame(columns=COLUMNS)


def fetch_etf_snapshot(
    session_factory: Callable[[], requests.Session] = requests.Session,
    attempts: int = ATTEMPTS,
    pause: float = RETRY_PAUSE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[pd.DataFrame, str]:
    """One row per NSE-listed ETF, and why it is empty when it is.

    Each attempt opens a fresh session, because NSE's bot screen sets its
    cookies on the referer page and a refused session stays refused. The
    snapshot is decoration on the implementation layer; it must never be able
    to fail a pipeline run that has already produced valid index history, so
    every failure is returned as a reason, never raised.
    """
    error = ""
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            session = session_factory()
            session.headers.update(HEADERS)
            session.get(REFERER, timeout=TIMEOUT)
            response = session.get(ETF_API, timeout=TIMEOUT)
            response.raise_for_status()
            frame = _parse(response.json().get("data", []), datetime.now(timezone.utc).isoformat())
            if not frame.empty:
                return frame, ""
            error = "NSE returned no ETF rows"
        except Exception as exc:  # noqa: BLE001 - any failure is a reason, not a crash
            error = f"{type(exc).__name__}: {exc}"[:300]
        if attempt < attempts:
            sleep(pause * attempt)
    return pd.DataFrame(columns=COLUMNS), f"{error} (after {attempts} attempt(s))"


@dataclass(frozen=True)
class SnapshotResolution:
    snapshot: pd.DataFrame
    status: str            # "fresh", "carried_forward", "unavailable" or "skipped"
    as_of_utc: str | None
    error: str = ""

    def report(self, matched: int, total: int) -> dict:
        return {"status": self.status, "as_of_utc": self.as_of_utc, "matched_etfs": int(matched),
                "total_etfs": int(total), "error": self.error}


def load_last_snapshot(path: Path) -> pd.DataFrame:
    """The last snapshot NSE actually served; empty if none was kept."""
    try:
        frame = pd.read_parquet(path)
    except Exception:  # noqa: BLE001 - a missing or unreadable file means no fallback
        return pd.DataFrame(columns=COLUMNS)
    return frame.reindex(columns=COLUMNS)


def resolve_snapshot(
    fresh: pd.DataFrame,
    error: str,
    last_good: pd.DataFrame,
    now: datetime | None = None,
    max_age_days: int = MAX_CARRY_FORWARD_DAYS,
) -> SnapshotResolution:
    """Today's snapshot if NSE served one, else the last good one while it is recent.

    A refused fetch used to publish blanks over the previous run's good values;
    carrying the last good snapshot forward keeps its own ``snapshot_utc`` so
    every reader can see how old it is.
    """
    if fresh is not None and not fresh.empty:
        return SnapshotResolution(fresh, "fresh", str(fresh["snapshot_utc"].dropna().max()), "")
    stamps = pd.to_datetime(last_good.get("snapshot_utc"), errors="coerce", utc=True) if not last_good.empty else None
    if stamps is not None and stamps.notna().any():
        newest = stamps.max()
        now = now or datetime.now(timezone.utc)
        if (pd.Timestamp(now) - newest) <= pd.Timedelta(days=max_age_days):
            return SnapshotResolution(last_good, "carried_forward", newest.isoformat(), error)
        error = f"{error}; last good snapshot {newest:%Y-%m-%d} is older than {max_age_days} days".lstrip("; ")
    return SnapshotResolution(pd.DataFrame(columns=COLUMNS), "unavailable", None, error)


def merge_snapshot(etfs: pd.DataFrame, snapshot: pd.DataFrame) -> pd.DataFrame:
    """Attach the snapshot to the ETF universe, matching on NSE trading symbol."""
    merged = etfs.copy()
    for column in COLUMNS[1:]:
        merged[column] = pd.NA
    if snapshot is None or snapshot.empty or "symbol" not in merged.columns:
        return merged
    lookup = snapshot.drop_duplicates("symbol").set_index("symbol")
    symbols = merged["symbol"].astype("string").str.upper()
    for column in COLUMNS[1:]:
        merged[column] = symbols.map(lookup[column])
    return merged


# A retail book is small enough that raw turnover is the wrong lens. What
# matters is whether one position clears without moving the price, and the
# convention is that a day's participation should stay a small share of volume.
DEFAULT_BOOK_RUPEES = 3_000_000
DEFAULT_POSITION_SHARE = 0.5      # top-2 rotation puts half the book in one name
PARTICIPATION_LIMIT = 0.10        # take at most 10% of a day's turnover


def position_headroom(
    traded_value: float,
    book: float = DEFAULT_BOOK_RUPEES,
    position_share: float = DEFAULT_POSITION_SHARE,
    participation: float = PARTICIPATION_LIMIT,
) -> dict[str, float]:
    """How many trading days one position would take to build at a sane pace.

    Returns days_to_build and the share of a day's turnover a single position
    represents. For most sector ETFs a retail-sized position clears in one day,
    which is precisely the edge a small book has over a large one.
    """
    position = book * position_share
    if not traded_value or traded_value != traded_value or traded_value <= 0:
        return {"position": position, "days_to_build": float("inf"), "day_share": float("inf")}
    capacity = traded_value * participation
    return {
        "position": position,
        "days_to_build": position / capacity,
        "day_share": position / traded_value,
    }
