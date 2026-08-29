from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
METADATA_PATH = ROOT / "data" / "processed" / "metadata.json"


def _metadata_mtime() -> int:
    try: return METADATA_PATH.stat().st_mtime_ns
    except OSError: return 0


@st.cache_data(show_spinner=False)
def load_metadata(modified_ns: int = 0) -> dict[str, object]:
    del modified_ns
    if not METADATA_PATH.exists(): return {}
    try: return json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {}


def get_metadata() -> dict[str, object]: return load_metadata(_metadata_mtime())


def data_health_banner(metadata: dict[str, object] | None = None) -> None:
    metadata=metadata if metadata is not None else get_metadata()
    if not metadata:
        st.error("Data health · metadata unavailable"); return
    canonical=int(metadata.get("valid_canonical_series",0)); total=int(metadata.get("total_canonical_exposures",0))
    coverage=float(metadata.get("canonical_coverage_ratio",0.0)); etf=int(metadata.get("etf_valid_series",0)); etf_total=int(metadata.get("etf_total",0))
    skipped=metadata.get("skipped_canonical_exposures",[]) or []; fallback=metadata.get("fallback_canonical_exposures",[]) or []
    source_map=metadata.get("source_by_canonical_exposure",{}) or {}; proxy_count=sum(v=="benchmark_proxy" for v in source_map.values())
    decision_grade=canonical-proxy_count
    updated=str(metadata.get("last_updated_utc","unknown"))
    status="VERIFIED" if coverage>=1.0 and not skipped else "ATTENTION"
    cls="sr-callout-good" if status=="VERIFIED" else "sr-callout"
    st.markdown(f'''<div class="sr-card {cls}" style="margin-bottom:14px"><div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start"><div><div class="sr-card-label">Data health</div><div class="sr-card-value">{canonical}/{total} canonical loaded</div><div class="sr-card-note">{decision_grade} decision-grade · {proxy_count} benchmark-proxy coverage-only · {etf}/{etf_total} ETF histories</div></div><div style="text-align:right;font-size:.7rem;white-space:nowrap"><strong>{status}</strong><br>{updated}</div></div></div>''', unsafe_allow_html=True)


def lineage_frame(metadata: dict[str, object] | None = None) -> pd.DataFrame:
    metadata=metadata if metadata is not None else get_metadata(); source_map=metadata.get("source_by_canonical_exposure",{}) or {}; name_map=metadata.get("resolved_official_index_names",{}) or {}
    rows=[{"exposure":e,"source":s,"resolved_name":name_map.get(e,e)} for e,s in source_map.items()]
    return pd.DataFrame(rows).sort_values("exposure") if rows else pd.DataFrame(columns=["exposure","source","resolved_name"])


def decision_frame(summary: pd.DataFrame) -> pd.DataFrame:
    """Conservative decision layer. Benchmark-proxy histories are coverage-only."""
    if summary.empty: return summary.copy()
    frame=summary.copy()
    source=frame.get("data_source",pd.Series("",index=frame.index)).fillna("").astype(str)
    stage=frame.get("stage",pd.Series("",index=frame.index)).fillna("").astype(str)
    ratio=pd.to_numeric(frame.get("rs_ratio",pd.Series(float("nan"),index=frame.index)),errors="coerce")
    velocity=pd.to_numeric(frame.get("rs_momentum",pd.Series(float("nan"),index=frame.index)),errors="coerce")
    momentum=pd.to_numeric(frame.get("momentum_z",pd.Series(float("nan"),index=frame.index)),errors="coerce")
    proxy=source.eq("benchmark_proxy")
    valid=ratio.notna() & velocity.notna() & momentum.notna()
    buy=(~proxy)&valid&stage.eq("Leading")&ratio.gt(1.0)&velocity.gt(0)&momentum.gt(0)
    reduce=(~proxy)&valid&stage.isin(["Weakening","Lagging"])&ratio.lt(1.0)&velocity.lt(0)
    improving=(~proxy)&valid&stage.eq("Improving")&ratio.gt(1.0)&velocity.gt(0)
    frame["decision_eligible"]=(~proxy)&valid
    frame["model_action"]="WATCH"
    frame.loc[proxy,"model_action"]="PROXY ONLY"
    frame.loc[~valid & ~proxy,"model_action"]="INSUFFICIENT DATA"
    frame.loc[improving,"model_action"]="WATCH / IMPROVING"
    frame.loc[buy,"model_action"]="BUY CANDIDATE"
    frame.loc[reduce,"model_action"]="REDUCE / EXIT"
    frame["decision_reason"]="Mixed / wait for confirmation"
    frame.loc[proxy,"decision_reason"]="Benchmark proxy; coverage only, not decision-grade"
    frame.loc[~valid & ~proxy,"decision_reason"]="Required RS/momentum input is unavailable"
    frame.loc[buy,"decision_reason"]="Leading + RS ratio > 1 + positive RS velocity + positive momentum"
    frame.loc[reduce,"decision_reason"]="Weakening/Lagging + RS ratio < 1 + negative RS velocity"
    frame.loc[improving,"decision_reason"]="Improving + RS ratio > 1 + positive RS velocity"
    return frame


def metric_row(summary: pd.DataFrame) -> None:
    frame=decision_frame(summary); total=len(frame); eligible=int(frame["decision_eligible"].sum()) if not frame.empty else 0
    buy=int((frame["model_action"]=="BUY CANDIDATE").sum()) if not frame.empty else 0; reduce=int((frame["model_action"]=="REDUCE / EXIT").sum()) if not frame.empty else 0
    proxy=int((frame["model_action"]=="PROXY ONLY").sum()) if not frame.empty else 0
    cols=st.columns(4)
    cols[0].metric("Exposures",total); cols[1].metric("Decision-grade",eligible); cols[2].metric("Buy candidates",buy); cols[3].metric("Reduce / exit",reduce)
