from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from src.models.exposure import Exposure, VehicleType

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
    # Two exposures resolving to one index occupy two ranks while representing a
    # single bet, and the duplication is invisible in the UI. NBFC and Financial
    # Services ex-Bank shipped this way against NIFTY FINANCIAL SERVICES EX-BANK.
    benchmarks = Counter(x.benchmark.strip().upper() for x in exposures if x.benchmark.strip())
    for benchmark, count in benchmarks.items():
        if count > 1:
            sharing = sorted(x.id for x in exposures if x.benchmark.strip().upper() == benchmark)
            errors.append(f"Benchmark {benchmark} is shared by {count} exposures: {', '.join(sharing)}")
    etf_symbols: list[str] = []
    all_aliases: list[str] = []
    for exposure in exposures:
        if not exposure.benchmark.strip():
            errors.append(f"{exposure.id}: missing benchmark")
        for etf in exposure.etfs:
            symbol = etf.symbol
            if symbol is None and etf.scheme_code is None:
                errors.append(f"{exposure.id}/{etf.name}: ETF requires symbol or scheme_code")
                continue
            if symbol is not None:
                etf_symbols.append(symbol)
                if not NSE_SYMBOL_RE.fullmatch(symbol):
                    errors.append(f"{exposure.id}/{symbol}: invalid NSE symbol format")
                if symbol in etf.aliases:
                    errors.append(f"{exposure.id}/{symbol}: primary symbol duplicated in aliases")
            all_aliases.extend(etf.aliases)
            if etf.yfinance_symbol and not YF_NSE_RE.fullmatch(etf.yfinance_symbol):
                errors.append(f"{exposure.id}/{symbol or etf.scheme_code}: invalid Yahoo NSE alias {etf.yfinance_symbol}")
            # Yahoo is the last-resort source, and an open-ended index fund is
            # not exchange-listed at all, so a missing alias is only worth
            # noting for an exchange-traded vehicle with no scheme code either.
            if not etf.yfinance_symbol and etf.vehicle is VehicleType.ETF and etf.scheme_code is None:
                warnings.append(
                    f"{exposure.id}/{symbol or etf.name}: no AMFI scheme code and no Yahoo alias; "
                    "NSE is the only available source"
                )
            if etf.scheme_code is None:
                warnings.append(f"{exposure.id}/{symbol or etf.name}: MFAPI scheme code will be resolved by search")
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
