from __future__ import annotations

import streamlit as st

from app.components.metrics import data_health_banner, get_metadata, lineage_frame

st.title("System Health")
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

st.subheader("Data lineage")
lineage = lineage_frame(metadata)
if not lineage.empty:
    st.dataframe(lineage, use_container_width=True, hide_index=True)
    proxy = lineage[lineage["source"] == "benchmark_proxy"]
    if not proxy.empty:
        st.info(f"Transparent fallback lineage: {len(proxy)} canonical exposures use benchmark_proxy history. These are labelled proxies, not represented as authoritative Nifty index histories.")

st.subheader("Source counts")
st.json(metadata.get("source_counts", {}))

skipped = metadata.get("skipped_canonical_exposures", [])
if skipped:
    st.error(f"Skipped canonical exposures: {', '.join(skipped)}")
else:
    st.success("No canonical exposures are skipped.")
