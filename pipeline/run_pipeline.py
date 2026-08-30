from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.cache import write_parquet
from src.data.etf_data import fetch_etf_histories
from src.data.index_data import download_benchmark, download_canonical_indices
from src.data.nse_etf import fetch_etf_snapshot, merge_snapshot
from src.quantitative.analytics import analyse_exposure
from src.quantitative.quality import check_dataset
from src.quantitative.ranking import normalise_weights, rank_exposures
from src.quantitative.relative_strength import (
    mansfield_relative_strength,
    rs_momentum,
    rs_ratio,
    rs_stage,
)
from src.universe.registry import UniverseRegistry
from src.universe.validation import validate_universe

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_PATH = ROOT / "data" / "universe" / "universe.json"
OUTPUT = ROOT / "data" / "processed"

MIN_DECISION_OBSERVATIONS = 250
BENCHMARK_COLUMN = "__benchmark__"

# NSE index history through the jugaad-data retrieval adapter, plus explicitly
# mapped ETF/NAV series for exposures NSE cannot serve. Nothing else is
# decision-grade.
AUTHORITATIVE_CANONICAL_SOURCES = {
    "niftyindices_jugaad",
    "etf_nav_authoritative",
}

# Deliberately explicit: every mapping was selected because the ETF tracks the
# same sector/thematic exposure. Never replace this with a nearest-symbol or
# nearest-category heuristic (e.g. Auto must never stand in for Capital Goods).
PRIMARY_CANONICAL_ETF_BY_EXPOSURE = {
    "auto": "AUTOBEES",
    "bank": "BANKBEES",
    "financial-services": "BFSI",
    "fmcg": "FMCGIETF",
    "healthcare": "HEALTHIETF",
    "it": "ITBEES",
    "metal": "METALIETF",
    "pharma": "PHARMABEES",
    "psu-bank": "PSUBNKBEES",
    "defence": "GROWWDEFNC",
    "ev-new-energy-auto": "EVINDIA",
    "manufacturing": "MAKEINDIA",
    "infrastructure": "INFRABEES",
    "consumption": "CONSUMBEES",
    "internet": "GROWWNET",
    "mnc": "MNC",
    "pse": "MOPSE",
    "cpse": "CPSEETF",
}


def _etf_frame(registry):
    rows = []
    for exposure in registry.all():
        for etf in exposure.etfs:
            rows.append(
                {
                    "exposure_id": exposure.id,
                    "exposure": exposure.name,
                    "category": exposure.category.value,
                    "symbol": etf.symbol,
                    "name": etf.name,
                    "vehicle": etf.vehicle.value,
                    "scheme_code": etf.scheme_code,
                    "yfinance_symbol": etf.yfinance_symbol,
                    "aliases": ",".join(etf.aliases),
                    "aum_crore": etf.tracking.aum_crore,
                    "expense_ratio": etf.tracking.expense_ratio,
                    "liquidity_score": etf.tracking.liquidity_score,
                    "tracking_error": etf.tracking.tracking_error,
                }
            )
    return pd.DataFrame(rows)


def build_fixture(registry, days=1300):
    rng = np.random.default_rng(42)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    benchmark = pd.Series(
        100 * np.exp(np.cumsum(rng.normal(0.00035, 0.008, len(dates)))),
        index=dates,
        name=registry.benchmark_name,
    )
    columns = {
        e.id: pd.Series(
            100 * np.exp(np.cumsum(rng.normal(0.00015 + (i % 7) * 0.00003, 0.011, len(dates)))),
            index=dates,
        )
        for i, e in enumerate(registry.all())
    }
    etf_prices = pd.DataFrame(
        {
            etf.symbol or etf.name: pd.Series(
                100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, len(dates)))), index=dates
            )
            for e in registry.all()
            for etf in e.etfs
        }
    )
    total = len(registry.all())
    health = {
        "total_canonical_exposures": total,
        "valid_canonical_series": total,
        "skipped_canonical_series": 0,
        "canonical_coverage_ratio": 1.0,
        "fallback_canonical_exposures": [],
        "skipped_canonical_exposures": [],
        "missing_yfinance_symbols": [],
        "source_counts": {"niftyindices_jugaad": total, "mfapi": int(etf_prices.shape[1])},
        "source_by_canonical_exposure": {e.id: "niftyindices_jugaad" for e in registry.all()},
        "value_type_by_canonical_exposure": {e.id: "TRI" for e in registry.all()},
        "etf_total": int(etf_prices.shape[1]),
        "etf_valid_series": int(etf_prices.shape[1]),
        "etf_coverage_ratio": 1.0,
        "etf_skipped_symbols": [],
        "resolved_official_index_names": {e.id: e.benchmark for e in registry.all()},
    }
    return pd.DataFrame(columns), benchmark, _etf_frame(registry), etf_prices, health


