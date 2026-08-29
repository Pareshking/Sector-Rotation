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
    updated = str(metadata.get("last_updated_utc", "unknown"))
    skipped = metadata.get("skipped_canonical_exposures", [])
    fallback = metadata.get("fallback_canonical_exposures", [])
    status = "VERIFIED" if coverage >= 1.0 and not skipped else "ATTENTION"
    icon = "●" if status == "VERIFIED" else "!"
    st.markdown(
        f'''<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 14px;border:1px solid #e5e7eb;border-radius:12px;background:#f8fafc;margin:0 0 14px;">
        <div><span style="font-size:.72rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#64748b;">Data health</span><br><span style="font-size:1.05rem;font-weight:700;color:#0f172a;">{coverage:.0%} canonical coverage</span></div>
        <div style="text-align:right;font-size:.74rem;color:#64748b;">{icon} <strong style="color:{'#059669' if status == 'VERIFIED' else '#d97706'}">{status}</strong><br>updated {updated} · {len(fallback)} fallback · {len(skipped)} skipped</div>
        </div>''',
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


def metric_row(summary: pd.DataFrame) -> None:
    total = len(summary)
    leading = int((summary.get("stage", pd.Series(dtype=str)) == "Leading").sum())
    improving = int((summary.get("stage", pd.Series(dtype=str)) == "Improving").sum())
    weakening = int((summary.get("stage", pd.Series(dtype=str)) == "Weakening").sum())
    lagging = int((summary.get("stage", pd.Series(dtype=str)) == "Lagging").sum())
    cols = st.columns(5)
    cols[0].metric("Exposures", total)
    cols[1].metric("Leading", leading)
    cols[2].metric("Improving", improving)
    cols[3].metric("Weakening", weakening)
    cols[4].metric("Lagging", lagging)
