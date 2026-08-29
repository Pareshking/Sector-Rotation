from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from src.models.exposure import Exposure


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def validate_universe(exposures: list[Exposure] | tuple[Exposure, ...]) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    ids = Counter(x.id for x in exposures)
    for item, count in ids.items():
        if count > 1:
            errors.append(f"Duplicate exposure id: {item}")
    etf_symbols: list[str] = []
    for exposure in exposures:
        if not exposure.benchmark.strip():
            errors.append(f"{exposure.id}: missing benchmark")
        for etf in exposure.etfs:
            etf_symbols.append(etf.symbol)
            if not etf.yfinance_symbol:
                warnings.append(f"{exposure.id}/{etf.symbol}: missing yfinance symbol")
    for symbol, count in Counter(etf_symbols).items():
        if count > 1:
            errors.append(f"Duplicate ETF symbol: {symbol}")
    return ValidationReport(not errors, tuple(errors), tuple(warnings))
