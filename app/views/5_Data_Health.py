from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import CHART_CONFIG, nav_sparkline  # noqa: E402
from app.components.header import header_state  # noqa: E402
from app.components.metrics import get_metadata, health_summary, lineage_frame, source_label  # noqa: E402
from app.components.tables import show_table  # noqa: E402
from app.components.theme import _esc, chip, html_block, kpi_grid, note, page_header, section  # noqa: E402
from app.data import UNIVERSE_PATH, load_cash_nav, load_decisions, load_index_panel  # noqa: E402
from src.portfolio.live import load_registry  # noqa: E402

page_header(
    "Trust & lineage",
    "Data Health",
    "Where every number came from and what is missing. An absent history is shown as absent, never quietly "
    "replaced by a synthetic proxy.",
)

metadata = get_metadata()
if not metadata:
    note("<b>Prepared metadata is unavailable.</b> Run the data pipeline first.", tone="neg")
    st.stop()

health = health_summary(metadata)
state = header_state()
alerts = [a for a in (metadata.get("quality_alerts") or []) if a.get("severity") in {"error", "warning"}]
errors = [a for a in alerts if a.get("severity") == "error"]
benchmark_type = str(metadata.get("benchmark_value_type") or "—")
missing = len(health["skipped"]) + len(health["etf_skipped"])

# --------------------------------------------------------------------------- #
# Health status grid
# --------------------------------------------------------------------------- #
section("Status", f"Published {health['updated']}")
kpi_grid(
    [
        ("Freshness", "Fresh" if state.fresh else "Stale",
         f"{health['age'] or 'age unknown'} · limit {state.max_age_hours:.0f}h", "pos" if state.fresh else "warn"),
        ("Decision-grade", f"{health['decision_grade']}/{health['total']}", "authoritative index histories",
         "pos" if health["healthy"] else "warn"),
        ("Benchmark", f"{metadata.get('benchmark', 'Nifty 50')} {benchmark_type}",
         "total return confirmed" if benchmark_type == "TRI" else "not a total-return series",
         "pos" if benchmark_type == "TRI" else "neg"),
        ("Fund histories", f"{health['etf_valid']}/{health['etf_total']}", "ETF and index-fund prices", ""),
        ("Missing values", str(missing), "index or fund histories absent", "warn" if missing else "pos"),
        ("Execution alerts", str(len(alerts)), f"{len(errors)} error(s) vs the previous run",
         "neg" if errors else ("warn" if alerts else "pos")),
    ]
)

counts = {k: v for k, v in (metadata.get("source_counts") or {}).items() if v}
if counts:
    html_block(
        '<div class="ds-legend"><span>Sources</span>'
        + "".join(
            chip(f"{source_label(k.removeprefix('etf:'))}{' · fund' if k.startswith('etf:') else ''} {v}", "info")
            for k, v in counts.items()
        )
        + "</div>"
    )
for alert in alerts:
    note(f"<b>{_esc(alert.get('check', 'check'))}</b> — {_esc(alert.get('message', ''))}",
         tone="neg" if alert.get("severity") == "error" else "warn")
if not alerts:
    note("No data-quality regressions against the previous published run.", tone="pos")
if health["proxy"]:
    note(f"<b>{health['proxy']} proxy histories are present.</b> They are excluded from decisions.", tone="neg")

# --------------------------------------------------------------------------- #
# Launch dates and back-calculated history
# --------------------------------------------------------------------------- #
panel, _ = load_index_panel()
decisions = load_decisions()
names = decisions.set_index("exposure_id")["exposure"].to_dict() if not decisions.empty else {}
section("Launch dates & backfill audit", "NSE computes an index back to its base date when it launches it")
if panel.empty:
    note("The index price panel has not been written yet.", tone="warn")
