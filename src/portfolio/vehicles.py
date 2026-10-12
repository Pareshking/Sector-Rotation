"""Which fund to buy for an exposure, and how long a position takes to build.

One rule, used by the Portfolio and Exposure pages alike:

1. Only vehicles that had incepted by the decision date (recorded
   ``inception_date``) are candidates.
2. Among candidates with at least a year of measured tracking against their
   own index, the one that gave up least — the highest (least negative)
   annualised tracking difference — wins. Tracking difference is expense ratio
   plus everything else, which is what a holder actually loses.
3. Without measured tracking: the ETF with the most NSE turnover, else the
   earliest-incepted index fund.

Days to build: an open-ended index fund transacts at NAV whatever the size, so
one order fills at the next NAV. An ETF is bought on exchange at no more than
``participation`` of a day's turnover.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

DEFAULT_BOOK_RUPEES = 3_000_000  # ₹30 lakh
PARTICIPATION_LIMIT = 0.10
MIN_TRACKING_YEARS = 1.0


@dataclass(frozen=True)
class VehicleChoice:
    exposure_id: str
    key: str
    name: str
    vehicle: str
    symbol: str | None
    scheme_code: int | None
    reason: str
    tracking_difference: float | None = None
    traded_value: float | None = None
    premium_discount_pct: float | None = None

    @property
    def label(self) -> str:
        return f"{self.symbol} · {self.name}" if self.symbol else self.name


def _num(value) -> float | None:
    out = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(out) else float(out)


def choose_vehicle(
    exposure_id: str,
    as_of: pd.Timestamp,
    vehicles: pd.DataFrame,
    tracking: pd.DataFrame | None = None,
) -> VehicleChoice | None:
    """The vehicle to buy ``exposure_id`` through on ``as_of``; None if none had incepted."""
    if vehicles is None or vehicles.empty:
        return None
    rows = vehicles[vehicles["exposure_id"].astype(str) == str(exposure_id)].copy()
    if "inception_date" in rows:
        rows = rows[pd.to_datetime(rows["inception_date"], errors="coerce") <= pd.Timestamp(as_of)]
    else:
        rows = rows.iloc[0:0]
    if rows.empty:
        return None
    rows["key"] = rows["symbol"].where(rows["symbol"].notna(), rows["name"]) if "symbol" in rows else rows["name"]
    rows["tracking_difference"] = float("nan")
    rows["history_years"] = 0.0
    if tracking is not None and not tracking.empty:
        keyed = tracking.assign(key=tracking["symbol"].where(tracking["symbol"].notna(), tracking["name"]))
        lookup = keyed.set_index("key")
        rows["tracking_difference"] = rows["key"].map(lookup["tracking_difference"])
        rows["history_years"] = rows["key"].map(lookup["history_years"]).fillna(0.0)
    rows["traded_value"] = pd.to_numeric(rows.get("traded_value"), errors="coerce")
    rows["_inception"] = pd.to_datetime(rows["inception_date"], errors="coerce")

    measured = rows[rows["tracking_difference"].notna() & (rows["history_years"] >= MIN_TRACKING_YEARS)]
    if not measured.empty:
        best = measured.sort_values(["tracking_difference", "key"], ascending=[False, True]).iloc[0]
        reason = (
            f"Least tracking difference against its index ({best['tracking_difference']:+.2%} a year "
            f"over {best['history_years']:.1f} years) among funds available on {pd.Timestamp(as_of):%d %b %Y}."
        )
    else:
        etfs = rows[(rows["vehicle"] == "etf") & rows["traded_value"].gt(0)]
        if not etfs.empty:
            best = etfs.sort_values(["traded_value", "key"], ascending=[False, True]).iloc[0]
            reason = "Most-traded ETF on NSE at the last snapshot; tracking not yet measurable over a year."
        else:
            best = rows.sort_values(["_inception", "key"]).iloc[0]
            reason = "Longest-running fund available; tracking not yet measurable over a year."
    symbol = best.get("symbol")
    return VehicleChoice(
        exposure_id=str(exposure_id),
        key=str(best["key"]),
        name=str(best["name"]),
        vehicle=str(best.get("vehicle") or "etf"),
        symbol=str(symbol) if isinstance(symbol, str) and symbol else None,
        scheme_code=int(best["scheme_code"]) if pd.notna(best.get("scheme_code")) else None,
        reason=reason,
        tracking_difference=_num(best.get("tracking_difference")),
        traded_value=_num(best.get("traded_value")),
        premium_discount_pct=_num(best.get("premium_discount_pct")),
    )


def days_to_build(
    choice: VehicleChoice | None,
    position_rupees: float,
    participation: float = PARTICIPATION_LIMIT,
) -> float | None:
    """Trading days to buy ``position_rupees`` of ``choice``; None when it cannot be judged."""
    if choice is None or position_rupees <= 0:
        return None if choice is None else 0.0
    if choice.vehicle == "index_fund":
        return 1.0
    if not choice.traded_value or choice.traded_value <= 0:
        return None
    return float(max(1, math.ceil(position_rupees / (choice.traded_value * participation))))
