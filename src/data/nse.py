from __future__ import annotations

import re


def normalize_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    value = re.sub(r"\.(NS|BO)$", "", value)
    if not value:
        raise ValueError("Symbol cannot be empty")
    return value


def nse_symbol(symbol: str) -> str:
    return f"{normalize_symbol(symbol)}.NS"
