from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Iterable, Mapping

import pandas as pd
import yfinance as yf

from src.data.jugaad_indices import fetch_jugaad_canonical_indices
from src.data.nifty_indices import fetch_nifty_index_history, fetch_missing_indices

MIN_OBSERVATIONS = 60
YAHOO_TIMEOUT = 10


def download_history(symbols: Iterable[str], years: int = 5) -> pd.DataFrame:
    clean = [str(s) for s in symbols if s]
    if not clean:
        return pd.DataFrame()
    start = date.today() - timedelta(days=365 * years + 10)
    data = yf.download(clean, start=start.isoformat(), end=(date.today() + timedelta(days=1)).isoformat(), auto_adjust=True, progress=False, group_by="column", threads=True, timeout=YAHOO_TIMEOUT)
    if data.empty:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"] if "Close" in data.columns.get_level_values(0) else data.xs("Close", axis=1, level=0)
    else:
        close = data[["Close"]].rename(columns={"Close": clean[0]})
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.dropna(how="all").sort_index()


def _fetch_official_first(exposure_names: Mapping[str, str], years: int) -> tuple[pd.DataFrame, dict[str, str], dict[str, str]]:
    start = date.today() - timedelta(days=365 * years + 10)
    results: dict[str, pd.Series] = {}
    sources: dict[str, str] = {}
    resolved: dict[str, str] = {}

    def one(item):
        eid, name = item
        return eid, fetch_nifty_index_history(name, years=years, start=start, end=date.today(), retries=2)

    with ThreadPoolExecutor(max_workers=min(5, max(len(exposure_names), 1))) as pool:
        futures = [pool.submit(one, item) for item in exposure_names.items()]
        for future in as_completed(futures):
            try:
                eid, series = future.result()
            except Exception:
                continue
            if len(series.dropna()) >= MIN_OBSERVATIONS:
                results[eid] = series.rename(eid)
                sources[eid] = series.attrs.get("source", "niftyindices")
                resolved[eid] = series.attrs.get("resolved_name", exposure_names[eid])

    return (pd.DataFrame(results).sort_index() if results else pd.DataFrame()), sources, resolved


def download_canonical_indices(
    exposure_names: Mapping[str, str],
    yfinance_symbols: Mapping[str, str | None],
    years: int = 5,
    etf_histories: pd.DataFrame | None = None,
    canonical_etf_keys: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Resolve decision-grade canonical histories with strict provenance.

    Priority: direct official Nifty/NSE history -> jugaad-data's official Nifty
    index/TRI adapter -> explicitly matched ETF/NAV. Generic Yahoo indices are
    deliberately not used for canonical exposures.
    """
    del yfinance_symbols
    anchor = download_history(["^NSEI"], years=years)
    if not anchor.empty:
        anchor = anchor.rename(columns={"^NSEI": "nifty50"})

    official, sources, resolved = _fetch_official_first(exposure_names, years)
    prices = anchor.join(official, how="outer") if not official.empty else anchor.copy()

    missing = {eid: name for eid, name in exposure_names.items() if eid not in prices.columns or len(prices[eid].dropna()) < MIN_OBSERVATIONS}
    if missing:
        jugaad, jugaad_sources, jugaad_resolved = fetch_jugaad_canonical_indices(missing, years=years, workers=4)
        for eid in jugaad.columns:
            prices = prices.drop(columns=[eid], errors="ignore").join(jugaad[eid], how="outer")
            sources[eid] = jugaad_sources[eid]
            resolved[eid] = jugaad_resolved[eid]

    missing = {eid: name for eid, name in exposure_names.items() if eid not in prices.columns or len(prices[eid].dropna()) < MIN_OBSERVATIONS}
    if missing:
        fallback = fetch_missing_indices(
            missing,
            existing=prices,
            years=years,
            etf_histories=etf_histories,
            canonical_etf_keys=canonical_etf_keys,
        )
        fallback_sources = dict(fallback.attrs.get("source_by_exposure", {}))
        fallback_resolved = dict(fallback.attrs.get("resolved_name_by_exposure", {}))
        for eid in missing:
            if eid in fallback and len(fallback[eid].dropna()) >= MIN_OBSERVATIONS:
                prices = prices.drop(columns=[eid], errors="ignore").join(fallback[eid].rename(eid), how="outer")
                sources[eid] = fallback_sources.get(eid, "missing")
                resolved[eid] = fallback_resolved.get(eid, exposure_names[eid])

    prices = prices.drop(columns=["nifty50"], errors="ignore").sort_index()
    prices.attrs["source_by_exposure"] = sources
    prices.attrs["resolved_name_by_exposure"] = resolved
    prices.attrs["unresolved_exposures"] = [eid for eid in exposure_names if eid not in prices.columns or prices[eid].dropna().size < MIN_OBSERVATIONS]
    return prices
