"""What the portfolio may hold, and from when.

Investability is point-in-time: an exposure is buyable on a date only if one
of its mapped vehicles (ETF or index fund) already had a price on that date.
Most of these funds launched in 2024-25; treating them as available in 2021
would be look-ahead of the worst kind. The same rule serves the live target
and every historical decision, which is what lets the two agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import pandas as pd


@dataclass(frozen=True)
class ExposureMeta:
    exposure_id: str
    name: str
    category: str = ""
    investable_from: pd.Timestamp | None = None
    vehicles: tuple[str, ...] = ()

    def investable_on(self, when: pd.Timestamp) -> bool:
        return self.investable_from is not None and self.investable_from <= pd.Timestamp(when)


def investable_from(
    vehicle_prices: pd.DataFrame | None, vehicles_by_exposure: Mapping[str, Iterable[str]] | None
) -> dict[str, pd.Timestamp]:
    """First date each exposure had a vehicle with a price."""
    starts: dict[str, pd.Timestamp] = {}
    if vehicle_prices is None or vehicle_prices.empty:
        return starts
    for exposure_id, keys in (vehicles_by_exposure or {}).items():
        firsts = [
            vehicle_prices[key].dropna().index.min()
            for key in keys
            if key in vehicle_prices.columns and not vehicle_prices[key].dropna().empty
        ]
        if firsts:
            starts[str(exposure_id)] = pd.Timestamp(min(firsts))
    return starts


def vehicles_by_exposure(etf_universe: pd.DataFrame | None) -> dict[str, list[str]]:
    """Exposure id -> the price-series keys (symbol, else fund name) of its vehicles."""
    if etf_universe is None or etf_universe.empty or "exposure_id" not in etf_universe.columns:
        return {}
    keyed = etf_universe.assign(key=etf_universe["symbol"].fillna(etf_universe["name"]))
    return {str(k): list(v) for k, v in keyed.groupby("exposure_id")["key"].apply(list).items()}


def build_universe_metadata(
    exposure_ids: Iterable[str],
    etf_universe: pd.DataFrame | None = None,
    vehicle_prices: pd.DataFrame | None = None,
    names: Mapping[str, str] | None = None,
    categories: Mapping[str, str] | None = None,
) -> dict[str, ExposureMeta]:
    vehicles = vehicles_by_exposure(etf_universe)
    starts = investable_from(vehicle_prices, vehicles)
    names = names or {}
    categories = categories or {}
    return {
        str(eid): ExposureMeta(
            exposure_id=str(eid),
            name=str(names.get(eid, eid)),
            category=str(categories.get(eid, "")),
            investable_from=starts.get(str(eid)),
            vehicles=tuple(vehicles.get(str(eid), ())),
        )
        for eid in exposure_ids
    }
