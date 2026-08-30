"""Decision boundary, data-health telemetry, and lineage helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from app.components.theme import _esc, fmt_num, fmt_signed

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


def format_updated(raw: object) -> tuple[str, str]:
    """Return (absolute, relative) labels for the pipeline timestamp.

    The raw value is a microsecond ISO string, which is unreadable in a header.
    """
    text = str(raw or "")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return (text or "unknown", "")
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    absolute = stamp.strftime("%d %b %Y · %H:%M UTC")
    hours = (datetime.now(timezone.utc) - stamp).total_seconds() / 3600.0
    if hours < 1:
        relative = "just now"
    elif hours < 24:
        relative = f"{int(hours)}h ago"
    else:
        relative = f"{int(hours // 24)}d ago"
    return absolute, relative


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


def _analysis_note(row: dict[str, object], action: str) -> str:
    stage = str(row.get("stage", "Unknown"))
    ratio = fmt_num(row.get("rs_ratio"))
    velocity = fmt_signed(row.get("rs_momentum"))
    momentum = fmt_signed(row.get("momentum_z"))
    rank = pd.to_numeric(row.get("rank"), errors="coerce")
    rank_text = f"Rank {int(rank)}" if rank == rank else "Rank unavailable"

    if action == "BUY":
        return (
            f"{stage}; RS ratio {ratio} (> 1); RS velocity {velocity} (> 0); "
            f"momentum Z {momentum} (> 0). {rank_text} is informational — rank does not gate BUY."
        )
    if action == "REDUCE / EXIT":
        return (
            f"{stage}; RS ratio {ratio} (< 1); RS velocity {velocity} (< 0). "
            f"{rank_text} is informational — the exit rule is signal-based, not rank-based."
        )
    if action == "WATCH / IMPROVING":
        return (
            f"{stage}; RS ratio {ratio} is still below the benchmark but RS velocity {velocity} "
            f"has turned positive. This is an early turn, not a confirmed BUY. {rank_text}."
        )
    if action == "DATA UNAVAILABLE":
        return (
            "No authoritative decision-grade index history is available. Excluded from "
            "BUY/REDUCE decisions rather than replaced with a proxy."
        )
    if stage == "Weakening":
        return (
            f"{stage}; RS ratio {ratio} is still above the benchmark but RS velocity {velocity} "
            f"has rolled over. Leadership is fading before the exit rule triggers. {rank_text}."
        )
    return f"{stage}; the full BUY or REDUCE confirmation is not present. {rank_text}."


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


def decision_frame(summary: pd.DataFrame) -> pd.DataFrame:
    """Apply the deterministic decision boundary to prepared model output."""
    if summary is None or summary.empty:
        return summary.copy() if summary is not None else pd.DataFrame()

    frame = summary.copy()
    nan = pd.Series(float("nan"), index=frame.index)
    source = frame.get("data_source", pd.Series("", index=frame.index)).fillna("").astype(str)
    stage = frame.get("stage", pd.Series("", index=frame.index)).fillna("").astype(str)
    ratio = pd.to_numeric(frame.get("rs_ratio", nan), errors="coerce")
    velocity = pd.to_numeric(frame.get("rs_momentum", nan), errors="coerce")
    momentum = pd.to_numeric(frame.get("momentum_z", nan), errors="coerce")

    # Proxy histories are never decision data. This also protects the UI from
    # stale processed datasets until the next clean live pipeline refresh.
    proxy = source.isin(PROXY_SOURCES)
    valid = ratio.notna() & velocity.notna() & momentum.notna()
    buy = (~proxy) & valid & stage.eq("Leading") & ratio.gt(1.0) & velocity.gt(0) & momentum.gt(0)
    reduce = (~proxy) & valid & stage.isin(["Weakening", "Lagging"]) & ratio.lt(1.0) & velocity.lt(0)
    # An Improving exposure is by definition below the benchmark (rs_stage puts
    # rs_ratio < 1 with rising momentum here), so the previous ``ratio > 1``
    # clause could never be satisfied and this bucket never rendered.
    improving = (~proxy) & valid & stage.eq("Improving") & velocity.gt(0)

    frame["decision_eligible"] = (~proxy) & valid
    frame["model_action"] = "WATCH"
    frame.loc[proxy, "model_action"] = "DATA UNAVAILABLE"
    frame.loc[~valid & ~proxy, "model_action"] = "DATA UNAVAILABLE"
    frame.loc[improving, "model_action"] = "WATCH / IMPROVING"
    frame.loc[buy, "model_action"] = "BUY"
    frame.loc[reduce, "model_action"] = "REDUCE / EXIT"

    frame["decision_reason"] = "Full BUY/REDUCE confirmation is not present"
    frame.loc[buy, "decision_reason"] = (
        "Leading + RS ratio > 1 + positive RS velocity + positive momentum"
    )
    frame.loc[reduce, "decision_reason"] = "Weakening/Lagging + RS ratio < 1 + negative RS velocity"
    frame.loc[improving, "decision_reason"] = "Improving + RS velocity has turned positive"
    frame.loc[proxy, "decision_reason"] = (
        "No authoritative history; proxy data is deliberately excluded"
    )
    frame.loc[~valid & ~proxy, "decision_reason"] = "Required RS/momentum input is unavailable"

    # Presentation-only sub-state. It never changes BUY/REDUCE, but it stops a
    # rolling-over rank-1 leader from looking identical to a flat neutral name.
    frame["watch_kind"] = ""
    plain_watch = frame["model_action"].eq("WATCH")
    frame.loc[plain_watch & stage.eq("Weakening"), "watch_kind"] = "Rolling over"
    frame.loc[plain_watch & stage.eq("Leading"), "watch_kind"] = "Holding"
    frame.loc[frame["model_action"].eq("WATCH / IMPROVING"), "watch_kind"] = "Early turn"

    frame["shares_index_with"] = _shared_index_map(frame)
    frame["tradeable"] = False
    frame["analysis_note"] = [
        _analysis_note(row, str(row["model_action"])) for row in frame.to_dict("records")
    ]
    return frame


def action_counts(frame: pd.DataFrame) -> dict[str, int]:
    if frame is None or frame.empty:
        return {"total": 0, "eligible": 0, "buy": 0, "reduce": 0, "improving": 0, "watch": 0}
    action = frame["model_action"]
    return {
        "total": len(frame),
        "eligible": int(frame["decision_eligible"].sum()),
        "buy": int((action == "BUY").sum()),
        "reduce": int((action == "REDUCE / EXIT").sum()),
        "improving": int((action == "WATCH / IMPROVING").sum()),
        "watch": int((action == "WATCH").sum()),
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
