from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
METADATA_PATH = ROOT / "data" / "processed" / "metadata.json"


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


def data_health_banner(metadata: dict[str, object] | None = None) -> None:
    metadata = metadata if metadata is not None else get_metadata()
    if not metadata:
        st.error("Data health · metadata unavailable")
        return
    coverage = float(metadata.get("canonical_coverage_ratio", metadata.get("coverage_ratio", 0.0)))
    etf_coverage = float(metadata.get("etf_coverage_ratio", 0.0))
    updated = str(metadata.get("last_updated_utc", "unknown"))
    skipped = metadata.get("skipped_canonical_exposures", [])
    fallback = metadata.get("fallback_canonical_exposures", [])
    proxy_count = sum(1 for source in metadata.get("source_by_canonical_exposure", {}).values() if source == "benchmark_proxy")
    status = "VERIFIED" if coverage >= 1.0 and not skipped else "ATTENTION"
    status_class = "sr-callout-good" if status == "VERIFIED" else "sr-callout"
    st.markdown(
        f'''<div class="sr-card {status_class}" style="margin-bottom:14px;">
        <div style="display:flex;justify-content:space-between;gap:14px;align-items:flex-start;">
          <div><div class="sr-card-label">Data health</div>
          <div class="sr-card-value">{coverage:.0%} canonical · {etf_coverage:.0%} ETF</div>
          <div class="sr-card-note">{len(fallback)} canonical fallbacks · {proxy_count} benchmark-proxy histories · {len(skipped)} skipped</div></div>
          <div style="text-align:right;font-size:.72rem;white-space:nowrap;"><strong>{status}</strong><br>{updated}</div>
        </div></div>''',
        unsafe_allow_html=True,
    )


def lineage_frame(metadata: dict[str, object] | None = None) -> pd.DataFrame:
    metadata = metadata if metadata is not None else get_metadata()
    source_map = metadata.get("source_by_canonical_exposure", {})
    name_map = metadata.get("resolved_official_index_names", {})
    rows = [
        {"exposure": exposure, "source": source, "resolved_name": name_map.get(exposure, exposure)}
        for exposure, source in source_map.items()
    ]
    return pd.DataFrame(rows).sort_values("exposure") if rows else pd.DataFrame(columns=["exposure", "source", "resolved_name"])


def decision_frame(summary: pd.DataFrame) -> pd.DataFrame:
    """Create an explicit, conservative decision layer from prepared metrics.

    Benchmark-proxy histories are never promoted to a buy/sell signal. They are
    kept visible for universe coverage but marked PROXY ONLY until authoritative
    index history is available.
    """
    if summary.empty:
        return summary.copy()
    frame = summary.copy()
    source = frame.get("data_source", pd.Series("", index=frame.index)).fillna("").astype(str)
    stage = frame.get("stage", pd.Series("", index=frame.index)).fillna("").astype(str)
    ratio = pd.to_numeric(frame.get("rs_ratio", pd.Series(float("nan"), index=frame.index)), errors="coerce")
    velocity = pd.to_numeric(frame.get("rs_momentum", pd.Series(float("nan"), index=frame.index)), errors="coerce")
    momentum = pd.to_numeric(frame.get("momentum_z", pd.Series(float("nan"), index=frame.index)), errors="coerce")

    proxy = source.eq("benchmark_proxy")
    buy = (~proxy) & stage.eq("Leading") & ratio.gt(1.0) & velocity.gt(0) & momentum.gt(0)
    reduce = (~proxy) & stage.isin(["Weakening", "Lagging"]) & ratio.lt(1.0) & velocity.lt(0)
    improving = (~proxy) & stage.eq("Improving") & ratio.gt(1.0) & velocity.gt(0)

    frame["decision_eligible"] = ~proxy
    frame["model_action"] = "WATCH"
    frame.loc[proxy, "model_action"] = "PROXY ONLY"
    frame.loc[improving, "model_action"] = "WATCH / IMPROVING"
    frame.loc[buy, "model_action"] = "BUY CANDIDATE"
    frame.loc[reduce, "model_action"] = "REDUCE / EXIT"

    frame["decision_reason"] = "Mixed signal"
    frame.loc[proxy, "decision_reason"] = "Benchmark proxy; not decision-grade"
    frame.loc[buy, "decision_reason"] = "Leading + RS above benchmark + positive velocity"
    frame.loc[reduce, "decision_reason"] = "Weakening/Lagging + RS below benchmark + negative velocity"
    frame.loc[improving, "decision_reason"] = "Improving + RS above benchmark + positive velocity"
    return frame


def metric_row(summary: pd.DataFrame) -> None:
    frame = decision_frame(summary)
    total = len(frame)
    eligible = int(frame.get("decision_eligible", pd.Series(dtype=bool)).sum())
    buy = int((frame.get("model_action", pd.Series(dtype=str)) == "BUY CANDIDATE").sum())
    reduce = int((frame.get("model_action", pd.Series(dtype=str)) == "REDUCE / EXIT").sum())
    proxy = int((frame.get("model_action", pd.Series(dtype=str)) == "PROXY ONLY").sum())
    cols = st.columns(5)
    cols[0].metric("Exposures", total)
    cols[1].metric("Decision-grade", eligible)
    cols[2].metric("Buy candidates", buy)
    cols[3].metric("Reduce / exit", reduce)
    cols[4].metric("Proxy only", proxy)