else:
    start = panel.index.min()
    rows = []
    for exposure in load_registry(UNIVERSE_PATH).all():
        if exposure.id not in panel.columns:
            continue
        observed = panel[exposure.id].dropna().index
        launch = pd.Timestamp(exposure.launch_date) if exposure.launch_date else None
        first_fund = pd.Timestamp(exposure.investable_from) if exposure.investable_from else None
        rows.append(
            {
                "Exposure": names.get(exposure.id, exposure.name),
                "Base date": pd.Timestamp(exposure.base_date) if exposure.base_date else None,
                "NSE launch": launch,
                "Launch basis": ("Upper bound" if exposure.launch_date_is_upper_bound
                                 else ("Factsheet" if launch is not None else "Unknown")),
                "First fund": first_fund,
                "Back-calculated in panel": float((observed < launch).mean()) if launch is not None and len(observed) else 0.0,
                "Investable in panel": float((observed >= first_fund).mean()) if first_fund is not None and len(observed) else 0.0,
            }
        )
    audit = pd.DataFrame(rows).sort_values(["Back-calculated in panel", "Exposure"], ascending=[False, True])
    inside = audit[audit["Back-calculated in panel"] > 0]
    synthetic = float(audit["Back-calculated in panel"].mean()) if not audit.empty else 0.0
    kpi_grid(
        [
            ("Launched inside the panel", f"{len(inside)} of {len(audit)}",
             f"their history before launch, from {start:%b %Y}, is synthetic", "warn" if len(inside) else "pos"),
            ("Synthetic share of the panel", f"{synthetic:.0%}", "averaged across indices", ""),
            ("Upper-bound launch dates", str(int((audit["Launch basis"] == "Upper bound").sum())),
             "factsheet leaves Launch Date blank", ""),
            ("No fund yet", str(int(audit["First fund"].isna().sum())), "signal only, nothing to buy", ""),
        ]
    )
    show_table(
        audit,
        hide_index=True,
        width="stretch",
        height=min(40 + 35 * len(audit), 560),
        column_config={
            "Exposure": st.column_config.TextColumn(pinned=True),
            "Base date": st.column_config.DateColumn(format="DD MMM YYYY"),
            "NSE launch": st.column_config.DateColumn(format="DD MMM YYYY", help="From the NSE Indices factsheet"),
            "Launch basis": st.column_config.TextColumn(
                help="Upper bound: NSE publishes no launch date, so this is the latest day the index is documented live"),
            "First fund": st.column_config.DateColumn(format="DD MMM YYYY",
                                                      help="Earliest authoritative inception among its vehicles"),
            "Back-calculated in panel": st.column_config.ProgressColumn(
                format="percent", min_value=0.0, max_value=1.0, help="Share of this index's stored history before its launch"),
            "Investable in panel": st.column_config.ProgressColumn(
                format="percent", min_value=0.0, max_value=1.0, help="Share of its stored history on which a fund existed"),
        },
    )
    note("Launch and base dates come from each index's NSE Indices factsheet, recorded in <code>universe.json</code>; "
         "fund dates are each vehicle's first published NAV in AMFI's record. The Evidence page shows the strategy "
         "with and without everything before each launch date.")

# --------------------------------------------------------------------------- #
# Liquid fund: the cash return and the hurdle
# --------------------------------------------------------------------------- #
section("Liquid fund status", "Its NAV is the cash hurdle and the return on unallocated cash")
proxy = metadata.get("cash_proxy") or {}
cash = load_cash_nav()
if cash is not None and not cash.empty:
    last_nav = cash.index.max()
    lag = (panel.index.max() - last_nav).days if not panel.empty else 0
    year_ago = cash.loc[: last_nav - pd.Timedelta(days=365)]
    trailing = float(cash.iloc[-1] / year_ago.iloc[-1] - 1.0) if not year_ago.empty else float("nan")
    kpi_grid(
        [
            ("Latest NAV", f"₹{cash.iloc[-1]:,.2f}", f"{last_nav:%d %b %Y}", ""),
            ("Trailing 12M", f"{trailing:.2%}" if trailing == trailing else "—", "the hurdle every holding must beat", "info"),
            ("Lag to index data", f"{max(lag, 0)} days", "NAV date vs last index session", "pos" if lag <= 3 else "warn"),
            ("History", f"{len(cash):,} NAVs", f"since {cash.index.min():%b %Y}", ""),
        ]
    )
    st.plotly_chart(nav_sparkline(cash.loc[last_nav - pd.Timedelta(days=400):]), width="stretch", config=CHART_CONFIG)
    st.caption(f"{_esc(proxy.get('name') or 'Configured liquid fund')} · AMFI scheme {proxy.get('scheme_code', '—')} · "
               f"ingest mode {proxy.get('mode', '—')}")
else:
    note("The liquid fund's NAV (<code>cash_nav.parquet</code>) has not been published. Until it is, the hurdle and "
         "cash accrual use the configured constant rate.", tone="warn")

# --------------------------------------------------------------------------- #
# Lineage and the long tail
# --------------------------------------------------------------------------- #
section("Data lineage", "One row per canonical exposure")
lineage = lineage_frame(metadata)
if lineage.empty:
    note("No lineage records are available.")
else:
    value_types = metadata.get("value_type_by_canonical_exposure", {}) or {}
    display = pd.DataFrame(
        {
            "Exposure": lineage["exposure"].map(lambda e: names.get(e, e)),
            "Retrieved via": lineage["source"],
            "Value": lineage["exposure"].map(lambda e: value_types.get(e, "—")),
            "Resolved index": lineage["resolved_name"],
        }
    )
    show_table(display, hide_index=True, width="stretch", height=min(40 + 35 * len(display), 480),
                 column_config={"Exposure": st.column_config.TextColumn(pinned=True),
                                "Value": st.column_config.TextColumn(help="TRI = total return; CLOSE = price index")})

with st.expander(f"Fund coverage · {health['etf_valid']}/{health['etf_total']}", expanded=False):
    if health["etf_skipped"]:
        st.write("No usable price history: " + ", ".join(health["etf_skipped"]))
        st.caption("An ingestion gap in the implementation layer, not a signal. The index histories behind every "
                   "decision are unaffected.")
    else:
        st.write("Every mapped fund has a price history.")
with st.expander(f"Validation warnings · {len(health['warnings'])}", expanded=False):
    for warning in health["warnings"] or ["None."]:
        st.write(f"• {warning}")
with st.expander(f"Missing Yahoo symbols · {len(health['missing_yfinance'])}", expanded=False):
    st.caption("Yahoo is never used for an index history, so this affects no signal; it only means no secondary "
               "cross-check series exists.")
    st.write(", ".join(sorted(names.get(e, e) for e in health["missing_yfinance"])) or "None.")
