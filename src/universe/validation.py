from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from src.models.exposure import Exposure

NSE_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9&._-]{0,29}$")
YF_NSE_RE = re.compile(r"^[A-Z0-9][A-Z0-9&._-]{0,29}\.NS$")


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
    all_aliases: list[str] = []
    for exposure in exposures:
        if not exposure.benchmark.strip():
            errors.append(f"{exposure.id}: missing benchmark")
        for etf in exposure.etfs:
            symbol = etf.symbol
            etf_symbols.append(symbol)
            all_aliases.extend(etf.aliases)
            if not NSE_SYMBOL_RE.fullmatch(symbol):
                errors.append(f"{exposure.id}/{symbol}: invalid NSE symbol format")
            if etf.yfinance_symbol and not YF_NSE_RE.fullmatch(etf.yfinance_symbol):
                errors.append(f"{exposure.id}/{symbol}: invalid Yahoo NSE alias {etf.yfinance_symbol}")
            if not etf.yfinance_symbol:
                warnings.append(f"{exposure.id}/{symbol}: missing yfinance symbol; official/AMFI fallback required")
            if symbol in etf.aliases:
                errors.append(f"{exposure.id}/{symbol}: primary symbol duplicated in aliases")
    for symbol, count in Counter(etf_symbols).items():
        if count > 1:
            errors.append(f"Duplicate ETF symbol: {symbol}")
    for alias, count in Counter(all_aliases).items():
        if count > 1:
            errors.append(f"Duplicate ETF alias: {alias}")
        if not NSE_SYMBOL_RE.fullmatch(alias):
            errors.append(f"Invalid ETF alias format: {alias}")
    overlap = set(etf_symbols) & set(all_aliases)
    for symbol in sorted(overlap):
        warnings.append(f"ETF symbol is also listed as an alias: {symbol}")
    return ValidationReport(not errors, tuple(errors), tuple(warnings))
