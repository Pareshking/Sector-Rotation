"""Which exposures can actually be bought.

One rule, shared by the app and the alert tool. When it lived only in the app
layer the alert report claimed every exposure was unbuyable, because the flag
it read was never populated outside Streamlit.
"""

from __future__ import annotations

import pandas as pd


def investable_exposure_ids(etfs: pd.DataFrame, etf_prices: pd.DataFrame | None = None) -> set[str]:
    """Exposures with a vehicle you could put money into.

    An open-ended index fund transacts at NAV and is never exchange-listed, so
    it counts even though NSE reports no turnover for it. For ETFs, live
    turnover is better evidence than whether our pipeline ingested a series —
    an upstream outage should not make a liquid fund look unbuyable.
    """
    if etfs is None or etfs.empty or "exposure_id" not in etfs.columns:
        return set()

    is_fund = (
        etfs["vehicle"].astype("string").eq("index_fund")
        if "vehicle" in etfs.columns
        else pd.Series(False, index=etfs.index)
    )
    if "traded_value" in etfs.columns:
        traded = pd.to_numeric(etfs["traded_value"], errors="coerce").fillna(0) > 0
        investable = traded | is_fund
        if investable.any():
            return set(etfs.loc[investable, "exposure_id"].dropna().astype(str))
    if is_fund.any():
        return set(etfs.loc[is_fund, "exposure_id"].dropna().astype(str))

    if etf_prices is None or etf_prices.empty:
        return set()
    keyed = etfs.assign(key=etfs["symbol"].fillna(etfs["name"]))
    with_history = keyed[keyed["key"].isin(etf_prices.columns)]
    return set(with_history["exposure_id"].dropna().astype(str))


def attach_tradeability(
    decisions: pd.DataFrame, etfs: pd.DataFrame, etf_prices: pd.DataFrame | None = None
) -> pd.DataFrame:
    frame = decisions.copy()
    if "exposure_id" not in frame.columns:
        return frame
    ids = investable_exposure_ids(etfs, etf_prices)
    frame["tradeable"] = frame["exposure_id"].astype(str).isin(ids)
    return frame