def _load_existing_etf_artifacts():
    """Reuse the ETF artifacts already on disk instead of re-downloading them.

    Index and ETF ingestion fail independently: NSE index history can be
    refreshed when Yahoo/AMFI are unreachable, and re-running the whole pipeline
    just to pick up an index change would overwrite good ETF data with a
    degraded fetch.
    """
    import pandas as pd

    prices_path = OUTPUT / "etf_prices.parquet"
    history = pd.read_parquet(prices_path) if prices_path.exists() else pd.DataFrame()
    metadata_path = OUTPUT / "metadata.json"
    sources, codes = {}, {}
    if metadata_path.exists():
        existing = json.loads(metadata_path.read_text(encoding="utf-8"))
        sources = existing.get("etf_source_by_symbol", {}) or {}
        codes = existing.get("resolved_mfapi_scheme_codes", {}) or {}
    return history, sources, codes


def build_live(registry, skip_etf: bool = False):
    exposure_names = {e.id: e.benchmark for e in registry.all()}
    etf_objects = [etf for e in registry.all() for etf in e.etfs]
    if skip_etf:
        etf_history, etf_sources, resolved_codes = _load_existing_etf_artifacts()
    else:
        etf_history, etf_sources, resolved_codes = fetch_etf_histories(etf_objects, years=5)
    prices = download_canonical_indices(
        exposure_names,
        years=5,
        etf_histories=etf_history,
        canonical_etf_keys=PRIMARY_CANONICAL_ETF_BY_EXPOSURE,
    )
    source_by_exposure = dict(prices.attrs.get("source_by_exposure", {}))
    resolved_names = dict(prices.attrs.get("resolved_name_by_exposure", {}))
    value_types = dict(prices.attrs.get("value_type_by_exposure", {}))

    non_authoritative = [
        eid
        for eid in list(prices.columns)
        if source_by_exposure.get(eid) not in AUTHORITATIVE_CANONICAL_SOURCES
    ]
    if non_authoritative:
        prices = prices.drop(columns=non_authoritative, errors="ignore")

    benchmark = download_benchmark(registry.benchmark_name.upper(), years=5)
    if benchmark.dropna().empty:
        raise RuntimeError("Unable to download Nifty 50 benchmark history")

    valid = [
        e.id
        for e in registry.all()
        if e.id in prices and prices[e.id].dropna().size >= MIN_DECISION_OBSERVATIONS
    ]
    skipped = [e.id for e in registry.all() if e.id not in valid]

    # Counted from what actually resolved. The previous hard-coded key list
    # omitted the adapter that serves every exposure, so System Health reported
    # zero canonical sources while 43 were present.
    source_counts = {
        source: sum(v == source for v in source_by_exposure.values())
        for source in sorted(set(source_by_exposure.values()))
    }
    for etf_source in sorted(set(etf_sources.values())):
        source_counts[f"etf:{etf_source}"] = sum(v == etf_source for v in etf_sources.values())

    etf_keys = [etf.symbol or etf.name for etf in etf_objects]
    etf_valid = sum(k in etf_history and etf_history[k].dropna().size >= 20 for k in etf_keys)
    health = {
        "total_canonical_exposures": len(registry.all()),
        "valid_canonical_series": len(valid),
        "skipped_canonical_series": len(skipped),
        "canonical_coverage_ratio": len(valid) / max(len(registry.all()), 1),
        "fallback_canonical_exposures": [
            eid
            for eid, source in source_by_exposure.items()
            if source not in AUTHORITATIVE_CANONICAL_SOURCES
        ],
        "skipped_canonical_exposures": skipped,
        "missing_yfinance_symbols": [e.id for e in registry.all() if not e.yfinance_symbol],
        "source_counts": source_counts,
        "source_by_canonical_exposure": source_by_exposure,
        "value_type_by_canonical_exposure": value_types,
        "resolved_official_index_names": resolved_names,
        "etf_total": len(etf_objects),
        "etf_valid_series": etf_valid,
        "etf_coverage_ratio": etf_valid / max(len(etf_objects), 1),
        "etf_skipped_symbols": [
            k for k in etf_keys if k not in etf_history or etf_history[k].dropna().size < 20
        ],
        "etf_source_by_symbol": etf_sources,
        "resolved_mfapi_scheme_codes": resolved_codes,
    }
    return prices, benchmark, _etf_frame(registry), etf_history, health


