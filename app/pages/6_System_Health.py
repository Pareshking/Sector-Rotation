from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.metrics import data_health_banner, get_metadata, lineage_frame
from app.components.theme import inject_theme, page_header, section

inject_theme()
page_header("Trust & Lineage", "System Health", "Coverage, freshness and source attribution for the prepared dataset")
metadata = get_metadata()
data_health_banner(metadata)

if not metadata:
    st.error("Prepared metadata is unavailable.")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Canonical", f"{metadata.get('valid_canonical_series', 0)}/{metadata.get('total_canonical_exposures', 0)}")
c2.metric("Canonical coverage", f"{float(metadata.get('canonical_coverage_ratio', 0.0)):.1%}")
c3.metric("ETF", f"{metadata.get('etf_valid_series', 0)}/{metadata.get('etf_total', 0)}")
c4.metric("ETF coverage", f"{float(metadata.get('etf_coverage_ratio', 0.0)):.1%}")

section("Data lineage")
lineage = lineage_frame(metadata)
if not lineage.empty:
    st.dataframe(lineage, width="stretch", hide_index=True)
    proxy = lineage[lineage["source"] == "benchmark_proxy"]
    if not proxy.empty:
        st.info(f"{len(proxy)} canonical exposures use benchmark_proxy history. These are explicitly labelled proxies, not authoritative Nifty index histories.")

section("Source counts")
st.json(metadata.get("source_counts", {}))

skipped = metadata.get("skipped_canonical_exposures", [])
if skipped:
    st.error(f"Skipped canonical exposures: {', '.join(skipped)}")
else:
    st.success("No canonical exposures are skipped.")
