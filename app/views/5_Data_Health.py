"""Data Health: the Paresh app's data-quality footer and Market breadth page (src/ui/views/breadth_view.py).

Element by element: the page head, a strip of readings (breadth's "today"
strip), the stock page's data-check chips for the run's alerts, a bar list of
sources (Portfolio's sector mix), then cards holding kit tables: the launch-date
audit, the liquid fund with its NAV on Lightweight Charts, and the lineage.
The long tail stays in expanders, as the stock page keeps its data checks.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.fmt import DASH, day, pct  # noqa: E402
from app.components.header import header_state  # noqa: E402
from app.components.metrics import get_metadata, health_summary, lineage_frame, source_label  # noqa: E402
from app.data import UNIVERSE_PATH, load_cash_nav, load_decisions, load_index_panel  # noqa: E402
from app.kit import lw_chart as lw  # noqa: E402
from app.kit import page_kit as kit  # noqa: E402
from app.kit.theme import render_saas_table  # noqa: E402
from src.portfolio.live import load_registry  # noqa: E402

VALUE_TYPES = {"TRI": "TRI · total return", "CLOSE": "CLOSE · price index"}

metadata = get_metadata()
health = health_summary(metadata) if metadata else {}
kit.page_head("Data health", f"Where every number came from · published {health.get('updated', DASH)}")
if not metadata:
    kit.note("Prepared metadata is unavailable.", "Run the data pipeline first.")
    st.stop()

state = header_state()
alerts = [a for a in (metadata.get("quality_alerts") or []) if a.get("severity") in {"error", "warning"}]
errors = [a for a in alerts if a.get("severity") == "error"]
benchmark_type = str(metadata.get("benchmark_value_type") or DASH)
missing = len(health["skipped"]) + len(health["etf_skipped"])

if health["proxy"]:
    kit.note(f"{health['proxy']} proxy histories are present.", "They are excluded from decisions.")

kit.readings([
    kit.Reading("Freshness", "Fresh" if state.fresh else "Stale",
                f"{health['age'] or 'age unknown'} · limit {state.max_age_hours:.0f}h", "up" if state.fresh else "warn"),
    kit.Reading("Decision-grade", f"{health['decision_grade']}/{health['total']}", "authoritative index histories",
                "up" if health["healthy"] else "warn"),
    kit.Reading("Benchmark", f"{metadata.get('benchmark', 'Nifty 50')} {benchmark_type}",
                "total return confirmed" if benchmark_type == "TRI" else "not a total-return series",
                "up" if benchmark_type == "TRI" else "down"),
    kit.Reading("Fund histories", f"{health['etf_valid']}/{health['etf_total']}", "ETF and index-fund prices"),
    kit.Reading("Missing values", str(missing), "index or fund histories absent", "warn" if missing else "up"),
    kit.Reading("Execution alerts", str(len(alerts)), f"{len(errors)} error(s) vs the previous run",
                "down" if errors else ("warn" if alerts else "up")),
], "Data health")

checks = [(a.get("severity") == "error", f"{a.get('check', 'check')} — {a.get('message', '')}") for a in alerts]
if not checks:
    checks = [(False, "No data-quality regressions against the previous run")]
counts = {k: v for k, v in (metadata.get("source_counts") or {}).items() if v}
left, right = st.columns([1.4, 1], gap="medium")
with left, kit.card("Checks", "dh_checks", "this run against the previous one"):
    st.html('<div class="sp-checks">'
            + "".join(f'<span class="{"bad" if bad else ""}">{html.escape(text)}</span>' for bad, text in checks)
            + "</div>")
with right, kit.card("Sources", "dh_sources", "histories retrieved per source"):
    if counts:
        rows = [(f"{source_label(k.removeprefix('etf:'))}{' · fund' if k.startswith('etf:') else ''}",
                 float(v), str(v), False) for k, v in counts.items()]
        st.html(kit.bar_list(rows, scale=max(r[1] for r in rows)))
    else:
        kit.caption("No source counts in this run's metadata.")

# --------------------------------------------------------------------------- #
# Launch dates and back-calculated history
# --------------------------------------------------------------------------- #
panel, _ = load_index_panel()
decisions = load_decisions()
names = decisions.set_index("exposure_id")["exposure"].to_dict() if not decisions.empty else {}
with kit.card("Launch dates & backfill", "dh_launch", "NSE computes an index back to its base date when it launches it"):
    if panel.empty:
        kit.caption("The index price panel has not been written yet.")
    else:
        start = panel.index.min()
        rows = []
        for exposure in load_registry(UNIVERSE_PATH).all():
            if exposure.id not in panel.columns:
                continue
            observed = panel[exposure.id].dropna().index
            launch = pd.Timestamp(exposure.launch_date) if exposure.launch_date else None
            first_fund = pd.Timestamp(exposure.investable_from) if exposure.investable_from else None
            rows.append({
                "Exposure": names.get(exposure.id, exposure.name),
                "Base date": pd.Timestamp(exposure.base_date) if exposure.base_date else None,
                "NSE launch": launch,
                "Launch basis": ("Upper bound" if exposure.launch_date_is_upper_bound
                                 else ("Factsheet" if launch is not None else "Unknown")),
                "First fund": first_fund,
                "Back-calculated": float((observed < launch).mean()) if launch is not None and len(observed) else 0.0,
                "Investable": float((observed >= first_fund).mean()) if first_fund is not None and len(observed) else 0.0,
            })
        audit = pd.DataFrame(rows).sort_values(["Back-calculated", "Exposure"], ascending=[False, True])
        inside = audit[audit["Back-calculated"] > 0]
        synthetic = float(audit["Back-calculated"].mean()) if not audit.empty else 0.0
        kit.metric_row([
            kit.Metric("Launched inside the panel", f"{len(inside)} of {len(audit)}",
                       help=f"Their history before launch, from {start:%b %Y}, is synthetic"),
            kit.Metric("Synthetic share", f"{synthetic:.0%}", help="Of the panel, averaged across indices"),
            kit.Metric("Upper-bound launch dates", str(int((audit["Launch basis"] == "Upper bound").sum())),
                       help="The factsheet leaves Launch Date blank"),
            kit.Metric("No fund yet", str(int(audit["First fund"].isna().sum())), help="Signal only, nothing to buy"),
        ], key="dh_launch")
        render_saas_table(audit.assign(**{
            "Base date": audit["Base date"].map(day),
            "NSE launch": audit["NSE launch"].map(day),
            "First fund": audit["First fund"].map(day),
            "Back-calculated": audit["Back-calculated"].map(lambda v: pct(v, 0)),
            "Investable": audit["Investable"].map(lambda v: pct(v, 0)),
        }), max_height=480)
        kit.caption("Back-calculated and Investable: share of each index's stored history before its launch, and with "
                    "a fund available. Dates from NSE factsheets (universe.json) and AMFI's first NAV.")

# --------------------------------------------------------------------------- #
# Liquid fund: the cash return and the hurdle
# --------------------------------------------------------------------------- #
proxy = metadata.get("cash_proxy") or {}
cash = load_cash_nav()
with kit.card("Liquid fund", "dh_cash", "its NAV is the cash hurdle and the return on unallocated cash"):
    if cash is not None and not cash.empty:
        last_nav = cash.index.max()
        lag = (panel.index.max() - last_nav).days if not panel.empty else 0
        year_ago = cash.loc[: last_nav - pd.Timedelta(days=365)]
        trailing = float(cash.iloc[-1] / year_ago.iloc[-1] - 1.0) if not year_ago.empty else float("nan")
        kit.metric_row([
            kit.Metric("Latest NAV", f"₹{cash.iloc[-1]:,.2f}", help=f"{last_nav:%d %b %Y}"),
            kit.Metric("Trailing 12M", pct(trailing, 2), help="The hurdle every holding must beat"),
            kit.Metric("Lag to index data", f"{max(lag, 0)} days", help="NAV date against the last index session"),
            kit.Metric("History", f"{len(cash):,} NAVs", help=f"Since {cash.index.min():%b %Y}"),
        ], key="dh_cash")
        recent = cash.loc[last_nav - pd.Timedelta(days=400):]
        lw.render([{"height": 220, "series": [{"name": "NAV", "type": "area", "color": lw.INDIGO, "fmt": "num",
                                               "data": lw.series_points(recent.index, recent)}]}], key="dh_cash_nav")
        kit.caption(f"{proxy.get('name') or 'Configured liquid fund'} · AMFI scheme {proxy.get('scheme_code') or DASH} · "
                    f"ingest {proxy.get('mode') or DASH}")
    else:
        kit.callout("The liquid fund's NAV has not been published.",
                    "Until it is, the hurdle and cash accrual use the configured constant rate.", "warn")

# --------------------------------------------------------------------------- #
# Lineage and the long tail
# --------------------------------------------------------------------------- #
lineage = lineage_frame(metadata)
with kit.card("Data lineage", "dh_lineage", "one row per exposure"):
    if lineage.empty:
        kit.caption("No lineage records are available.")
    else:
        value_types = metadata.get("value_type_by_canonical_exposure", {}) or {}
        render_saas_table(pd.DataFrame({
            "Exposure": lineage["exposure"].map(lambda e: names.get(e, e)),
            "Retrieved via": lineage["source"],
            "Value": lineage["exposure"].map(lambda e: VALUE_TYPES.get(value_types.get(e), value_types.get(e) or DASH)),
            "Resolved index": lineage["resolved_name"],
        }), max_height=480)

with st.expander(f"Fund coverage · {health['etf_valid']}/{health['etf_total']}", expanded=False):
    if health["etf_skipped"]:
        st.write("No usable price history: " + ", ".join(health["etf_skipped"]))
        kit.caption("A gap in the implementation layer, not a signal: the index histories are unaffected.")
    else:
        st.write("Every mapped fund has a price history.")
with st.expander(f"Validation warnings · {len(health['warnings'])}", expanded=False):
    if health["warnings"]:
        for warning in health["warnings"]:
            st.write(f"• {warning}")
    else:
        st.write("No validation warnings.")
with st.expander(f"Missing Yahoo symbols · {len(health['missing_yfinance'])}", expanded=False):
    kit.caption("Yahoo is never used for an index history: this only means no secondary cross-check exists.")
    st.write(", ".join(sorted(names.get(e, e) for e in health["missing_yfinance"])) or "Every exposure has one.")