def _analytics_columns(asset, benchmark) -> dict[str, float]:
    """Durability metrics, precomputed so the UI stays cheap.

    A rank says which exposure is strongest today. These say whether that
    strength has held up, and whether it is strength or just beta.
    """
    stats = analyse_exposure(asset, benchmark)
    risk = stats.risk.get("3Y", {})
    rolling = stats.rolling.get("3Y", {})
    consistency = stats.consistency.get("1Y", {})
    return {
        "alpha": stats.versus.get("alpha"),
        "beta": stats.versus.get("beta"),
        "r_squared": stats.versus.get("r2"),
        "information_ratio": stats.versus.get("information_ratio"),
        "tracking_error": stats.versus.get("error"),
        "volatility_3y": risk.get("volatility"),
        "sharpe_3y": risk.get("sharpe"),
        "sortino_3y": risk.get("sortino"),
        "rolling_3y_median": rolling.get("median"),
        "rolling_3y_min": rolling.get("min"),
        "rolling_3y_positive": rolling.get("positive"),
        "consistency_overall": consistency.get("overall"),
        "consistency_upside": consistency.get("upside"),
        "consistency_downside": consistency.get("downside"),
        "max_drawdown": stats.drawdown.get("depth"),
        "drawdown_from_high": stats.drawdown.get("current"),
    }


