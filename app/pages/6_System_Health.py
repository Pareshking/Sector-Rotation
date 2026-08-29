from __future__ import annotations

import sys
from pathlib import Path
import streamlit as st

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.components.metrics import data_health_banner,get_metadata,lineage_frame
from app.components.theme import inject_theme,page_header,render_compact_table,section

inject_theme(); page_header("Trust & Lineage","System Health","Separate data coverage from decision quality. A 100% loaded universe does not mean every series is authoritative.")
metadata=get_metadata(); data_health_banner(metadata)
if not metadata: st.error("Prepared metadata is unavailable."); st.stop()

source_map=metadata.get("source_by_canonical_exposure",{}) or {}; proxy_count=sum(v=="benchmark_proxy" for v in source_map.values()); canonical=int(metadata.get("valid_canonical_series",0)); total=int(metadata.get("total_canonical_exposures",0)); decision_grade=canonical-proxy_count
c1,c2,c3,c4=st.columns(4); c1.metric("Canonical loaded",f"{canonical}/{total}"); c2.metric("Decision-grade",decision_grade); c3.metric("Benchmark proxies",proxy_count); c4.metric("ETF histories",f"{metadata.get('etf_valid_series',0)}/{metadata.get('etf_total',0)}")

section("Decision-grade boundary")
if proxy_count:
    st.markdown(f'<div class="sr-callout"><strong>{proxy_count} canonical exposures are coverage-only.</strong> Their histories are generated from broad/sector benchmark proxies rather than authoritative Nifty index histories. The UI blocks them from BUY/SELL candidates and labels them explicitly.</div>',unsafe_allow_html=True)
else: st.markdown('<div class="sr-callout sr-callout-good"><strong>No benchmark-proxy histories.</strong> All canonical series are authoritative or exact ETF/index proxies.</div>',unsafe_allow_html=True)

section("ETF health")
etf_total=int(metadata.get("etf_total",0)); etf_valid=int(metadata.get("etf_valid_series",0)); skipped=metadata.get("etf_skipped_symbols",[]) or []
if etf_valid<etf_total:
    st.markdown(f'<div class="sr-callout sr-callout-bad"><strong>ETF coverage is {etf_valid}/{etf_total}, not 100%.</strong> The current pipeline skipped {len(skipped)} instruments. This is a data-pipeline issue, not a UI issue.</div>',unsafe_allow_html=True)
    for item in skipped: st.write(f"• {item}")
else: st.markdown('<div class="sr-callout sr-callout-good"><strong>ETF coverage is complete.</strong></div>',unsafe_allow_html=True)

section("Data lineage")
lineage=lineage_frame(metadata)
if not lineage.empty:
    display=lineage.copy(); display["source"]=display.source.replace({"benchmark_proxy":"BENCHMARK PROXY · COVERAGE ONLY","etf_proxy":"ETF / NAV PROXY","niftyindices_tri":"NIFTY TRI","niftyindices_pr":"NIFTY PR","nse_archive":"NSE ARCHIVE","yahoo":"YAHOO","mfapi":"MFAPI","nse":"NSE"})
    render_compact_table(display,[("exposure","Exposure"),("source","Source"),("resolved_name","Resolved history")],limit=50)

with st.expander("Source counts",expanded=False): st.json(metadata.get("source_counts",{}))
warnings=metadata.get("validation_warnings",[]) or []
if warnings:
    with st.expander(f"Validation warnings · {len(warnings)}",expanded=False):
        for warning in warnings: st.write(f"• {warning}")
skipped_canonical=metadata.get("skipped_canonical_exposures",[]) or []
if skipped_canonical: st.error(f"Skipped canonical exposures: {', '.join(skipped_canonical)}")
else: st.success("No canonical exposures are skipped.")
