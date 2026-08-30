"""Canonical index resolution.

Resolution order is deliberately short:

1. NSE / NiftyIndices history via the jugaad-data adapter (every exposure, and
   the Nifty 50 benchmark, so both sides of every relative number share one
   calendar and one dividend treatment).
2. An explicitly mapped ETF/NAV series, only for exposures NSE cannot serve.

The previous implementation additionally scraped ``niftyindices.com``
Backpage endpoints, the NSE historical API, daily NSE archive CSVs, Yahoo index
symbols and a seed cache. In production none of those resolved a single
exposure — every canonical history came from the jugaad adapter — while they
still fired dozens of retried requests per run and could quietly admit a Yahoo
proxy into a decision-grade series. They have been removed.
"""

from __future__ import annotations

from typing import Mapping

import pandas as pd

from src.data.canonical import promote_etf_histories
from src.data.jugaad_indices import fetch_benchmark, fetch_jugaad_canonical_indices

MIN_OBSERVATIONS = 60


def download_canonical_indices(
    exposure_names: Mapping[str, str],
    years: int = 5,
    etf_histories: pd.DataFrame | None = None,
    canonical_etf_keys: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Resolve decision-grade canonical histories with strict provenance."""
    prices, sources, resolved, value_types = fetch_jugaad_canonical_indices(
        exposure_names, years=years, workers=10
    )

    missing = {
        eid: name
        for eid, name in exposure_names.items()
        if eid not in prices.columns or len(prices[eid].dropna()) < MIN_OBSERVATIONS
    }
    if missing:
        promoted, promoted_sources, promoted_resolved = promote_etf_histories(
            missing, etf_histories, canonical_etf_keys
        )
        for eid, series in promoted.items():
            prices = prices.drop(columns=[eid], errors="ignore").join(series, how="outer")
            sources[eid] = promoted_sources[eid]
            resolved[eid] = promoted_resolved[eid]
            value_types[eid] = "NAV"

    prices = prices.sort_index()
    prices.attrs["source_by_exposure"] = sources
    prices.attrs["resolved_name_by_exposure"] = resolved
    prices.attrs["value_type_by_exposure"] = value_types
    prices.attrs["unresolved_exposures"] = [
        eid
        for eid in exposure_names
        if eid not in prices.columns or prices[eid].dropna().size < MIN_OBSERVATIONS
    ]
    return prices


def download_benchmark(name: str = "NIFTY 50", years: int = 5) -> pd.Series:
    """Nifty 50 history from the same adapter every exposure uses."""
    return fetch_benchmark(name, years=years)
