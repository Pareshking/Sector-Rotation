"""NSE listed-ETF snapshot: traded value, NAV, and premium/discount.

AUM, expense ratio and tracking error are not published on any endpoint this
project can reach, so they stay null rather than being invented. What NSE does
publish is the part that most often decides whether a signal is actually
actionable: whether the ETF trades at all, and whether it trades near its NAV.

A persistent premium is a real, permanent cost to a buyer — a thinly traded
sector ETF at a 2% premium hands back two years of the index's edge on entry.
This is a point-in-time snapshot taken when the pipeline runs, not a history,
and it is labelled as such wherever it is displayed.
"""

from __future__ import annotations

from datetime import datetime, timezone

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


def fetch_etf_snapshot(session: requests.Session | None = None) -> pd.DataFrame:
    """One row per NSE-listed ETF. Returns an empty frame if NSE is unreachable.

    The snapshot is decoration on the implementation layer; it must never be
    able to fail a pipeline run that has already produced valid index history.
    """
    session = session or requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get(REFERER, timeout=TIMEOUT)
        response = session.get(ETF_API, timeout=TIMEOUT)
        response.raise_for_status()
        rows = response.json().get("data", [])
    except Exception:
        return pd.DataFrame(columns=COLUMNS)

    stamp = datetime.now(timezone.utc).isoformat()
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
