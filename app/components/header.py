"""The persistent status header: one line every page shares.

Rendered once by the app shell, above whichever page is running, so the regime,
the as-of date, the strategy version and the data's age are visible everywhere
without each page repeating them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import streamlit as st

from app.components.theme import _esc, chip, html_block


@dataclass(frozen=True)
class HeaderState:
    regime: str = ""
    benchmark_12m: float | None = None
    cash_12m: float | None = None
    cash_source: str = ""
    as_of: str = ""
    version: str = ""
    config_hash: str = ""
    updated: str = ""
    age_hours: float | None = None
    max_age_hours: float = 36.0

    @property
    def fresh(self) -> bool:
        return self.age_hours is not None and self.age_hours <= self.max_age_hours


def _age_hours(raw: object) -> float | None:
    try:
        stamp = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 3600.0


def _age_label(hours: float | None) -> str:
    if hours is None:
        return "age unknown"
    if hours < 1:
        return "updated just now"
    if hours < 48:
        return f"updated {hours:.0f}h ago"
    return f"updated {hours / 24:.0f}d ago"


def header_state() -> HeaderState:
    """Everything the header shows, read from the published artifacts."""
    from app.components.metrics import get_metadata
    from app.data import current_regime, load_portfolio, strategy_config
    from src.quantitative.quality import MAX_DATA_AGE_HOURS

    regime = current_regime()
    live = load_portfolio()
    config = strategy_config()
    metadata = get_metadata() or {}
    raw = metadata.get("last_updated_utc")
    return HeaderState(
        regime=regime.label if regime is not None else "",
        benchmark_12m=regime.benchmark_12m if regime is not None else None,
        cash_12m=regime.cash_12m if regime is not None else None,
        cash_source=regime.cash_source if regime is not None else "",
        as_of=f"{live.data_as_of:%d %b %Y}" if live is not None else "",
        version=str(config.version),
        config_hash=str(config.config_hash),
        updated=str(raw or ""),
        age_hours=_age_hours(raw) if raw else None,
        max_age_hours=float(MAX_DATA_AGE_HOURS),
    )


def _stat(label: str, value: str) -> str:
    return (
        f'<div class="ds-stat"><span class="ds-stat-l">{_esc(label)}</span>'
        f'<span class="ds-stat-v">{_esc(value)}</span></div>'
    )


def header_html(state: HeaderState) -> str:
    sep = '<span class="ds-sep"></span>'
    parts = ['<span class="ds-brand">Dual Momentum</span>']
    if state.regime:
        parts.append(chip(state.regime, "pos" if state.regime == "RISK-ON" else "neg", large=True, dot=True))
    if state.benchmark_12m is not None and state.cash_12m is not None:
        hurdle = "liquid fund" if state.cash_source == "nav" else "assumed cash"
        parts += [
            sep,
            _stat("Nifty 50 TRI · 12M", f"{state.benchmark_12m:+.1%}"),
            _stat(f"Hurdle · {hurdle} 12M", f"{state.cash_12m:.2%}"),
        ]
    if state.as_of:
        parts += [sep, _stat("As of", state.as_of)]
    # The rules' version and fingerprint live on the Method page; in the header
    # they read as a second strategy (owner, 12 Oct 2026).
    pulse = "ds-pulse" if state.fresh else "ds-pulse stale"
    verdict = "Data fresh" if state.fresh else "Data stale"
    parts.append(
        f'<span class="ds-fresh" title="{_esc(state.updated)}"><i class="{pulse}"></i>'
        f"{verdict} · {_esc(_age_label(state.age_hours))}</span>"
    )
    return f'<div class="ds-header" role="banner">{"".join(parts)}</div>'


def global_header() -> None:
    html_block(header_html(header_state()))
