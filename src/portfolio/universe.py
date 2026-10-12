"""What the portfolio may hold, and from when — from authoritative metadata only.

Buyability is point-in-time: an exposure is buyable on a date only if one of
its mapped vehicles had already incepted, by the ``inception_date`` recorded in
``data/universe/universe.json`` (AMFI's first published NAV). It is never
inferred from the nightly price download: a fetch that fails one night must
not turn a fund that launched years ago into an unbuyable one and sell it.

Each exposure also carries its index's NSE ``launch_date``. History before it
was back-calculated after the fact; the strategy can be run with or without it
(``backfill_policy``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import pandas as pd

# Prices this many days before a recorded inception mean the date is wrong.
INCEPTION_SLACK_DAYS = 10


@dataclass(frozen=True)
class ExposureMeta:
    exposure_id: str
    name: str
    category: str = ""
    investable_from: pd.Timestamp | None = None
    vehicles: tuple[str, ...] = ()
    launch_date: pd.Timestamp | None = None
    base_date: pd.Timestamp | None = None

    def investable_on(self, when: pd.Timestamp) -> bool:
        return self.investable_from is not None and self.investable_from <= pd.Timestamp(when)

    def backcalculated_on(self, when: pd.Timestamp) -> bool:
        """True when ``when`` precedes the index's launch: its value then was computed later."""
        return self.launch_date is not None and pd.Timestamp(when) < self.launch_date


def _ts(value) -> pd.Timestamp | None:
    return pd.Timestamp(value) if value is not None else None


def build_universe_metadata(
    exposure_ids: Iterable[str],
    registry,
    names: Mapping[str, str] | None = None,
    categories: Mapping[str, str] | None = None,
) -> dict[str, ExposureMeta]:
    """Metadata for ``exposure_ids`` from the universe registry (``universe.json``).

    An id the registry does not know gets no inception date, and so is never
    buyable: an exposure nobody has dated is not assumed to exist.
    """
    names = names or {}
    categories = categories or {}
    known = {e.id: e for e in registry.all()} if registry is not None else {}
    out: dict[str, ExposureMeta] = {}
    for eid in exposure_ids:
        exposure = known.get(str(eid))
        if exposure is None:
            out[str(eid)] = ExposureMeta(str(eid), str(names.get(eid, eid)), str(categories.get(eid, "")))
            continue
        out[str(eid)] = ExposureMeta(
            exposure_id=exposure.id,
            name=str(names.get(eid, exposure.name)),
            category=str(categories.get(eid, exposure.category.value)),
            investable_from=_ts(exposure.investable_from),
            vehicles=tuple(v.symbol or v.name for v in exposure.etfs),
            launch_date=_ts(exposure.launch_date),
            base_date=_ts(exposure.base_date),
        )
    return out


def inception_conflicts(registry, vehicle_prices: pd.DataFrame | None) -> list[str]:
    """Vehicles whose price history starts well before their recorded inception date.

    The nightly prices never decide buyability; they are only evidence that a
    recorded date is wrong and needs a reviewed correction.
    """
    if registry is None or vehicle_prices is None or vehicle_prices.empty:
        return []
    problems = []
    for exposure in registry.all():
        for vehicle in exposure.etfs:
            key = vehicle.symbol or vehicle.name
            if vehicle.inception_date is None or key not in vehicle_prices.columns:
                continue
            series = vehicle_prices[key].dropna()
            if series.empty:
                continue
            first = series.index.min()
            if first < pd.Timestamp(vehicle.inception_date) - pd.Timedelta(days=INCEPTION_SLACK_DAYS):
                problems.append(
                    f"{exposure.id}/{key}: prices from {first:%Y-%m-%d} precede the recorded "
                    f"inception {vehicle.inception_date}"
                )
    return problems


def backcalculated_mask(prices: pd.DataFrame, metadata: Mapping[str, ExposureMeta]) -> pd.DataFrame:
    """True where a value predates its index's launch (back-calculated history)."""
    mask = pd.DataFrame(False, index=prices.index, columns=prices.columns)
    for column in prices.columns:
        meta = metadata.get(str(column))
        if meta is not None and meta.launch_date is not None:
            mask[column] = prices.index < meta.launch_date
    return mask
