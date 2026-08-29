from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
METADATA_PATH = ROOT / "data" / "processed" / "metadata.json"


def load_metadata() -> dict[str, object]:
    if not METADATA_PATH.exists():
        return {}
    try:
        return json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def data_health_banner(metadata: dict[str, object] | None = None) -> None:
    metadata = metadata or load_metadata()
    if not metadata:
        st.info("Data health: metadata unavailable")
        return
    coverage = float(metadata.get("canonical_coverage_ratio", metadata.get("coverage_ratio", 0.0)))
    updated = str(metadata.get("last_updated_utc", "unknown"))
    fallback = metadata.get("fallback_canonical_exposures", [])
    skipped = metadata.get("skipped_canonical_exposures", [])
    if coverage >= 1.0 and not skipped:
        st.success(f"Data health: 100% canonical coverage · updated {updated}")
    elif coverage > 0:
        st.warning(f"Data health: {coverage:.1%} canonical coverage · updated {updated} · fallback {len(fallback)} · skipped {len(skipped)}")
    else:
        st.error(f"Data health: no valid canonical series · updated {updated}")


def metric_row(summary: pd.DataFrame) -> None:
    total = len(summary)
    leading = int((summary.get("stage", pd.Series(dtype=str)) == "Leading").sum())
    improving = int((summary.get("stage", pd.Series(dtype=str)) == "Improving").sum())
    st.metric("Exposures", total)
    cols = st.columns(3)
    cols[0].metric("Leading", leading)
    cols[1].metric("Improving", improving)
    cols[2].metric("Top Rank", summary.iloc[0]["exposure"] if not summary.empty else "—")
