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
page_header("Trust & Lineage", "System Health", "Coverage, freshness and source attribution for every prepared series.")
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

section("Decision-grade boundary")
lineage = lineage_frame(metadata)
proxy = lineage[lineage["source"] == "benchmark_proxy"] if not lineage.empty else lineage
if not proxy.empty:
    st.markdown(
        f'<div class="sr-callout"><strong>{len(proxy)} exposures are benchmark proxies.</strong> Coverage is 100%, but those series are not authoritative Nifty histories. The dashboard therefore keeps them visible while blocking them from buy/sell candidate status.</div>',
        unsafe_allow_html=True,
    )
else:
    st.markdown('<div class="sr-callout sr-callout-good"><strong>No benchmark-proxy histories.</strong> All canonical exposures are sourced from authoritative or ETF/index proxy channels.</div>', unsafe_allow_html=True)

section("Data lineage")
if not lineage.empty:
    display = lineage.copy()
    display["source"] = display["source"].replace({"benchmark_proxy": "BENCHMARK PROXY", "etf_proxy": "ETF PROXY", "niftyindices_tri": "NIFTY TRI", "niftyindices_pr": "NIFTY PR", "nse_archive": "NSE ARCHIVE", "yahoo": "YAHOO", "mfapi": "MFAPI", "nse": "NSE"})
    st.dataframe(display, width="stretch", hide_index=True)

with st.expander("Source counts", expanded=False):
    st.json(metadata.get("source_counts", {}))

warnings = metadata.get("validation_warnings", [])
if warnings:
    with st.expander(f"Validation warnings · {len(warnings)}", expanded=False):
        for warning in warnings:
            st.write(f"• {warning}")

skipped = metadata.get("skipped_canonical_exposures", [])
if skipped:
    st.error(f"Skipped canonical exposures: {', '.join(skipped)}")
else:
    st.success("No canonical exposures are skipped.")
