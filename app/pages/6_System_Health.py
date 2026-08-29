from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.metrics import data_health_banner, get_metadata, lineage_frame
from app.components.theme import inject_theme, page_header, render_compact_table, section

inject_theme()
page_header(
    "Trust & Lineage",
    "System Health",
    "Coverage and decision quality are reported separately. Missing authoritative history is shown as unavailable — never silently replaced by a synthetic sector proxy.",
)
metadata = get_metadata()
data_health_banner(metadata)
if not metadata:
    st.error("Prepared metadata is unavailable.")
    st.stop()

source_map = metadata.get("source_by_canonical_exposure", {}) or {}
proxy_count = sum(v in {"benchmark_proxy", "etf_proxy"} for v in source_map.values())
canonical = int(metadata.get("valid_canonical_series", 0))
total = int(metadata.get("total_canonical_exposures", 0))
decision_grade = max(canonical - proxy_count, 0)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Authoritative histories", f"{decision_grade}/{total}")
c2.metric("Excluded proxies", proxy_count)
c3.metric("Missing histories", len(metadata.get("skipped_canonical_exposures", []) or []))
c4.metric("ETF histories", f"{metadata.get('etf_valid_series', 0)}/{metadata.get('etf_total', 0)}")

section("Decision boundary")
if proxy_count:
    st.error(
        f"{proxy_count} proxy histories are present in the prepared dataset. They are excluded from decisions and should disappear after the next authoritative-only pipeline refresh."
    )
else:
    st.success("No proxy histories are used for model decisions.")

section("ETF health")
etf_total = int(metadata.get("etf_total", 0))
etf_valid = int(metadata.get("etf_valid_series", 0))
skipped = metadata.get("etf_skipped_symbols", []) or []
if etf_valid < etf_total:
    st.warning(f"ETF coverage is {etf_valid}/{etf_total}. The skipped instruments are an ingestion issue, not a model signal.")
    for item in skipped:
        st.write(f"• {item}")
else:
    st.success("ETF coverage is complete.")

section("Data lineage")
lineage = lineage_frame(metadata)
if not lineage.empty:
    display = lineage.copy()
    display["source"] = display.source.replace(
        {
            "benchmark_proxy": "EXCLUDED · BENCHMARK PROXY",
            "etf_proxy": "EXCLUDED · ETF/NAV PROXY",
            "niftyindices_tri": "NIFTY TRI",
            "niftyindices_pr": "NIFTY PR",
            "nse_archive": "NSE ARCHIVE",
            "yahoo": "YAHOO INDEX",
            "mfapi": "MFAPI",
            "nse": "NSE",
            "nse_api": "NSE API",
            "seed_cache": "SEEDED CANONICAL",
        }
    )
    render_compact_table(display, [("exposure", "Exposure"), ("source", "Source"), ("resolved_name", "Resolved history")], limit=60)
else:
    st.info("No lineage records are available.")

with st.expander("Source counts", expanded=False):
    st.json(metadata.get("source_counts", {}))

warnings = metadata.get("validation_warnings", []) or []
if warnings:
    with st.expander(f"Validation warnings · {len(warnings)}", expanded=False):
        for warning in warnings:
            st.write(f"• {warning}")

skipped_canonical = metadata.get("skipped_canonical_exposures", []) or []
section("Missing authoritative histories")
if skipped_canonical:
    for item in skipped_canonical:
        st.write(f"• {item}")
else:
    st.success("No canonical histories are skipped.")
