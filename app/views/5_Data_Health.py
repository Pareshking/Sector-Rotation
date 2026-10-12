from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.metrics import (
    data_health_banner,
    get_metadata,
    health_summary,
    lineage_frame,
    source_label,
)
from app.components.navigation import mobile_nav
from app.components.theme import (
    inject_theme,
    kpi_strip,
    note,
    page_header,
    section,
)
from app.data import load_cash_nav, load_decisions, load_index_panel, universe_metadata

inject_theme()
mobile_nav("Data_Health")
page_header(
    "Trust & Lineage",
    "Data Health",
    "Where every number came from, and what is missing. Coverage and decision quality are "
    "reported separately — an absent history is shown as absent, never quietly replaced by a "
    "synthetic proxy.",
)

metadata = get_metadata()
data_health_banner(metadata)
if not metadata:
    st.error("Prepared metadata is unavailable.")
    st.stop()

health = health_summary(metadata)
kpi_strip(
    [
        ("Decision-grade", f"{health['decision_grade']}/{health['total']}", "authoritative histories", ""),
        ("Excluded proxies", health["proxy"], "never used for decisions", "red" if health["proxy"] else ""),
        ("Missing histories", len(health["skipped"]), "outside the decision set", "amber" if health["skipped"] else ""),
        ("ETF histories", f"{health['etf_valid']}/{health['etf_total']}", "price series ingested", ""),
    ]
)

alerts = metadata.get("quality_alerts", []) or []
actionable = [a for a in alerts if a.get("severity") in {"error", "warning"}]
if actionable:
    section("Quality alerts", "Regressions against the previous published run")
    for alert in actionable:
        text = f"**{alert.get('check', 'check')}** — {alert.get('message', '')}"
        (st.error if alert.get("severity") == "error" else st.warning)(text)
elif alerts:
    section("Quality alerts")
    st.success("No data-quality regressions detected against the previous run.")

section("Provenance")
note(
    "Canonical index histories are retrieved from <b>NSE / NiftyIndices</b> through the "
    "<code>jugaad-data</code> adapter. jugaad-data is a retrieval client, not a data authority: "
    "it returns whichever series NSE serves. Where the total-return endpoint answers, the series "
    "is a <b>TRI</b>; where only the price endpoint answers, it is a <b>price close</b> and "
    "carries no dividend. The <i>Value</i> column below states which one each exposure actually "
    "uses, so no series is presented as total return unless it is."
)

if health["proxy"]:
    st.error(
        f"{health['proxy']} proxy histories are present in the prepared dataset. They are excluded "
        "from decisions and should disappear after the next authoritative-only refresh."
    )
else:
    st.success("No proxy histories are used for model decisions.")

section("Backtest data")
panel, benchmark = load_index_panel()
if panel.empty:
    note(
        "The canonical index price panel (<code>index_prices.parquet</code>) has not been written "
        "yet. The Evidence page needs it; the next pipeline run produces it.",
        tone="amber",
    )
else:
    st.success(
        f"Index panel available: {panel.shape[1]} exposures plus the Nifty 50 benchmark, "
        f"{len(panel)} trading days from {panel.index.min():%d %b %Y} to {panel.index.max():%d %b %Y}."
    )

    meta = universe_metadata()
    rows = []
    for eid in panel.columns:
        item = meta.get(str(eid))
        if item is None or item.launch_date is None or item.launch_date <= panel.index.min():
            continue
        observed = panel[eid].dropna().index
        rows.append(
            {
                "Exposure": item.name,
                "NSE launch": item.launch_date,
                "Base date": item.base_date,
                "Back-calculated": float((observed < item.launch_date).mean()) if len(observed) else None,
            }
        )
    section(
        "Back-calculated history",
        "Indices NSE launched inside the panel; their earlier values were computed after the fact",
    )
    if rows:
        frame = pd.DataFrame(rows).sort_values("Back-calculated", ascending=False)
        st.dataframe(
            frame,
            hide_index=True,
            width="stretch",
            column_config={
                "NSE launch": st.column_config.DateColumn(format="DD MMM YYYY"),
                "Base date": st.column_config.DateColumn(format="DD MMM YYYY"),
                "Back-calculated": st.column_config.ProgressColumn(
                    format="percent", min_value=0.0, max_value=1.0,
                    help="Share of this index's stored history that predates its launch",
                ),
            },
        )
        note(
            f"<b>{len(rows)} of {panel.shape[1]} indices launched inside the panel.</b> Launch and base "
            "dates come from each index's NSE Indices factsheet, recorded in <code>universe.json</code>. "
            "The Evidence page shows the strategy with and without everything before each launch date.",
            tone="amber",
        )
    else:
        st.success("Every index in the panel launched before the panel starts.")