def run(mode, skip_etf: bool = False, strict: bool = False):
    registry = UniverseRegistry.from_json(UNIVERSE_PATH)
    report = validate_universe(registry.all())
    if not report.valid:
        raise ValueError("Invalid universe: " + "; ".join(report.errors))
    if mode == "fixture":
        prices, benchmark, etfs, etf_history, health = build_fixture(registry)
    elif mode == "live":
        prices, benchmark, etfs, etf_history, health = build_live(registry, skip_etf=skip_etf)
    else:
        raise ValueError("mode must be fixture or live")

    common = prices.index.intersection(benchmark.dropna().index)
    prices = prices.loc[common].sort_index()
    benchmark = benchmark.loc[common].sort_index()
    if prices.empty:
        raise RuntimeError("No overlapping authoritative benchmark/exposure history was downloaded")

    rankings = rank_exposures(prices, benchmark, weights=registry.momentum_weights)
    summary_rows = []
    rs_series = {}
    for exposure in registry.all():
        if exposure.id not in prices:
            continue
        asset = prices[exposure.id]
        mrs = mansfield_relative_strength(asset, benchmark)
        ratio = rs_ratio(asset, benchmark)
        momentum = rs_momentum(mrs)
        rs_series[exposure.id] = mrs
        latest_ratio = ratio.dropna().iloc[-1] if not ratio.dropna().empty else np.nan
        latest_momentum = momentum.dropna().iloc[-1] if not momentum.dropna().empty else np.nan
        rank_row = rankings.loc[exposure.id]
        summary_rows.append(
            {
                "exposure_id": exposure.id,
                "exposure": exposure.name,
                "category": exposure.category.value,
                "benchmark": exposure.benchmark,
                "resolved_official_index_name": health.get("resolved_official_index_names", {}).get(
                    exposure.id, exposure.benchmark
                ),
                "data_source": health.get("source_by_canonical_exposure", {}).get(
                    exposure.id, "unknown"
                ),
                "value_type": health.get("value_type_by_canonical_exposure", {}).get(
                    exposure.id, "UNKNOWN"
                ),
                "rs_ratio": latest_ratio,
                "rs_momentum": latest_momentum,
                "stage": rs_stage(latest_ratio, latest_momentum),
                "momentum_z": rank_row["momentum_z"],
                "rank": rank_row["rank"],
                **{
                    f"return_{label}": rank_row[f"return_{label}"]
                    for label in ("1M", "3M", "6M", "12M")
                },
                **{
                    f"relative_{label}": rank_row[f"relative_{label}"]
                    for label in ("1M", "3M", "6M", "12M")
                },
                **_analytics_columns(asset, benchmark),
            }
        )

    summary = pd.DataFrame(summary_rows).sort_values("rank")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_parquet(summary, OUTPUT / "summary_rankings.parquet")
    write_parquet(pd.DataFrame(rs_series).sort_index(), OUTPUT / "rs_matrix.parquet")
    # Liquidity and premium/discount decide whether a signal is actually
    # actionable. Best-effort: a snapshot failure must not fail a run that
    # already produced valid index history.
    etfs = merge_snapshot(etfs, fetch_etf_snapshot() if mode == "live" else None)
    write_parquet(etfs, OUTPUT / "etf_universe.parquet")
    write_parquet(etf_history, OUTPUT / "etf_prices.parquet")

    # The canonical price panel is what makes an out-of-sample backtest possible.
    # Without it the app can only ever describe the present ranking.
    index_panel = prices.copy()
    index_panel[BENCHMARK_COLUMN] = benchmark
    write_parquet(index_panel.sort_index(), OUTPUT / "index_prices.parquet")

    metadata = {
        "mode": mode,
        "etf_ingestion": "reused" if (mode == "live" and skip_etf) else "refreshed",
        "benchmark": registry.benchmark_name,
        "momentum_weights": normalise_weights(registry.momentum_weights),
        "benchmark_source": "niftyindices_jugaad",
        "last_updated_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "observations": int(len(prices)),
        "valid_series": int(prices.shape[1]),
        "etf_series": int(etf_history.shape[1]),
        "coverage_ratio": float(prices.shape[1] / max(len(registry.all()), 1)),
        "index_panel_start": str(index_panel.index.min().date()),
        "index_panel_end": str(index_panel.index.max().date()),
        "validation_warnings": list(report.warnings),
        **health,
    }
    # Compare against the last published run before overwriting it. A run that
    # is internally consistent can still be worse than the one it replaces.
    previous_path = OUTPUT / "metadata.json"
    previous = {}
    if previous_path.exists():
        try:
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
    quality = check_dataset(metadata, previous, index_panel, etf_history)
    metadata["quality_alerts"] = quality.sorted_alerts()

    previous_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    for alert in quality.sorted_alerts():
        print(f"[{alert['severity'].upper()}] {alert['check']}: {alert['message']}")
    print(json.dumps(metadata))
    if strict and not quality.ok:
        raise SystemExit(
            f"Data-quality check failed with {len(quality.errors)} error(s); dataset written but not clean."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the Sector-Rotation prepared dataset")
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument(
        "--skip-etf",
        action="store_true",
        help="Refresh index data only, reusing the ETF artifacts already in data/processed.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when a data-quality check reports an error.",
    )
    args = parser.parse_args()
    run(args.mode, skip_etf=args.skip_etf, strict=args.strict)
