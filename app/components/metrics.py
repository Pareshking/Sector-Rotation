"""Target-portfolio annotation, data-health telemetry, and lineage helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from app.components.theme import _esc
from src.formatting import format_updated

ROOT = Path(__file__).resolve().parents[2]
METADATA_PATH = ROOT / "data" / "processed" / "metadata.json"

PROXY_SOURCES = {"benchmark_proxy", "etf_proxy"}

# Friendly labels for pipeline source codes. Unknown codes fall back to a
# prettified version of the code itself, so a new adapter never renders as a
# blank or a raw identifier the way ``niftyindices_jugaad`` previously did.
SOURCE_LABELS = {
    "niftyindices_jugaad": "NSE / NiftyIndices via jugaad-data",
    "niftyindices_tri": "NiftyIndices · TRI endpoint",
    "niftyindices_pr": "NiftyIndices · price endpoint",
    "nse_archive": "NSE archive",
    "nse_api": "NSE API",
    "nse": "NSE",
    "yahoo": "Yahoo Finance",
    "mfapi": "MFAPI NAV",
    "amfi": "AMFI NAV",
    "seed_cache": "Seeded canonical",
    "benchmark_proxy": "Excluded · benchmark proxy",
    "etf_proxy": "Excluded · ETF/NAV proxy",
}


def source_label(code: object) -> str:
    key = str(code or "").strip()
    if not key:
        return "—"
    return SOURCE_LABELS.get(key, key.replace("_", " ").title())


def _metadata_mtime() -> int:
    try:
        return METADATA_PATH.stat().st_mtime_ns
    except OSError:
        return 0


@st.cache_data(show_spinner=False)
def load_metadata(modified_ns: int = 0) -> dict[str, object]:
    del modified_ns
    if not METADATA_PATH.exists():
        return {}
    try:
        return json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def get_metadata() -> dict[str, object]:
    return load_metadata(_metadata_mtime())


def health_summary(metadata: dict[str, object] | None = None) -> dict[str, object]:
    metadata = metadata if metadata is not None else get_metadata()
    if not metadata:
        return {}
    source_map = metadata.get("source_by_canonical_exposure", {}) or {}
    proxy = sum(value in PROXY_SOURCES for value in source_map.values())
    canonical = int(metadata.get("valid_canonical_series", 0))
    total = int(metadata.get("total_canonical_exposures", 0))
    skipped = list(metadata.get("skipped_canonical_exposures", []) or [])
    absolute, relative = format_updated(metadata.get("last_updated_utc"))
    return {
        "canonical": canonical,
        "total": total,
        "proxy": proxy,
        "decision_grade": max(canonical - proxy, 0),
        "skipped": skipped,
        "etf_valid": int(metadata.get("etf_valid_series", 0)),
        "etf_total": int(metadata.get("etf_total", 0)),
        "etf_skipped": list(metadata.get("etf_skipped_symbols", []) or []),
        "missing_yfinance": list(metadata.get("missing_yfinance_symbols", []) or []),
        "warnings": list(metadata.get("validation_warnings", []) or []),
        "updated": absolute,
        "age": relative,
        "healthy": bool(
            metadata.get("canonical_coverage_ratio", 0.0) >= 1.0 and not skipped and proxy == 0
        ),
    }


def data_health_banner(metadata: dict[str, object] | None = None) -> None:
    """One compact line of provenance, above the fold on every page."""
    health = health_summary(metadata)
    if not health:
        st.markdown(
            '<div class="hs hs-warn">Data health · prepared metadata is unavailable</div>',
            unsafe_allow_html=True,
        )
        return
    tone = "" if health["healthy"] else " hs-warn"
    etf_note = f'{health["etf_valid"]}/{health["etf_total"]} ETF price histories'
    proxy_note = (
        f'<span class="hs-sep">|</span><span><b>{health["proxy"]}</b> proxy excluded</span>'
        if health["proxy"]
        else ""
    )
    age = f' · {_esc(health["age"])}' if health["age"] else ""
    st.markdown(
        f'<div class="hs{tone}">'
        f'<span><b>{health["decision_grade"]}/{health["total"]}</b> decision-grade histories</span>'
        f"{proxy_note}"
        f'<span class="hs-sep">|</span><span>{_esc(etf_note)}</span>'
        f'<span class="hs-time">Updated {_esc(health["updated"])}{age}</span>'
        "</div>",
        unsafe_allow_html=True,
    )


def lineage_frame(metadata: dict[str, object] | None = None) -> pd.DataFrame:
    metadata = metadata if metadata is not None else get_metadata()
    source_map = metadata.get("source_by_canonical_exposure", {}) or {}
    name_map = metadata.get("resolved_official_index_names", {}) or {}
    rows = [
        {
            "exposure": exposure,
            "source": source_label(source),
            "resolved_name": name_map.get(exposure, "—"),
        }
        for exposure, source in source_map.items()
    ]
    if not rows:
        return pd.DataFrame(columns=["exposure", "source", "resolved_name"])
    return pd.DataFrame(rows).sort_values("exposure", ignore_index=True)


def _shared_index_map(frame: pd.DataFrame) -> pd.Series:
    """Flag exposures that resolve to the same underlying Nifty index.

    NBFC and Financial Services ex-Bank both resolve to NIFTY FINANCIAL
    SERVICES EX-BANK, so they occupy two ranks while representing one bet.
    Surfacing that beats silently de-duplicating it.
    """
    blank = pd.Series([None] * len(frame), index=frame.index, dtype=object)
    key_col = "resolved_official_index_name"
    if key_col not in frame.columns or "exposure" not in frame.columns:
        return blank
    keys = frame[key_col].fillna("").astype(str)
    out = blank.copy()
    for key, group in frame.groupby(keys):
        if not key or len(group) < 2:
            continue
        for idx in group.index:
            peers = [str(x) for i, x in group["exposure"].items() if i != idx]
            out.at[idx] = ", ".join(peers)
    return out


# The actions a row can carry. BUY / HOLD / TRIM / SELL come straight from the
# target portfolio (src/portfolio/construct.py); everything else is either not
# in the portfolio or could not be scored. The RRG stage is display only.
PORTFOLIO_ACTIONS = ("BUY", "HOLD", "TRIM", "SELL")
NOT_HELD = "NOT HELD"
UNAVAILABLE = "DATA UNAVAILABLE"
HELD_ACTIONS = {"BUY", "HOLD", "TRIM"}


def decision_frame(summary: pd.DataFrame, portfolio=None) -> pd.DataFrame:
    """Summary rows annotated with what the target portfolio does with each exposure.

    ``portfolio`` is the ``TargetPortfolio`` produced by
    ``construct_target_portfolio`` at the latest rebalance — the same object
    the backtest's final decision is. Without one, nothing is actionable.
    """
    if summary is None or summary.empty:
        return summary.copy() if summary is not None else pd.DataFrame()
    frame = summary.copy()
    ids = frame["exposure_id"].astype(str) if "exposure_id" in frame else frame.index.astype(str)
    source = frame.get("data_source", pd.Series("", index=frame.index)).fillna("").astype(str)
    proxy = source.isin(PROXY_SOURCES)

    if portfolio is None:
        frame["model_action"] = UNAVAILABLE
        frame["decision_eligible"] = False
        frame["tradeable"] = False
        frame["target_weight"] = 0.0
        frame["prior_weight"] = 0.0
        frame["decision_rank"] = float("nan")
        frame["decision_status"] = ""
        frame["decision_reason"] = "No target portfolio: the index price panel is not available."
        frame["analysis_note"] = frame["decision_reason"]
        frame["shares_index_with"] = _shared_index_map(frame)
        return frame

    ranking = portfolio.ranking
    decisions = {d.exposure_id: d for d in portfolio.decisions}
    frame["decision_rank"] = ids.map(ranking["rank"]).astype(float).to_numpy()
    frame["strategy_score"] = ids.map(ranking["score"]).astype(float).to_numpy()
    frame["target_weight"] = ids.map(portfolio.weights).fillna(0.0).astype(float).to_numpy()
    frame["prior_weight"] = ids.map(ranking["prior_weight"]).fillna(0.0).astype(float).to_numpy()
    frame["decision_status"] = ids.map(ranking["status"]).fillna("").to_numpy()
    scorable = ids.map(ranking["valid"]).eq(True).to_numpy()
    frame["decision_eligible"] = scorable & ~proxy.to_numpy()
    frame["tradeable"] = ids.map(ranking["investable"]).eq(True).to_numpy()

    actions, reasons = [], []
    for eid, eligible, is_proxy in zip(ids, frame["decision_eligible"], proxy):
        decision = decisions.get(eid)
        if is_proxy:
            # The pipeline never admits a proxy into the price panel; this is the
            # backstop for a stale dataset generated before that rule existed.
            actions.append(UNAVAILABLE)
            reasons.append("No authoritative history; proxy data is deliberately excluded.")
        elif decision is not None:
            actions.append(decision.action)
            reasons.append(decision.reason)
        elif not eligible:
            actions.append(UNAVAILABLE)
            reasons.append(
                "No authoritative 12-month history; excluded from the portfolio rather than "
                "replaced with a proxy."
            )
        else:
            status = str(ranking["status"].get(eid, "") or "")
            detail = str(ranking["reason"].get(eid, "") or "")
            actions.append(NOT_HELD)
            reasons.append(f"Not held ({status}): {detail}." if detail else f"Not held ({status}).")
    frame["model_action"] = actions
    frame["decision_reason"] = reasons
    as_of = f"{pd.Timestamp(portfolio.as_of):%d %b %Y}"
    frame["analysis_note"] = [f"Decision at the {as_of} close. {r}" for r in reasons]
    frame["shares_index_with"] = _shared_index_map(frame)
    return frame


def action_counts(frame: pd.DataFrame) -> dict[str, int]:
    keys = ("total", "eligible", "held", "buy", "hold", "trim", "sell", "not_held")
    if frame is None or frame.empty or "model_action" not in frame:
        return dict.fromkeys(keys, 0)
    action = frame["model_action"]
    return {
        "total": len(frame),
        "eligible": int(frame["decision_eligible"].sum()),
        "held": int(action.isin(HELD_ACTIONS).sum()),
        "buy": int((action == "BUY").sum()),
        "hold": int((action == "HOLD").sum()),
        "trim": int((action == "TRIM").sum()),
        "sell": int((action == "SELL").sum()),
        "not_held": int((action == NOT_HELD).sum()),
    }


def market_state(panel: pd.DataFrame, benchmark: pd.Series, decisions: pd.DataFrame) -> dict[str, object]:
    """Headline market context: regime, benchmark level, and breadth.

    Regime is the benchmark against its own 200-day average — the crudest
    honest read of whether the tide is going in or out. Breadth is how much of
    the universe is actually leading, which is what decides whether a rotation
    model has anything to rotate into.
    """
    state: dict[str, object] = {}
    series = pd.to_numeric(benchmark, errors="coerce").dropna() if benchmark is not None else pd.Series(dtype=float)
    if not series.empty:
        last = float(series.iloc[-1])
        state["level"] = last
        state["as_of"] = series.index[-1]
        if len(series) >= 200:
            average = float(series.tail(200).mean())
            if average > 0:
                gap = last / average - 1.0
                state["vs_200d"] = gap
                state["regime"] = "BULLISH" if gap >= 0 else "BEARISH"
    if decisions is not None and not decisions.empty and "stage" in decisions.columns:
        eligible = decisions[decisions.get("decision_eligible", True)]
        leading = int((eligible["stage"] == "Leading").sum())
        state["leading"] = leading
        state["universe"] = int(len(eligible))
        if len(eligible):
            state["breadth"] = leading / len(eligible)
    del panel
    return state