section("Cash proxy", "The liquid fund whose NAV is the cash hurdle and the cash return")
proxy = (get_metadata() or {}).get("cash_proxy") or {}
cash = load_cash_nav()
if cash is not None and not cash.empty:
    st.success(
        f"{proxy.get('name') or 'Configured liquid fund'} (AMFI scheme {proxy.get('scheme_code', '—')}): "
        f"{len(cash)} daily NAVs from {cash.index.min():%d %b %Y} to {cash.index.max():%d %b %Y}."
    )
else:
    note(
        "The liquid fund's NAV (<code>cash_nav.parquet</code>) has not been published yet. Until it "
        "is, the cash hurdle and cash accrual use the configured constant rate.",
        tone="amber",
    )

section("ETF coverage")
if health["etf_valid"] < health["etf_total"]:
    st.warning(
        f"ETF price coverage is {health['etf_valid']}/{health['etf_total']}. This is an ingestion "
        "gap in the implementation layer, not a model signal — the canonical index histories "
        "behind every decision are unaffected."
    )
    for item in health["etf_skipped"]:
        st.write(f"• {item}")
else:
    st.success("ETF coverage is complete.")

decisions = load_decisions()
exposure_names = (
    decisions.set_index("exposure_id")["exposure"].to_dict() if not decisions.empty else {}
)

section("Data lineage", "One row per canonical exposure")
lineage = lineage_frame(metadata)
if lineage.empty:
    st.info("No lineage records are available.")
else:
    value_types = metadata.get("value_type_by_canonical_exposure", {}) or {}
    lineage["Exposure"] = lineage["exposure"].map(lambda e: exposure_names.get(e, e))
    lineage["Value"] = lineage["exposure"].map(lambda e: value_types.get(e, "—"))
    display = lineage[["Exposure", "source", "Value", "resolved_name"]].rename(
        columns={"source": "Retrieved via", "resolved_name": "Resolved index"}
    )
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        height=min(56 + 35 * len(display), 560),
        column_config={
            "Exposure": st.column_config.TextColumn(width="medium", pinned=True),
            "Retrieved via": st.column_config.TextColumn(width="medium"),
            "Value": st.column_config.TextColumn(
                width="small", help="TRI = total return series; CLOSE = price index, no dividend"
            ),
            "Resolved index": st.column_config.TextColumn(width="large"),
        },
    )

section("Missing Yahoo symbols", "Affects nothing in the decision path")
missing_yf = health["missing_yfinance"]
if missing_yf:
    st.caption(
        f"{len(missing_yf)} exposures carry no Yahoo Finance symbol. Yahoo is never used for a "
        "canonical index history, so this does not affect any signal — it only means no secondary "
        "cross-check series exists for those exposures."
    )
    st.write(", ".join(sorted(exposure_names.get(e, e) for e in missing_yf)))
else:
    st.success("Every exposure has a secondary symbol mapped.")

with st.expander("Source counts", expanded=False):
    counts = metadata.get("source_counts", {}) or {}
    if counts:
        st.dataframe(
            pd.DataFrame(
                [
                    {"Source": source_label(k.replace("etf:", "")) + (" · ETF" if k.startswith("etf:") else ""),
                     "Series": v}
                    for k, v in counts.items()
                    if v
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No source counts were recorded.")

warnings = health["warnings"]
if warnings:
    with st.expander(f"Validation warnings · {len(warnings)}", expanded=False):
        for warning in warnings:
            st.write(f"• {warning}")

section("Missing authoritative histories")
if health["skipped"]:
    for item in health["skipped"]:
        st.write(f"• {item}")
else:
    st.success("No canonical history is skipped.")
