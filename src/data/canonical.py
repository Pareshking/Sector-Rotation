"""Explicit ETF/NAV promotion — the single documented canonical fallback.

When NSE has no usable index history for an exposure, an explicitly mapped
ETF/fund NAV history may stand in as the canonical market-traded series. The
mapping is hand-maintained per exposure; it never guesses by ticker text,
category, or string similarity, so an unrelated instrument cannot become a
canonical benchmark by accident.
"""

from __future__ import annotations

from typing import Mapping

import pandas as pd

MIN_OBSERVATIONS = 60
SOURCE = "etf_nav_authoritative"


def promote_etf_histories(
    missing: Mapping[str, str],
    etf_histories: pd.DataFrame | None,
    canonical_etf_keys: Mapping[str, str] | None,
) -> tuple[dict[str, pd.Series], dict[str, str], dict[str, str]]:
    """Return (series_by_exposure, source_by_exposure, resolved_name_by_exposure)."""
    if etf_histories is None or etf_histories.empty or not canonical_etf_keys:
        return {}, {}, {}
    promoted: dict[str, pd.Series] = {}
    sources: dict[str, str] = {}
    resolved: dict[str, str] = {}
    for exposure_id in missing:
        key = canonical_etf_keys.get(exposure_id)
        if not key or key not in etf_histories.columns:
            continue
        series = pd.to_numeric(etf_histories[key], errors="coerce").dropna()
        if len(series) < MIN_OBSERVATIONS:
            continue
        promoted[exposure_id] = series.rename(exposure_id)
        sources[exposure_id] = SOURCE
        resolved[exposure_id] = f"ETF/NAV:{key}"
    return promoted, sources, resolved
