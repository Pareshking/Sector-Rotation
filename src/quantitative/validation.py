from __future__ import annotations

import numpy as np
import pandas as pd


def validate_price_matrix(prices: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    if prices.empty:
        errors.append("Price matrix is empty")
        return errors
    if not isinstance(prices.index, pd.DatetimeIndex):
        errors.append("Price matrix index must be DatetimeIndex")
    if prices.index.has_duplicates:
        errors.append("Price matrix contains duplicate dates")
    if prices.isna().all(axis=None):
        errors.append("Price matrix contains no usable observations")
    if (prices <= 0).any(axis=None):
        errors.append("Price matrix contains non-positive prices")
    return errors


def validate_returns(returns: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    if np.isinf(returns.to_numpy(dtype=float, na_value=np.nan)).any():
        errors.append("Returns contain infinite values")
    if ((returns < -1).any(axis=None)):
        errors.append("Returns below -100% detected")
    return errors
