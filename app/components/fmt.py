"""Figures as text for the kit's readings, metrics and tables.

Formatting only: nothing is computed here. A value that is missing or not a
finite number prints as an em dash, never as "None" or "nan".
"""

from __future__ import annotations

import math

import pandas as pd

DASH = "—"


def _num(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def pct(value: object, digits: int = 1, signed: bool = False) -> str:
    """A fraction as a percentage: 0.123 -> 12.3%."""
    number = _num(value)
    if number is None:
        return DASH
    return f"{number:+.{digits}%}" if signed else f"{number:.{digits}%}"


def num(value: object, digits: int = 2, signed: bool = False) -> str:
    number = _num(value)
    if number is None:
        return DASH
    return f"{number:+.{digits}f}" if signed else f"{number:.{digits}f}"


def rupees(value: object) -> str:
    """Indian units: ₹4.20 Cr, ₹30.0 L, ₹8,500."""
    number = _num(value)
    if number is None:
        return DASH
    if abs(number) >= 1e7:
        return f"₹{number / 1e7:.2f} Cr"
    if abs(number) >= 1e5:
        return f"₹{number / 1e5:.1f} L"
    return f"₹{number:,.0f}"


def day(value: object, pattern: str = "%d %b %Y") -> str:
    stamp = pd.to_datetime(value, errors="coerce")
    return DASH if pd.isna(stamp) else f"{stamp:{pattern}}"


def tone(value: object, neutral: float = 0.0) -> str:
    """The readings strip's colour for a signed figure: "up", "down" or ""."""
    number = _num(value)
    if number is None or number == neutral:
        return ""
    return "up" if number > neutral else "down"
