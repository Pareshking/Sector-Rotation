from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import load_strategy_config
from src.data.cache import write_parquet
from src.data.calendar import TradingCalendar
from src.data.canonical import promote_etf_histories
from src.data.contracts import enforce

# Importing etf_data pulls in src.data._jugaad_patches (via nse_equity), which
# installs a socket timeout and widens jugaad-data's date-chunking before any
# NSE fetch runs. See that module for why both are necessary.
from src.data.etf_data import fetch_etf_histories
from src.data.ingest import (
    BENCHMARK_ID,
    IndexSource,
    ingest_cash,
    ingest_indices,
    ingest_vehicles,
    restatements,
    update_index,
)
from src.data.nse_etf import (
    COLUMNS as SNAPSHOT_COLUMNS,
    SnapshotResolution,
    fetch_etf_snapshot,
    load_last_snapshot,
    merge_snapshot,
    resolve_snapshot,
)
from src.data.store import DEFAULT_OVERLAP_SESSIONS, RawStore
from src.models.exposure import IndexProvider
from src.portfolio.live import live_portfolio, target_frame
from src.portfolio.score import score_exposures
from src.portfolio.universe import (
    backcalculated_mask,
    build_universe_metadata,
    inception_conflicts,
)
from src.quantitative.analytics import analyse_exposure
from src.quantitative.quality import check_dataset
from src.quantitative.ranking import rank_exposures
from src.quantitative.relative_strength import (
    mansfield_relative_strength,
    rs_momentum,
    rs_ratio,
    rs_stage,
)
from src.quantitative.validation import validate_price_matrix, validate_returns
from src.universe.registry import UniverseRegistry
from src.universe.validation import validate_universe

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_PATH = ROOT / "data" / "universe" / "universe.json"
OUTPUT = ROOT / "data" / "processed"
# The append-only archive. Committed by the nightly workflow alongside
# data/processed, so each run extends it instead of starting again.
STORE_ROOT = ROOT / "data" / "raw"
# The last snapshot NSE actually served, kept so a refused fetch carries it forward.
SNAPSHOT_PATH = STORE_ROOT / "snapshot" / "nse_etf.parquet"

MIN_DECISION_OBSERVATIONS = 250
MIN_PROMOTION_OBSERVATIONS = 60
SEED_YEARS = 5
BENCHMARK_COLUMN = "__benchmark__"

# NSE index history through the jugaad-data retrieval adapter, BSE index
# history from BSE Index Services (BSE's own index arm, for exposures marked
# ``index_provider: "bse"``), plus explicitly mapped ETF/NAV series for
# exposures NSE cannot serve. Nothing else is decision-grade.
AUTHORITATIVE_CANONICAL_SOURCES = {
    "niftyindices_jugaad",
    "bseindices",
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


def _index_sources(registry) -> dict[str, IndexSource]:
    """Exposures whose index is not NSE's, with the provider identifiers to fetch them by."""
    return {
        e.id: IndexSource(e.index_provider.value, int(e.index_source_id), str(e.index_code))
        for e in registry.all()
        if e.index_provider is not IndexProvider.NSE
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
                    "inception_date": pd.Timestamp(etf.inception_date) if etf.inception_date else pd.NaT,
                    "inception_source": etf.inception_source,
                    "aum_crore": etf.tracking.aum_crore,
                    "expense_ratio": etf.tracking.expense_ratio,
                    "liquidity_score": etf.tracking.liquidity_score,
                    "tracking_error": etf.tracking.tracking_error,
                }
            )
    frame = pd.DataFrame(rows)
    frame["inception_date"] = pd.to_datetime(frame["inception_date"])
    frame["scheme_code"] = frame["scheme_code"].astype("Int64")
    return frame


def _cash_info(strategy, cash: pd.Series, report=None) -> dict:
    proxy = strategy.cash_proxy
    info = {
        "scheme_code": proxy.scheme_code if proxy else None,
        "name": proxy.name if proxy else None,
        "fallback_rate_annual": strategy.risk_free_rate_annual,
        "first_nav": f"{cash.index.min():%Y-%m-%d}" if cash is not None and not cash.empty else None,
        "last_nav": f"{cash.index.max():%Y-%m-%d}" if cash is not None and not cash.empty else None,
    }
    if report is not None:
        info.update(report.as_dict())
    return info


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
    # A liquid fund publishes a NAV every calendar day, compounding steadily.
    days_index = pd.date_range(dates[0], dates[-1], freq="D")
    elapsed = (days_index - days_index[0]).days.to_numpy() / 365.25
    cash = pd.Series(1000.0 * 1.065**elapsed, index=days_index, name="nav")
    total = len(registry.all())
    # The same lineage a live run records: BSE indices are price-only.
    bse = {e.id for e in registry.all() if e.index_provider is IndexProvider.BSE}
    sources = {e.id: "bseindices" if e.id in bse else "niftyindices_jugaad" for e in registry.all()}
    health = {
        "total_canonical_exposures": total,
        "valid_canonical_series": total,
        "skipped_canonical_series": 0,
        "canonical_coverage_ratio": 1.0,
        "fallback_canonical_exposures": [],
        "skipped_canonical_exposures": [],
        "missing_yfinance_symbols": [],
        "source_counts": {
            **{s: sum(v == s for v in sources.values()) for s in sorted(set(sources.values()))},
            "mfapi": int(etf_prices.shape[1]),
        },
        "source_by_canonical_exposure": sources,
        "value_type_by_canonical_exposure": {e.id: "CLOSE" if e.id in bse else "TRI" for e in registry.all()},
        "benchmark_source": "niftyindices_jugaad",
        "benchmark_value_type": "TRI",
        "canonical_fetch_errors": {},
        "etf_total": int(etf_prices.shape[1]),
        "etf_valid_series": int(etf_prices.shape[1]),
        "etf_coverage_ratio": 1.0,
        "etf_skipped_symbols": [],
        "resolved_official_index_names": {e.id: e.benchmark for e in registry.all()},
        "ingest": {"mode": "fixture"},
        "restatements": [],
    }
    return pd.DataFrame(columns), benchmark, _etf_frame(registry), etf_prices, cash, health


def _load_existing_etf_artifacts():
    """Reuse the ETF artifacts already on disk instead of re-downloading them.

    Index and ETF ingestion fail independently: NSE index history can be
    refreshed when Yahoo/AMFI are unreachable, and re-running the whole pipeline
    just to pick up an index change would overwrite good ETF data with a
    degraded fetch.
    """
    prices_path = OUTPUT / "etf_prices.parquet"
    history = pd.read_parquet(prices_path) if prices_path.exists() else pd.DataFrame()
    metadata_path = OUTPUT / "metadata.json"
    sources, codes = {}, {}
    if metadata_path.exists():
        existing = json.loads(metadata_path.read_text(encoding="utf-8"))
        sources = existing.get("etf_source_by_symbol", {}) or {}
        codes = existing.get("resolved_mfapi_scheme_codes", {}) or {}
    return history, sources, codes


def _stage(message: str) -> None:
    import sys
    import time

    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def build_live(
    registry,
    strategy,
    skip_etf: bool = False,
    store_root: Path = STORE_ROOT,
    seed_years: int = SEED_YEARS,
    overlap: int = DEFAULT_OVERLAP_SESSIONS,
    today: date | None = None,
):
    """Extend the raw store from NSE / MFAPI / AMFI and return the full stored histories."""
    today = today or date.today()
    store = RawStore(store_root)
    exposure_names = {e.id: e.benchmark for e in registry.all()}
    etf_objects = [etf for e in registry.all() for etf in e.etfs]

    # The benchmark comes first: its sessions are the calendar every exposure
    # is checked against for missing or truncated request chunks.
    _stage("Updating the benchmark...")
    benchmark, bench_report = update_index(
        store, BENCHMARK_ID, registry.benchmark_name.upper(), today, seed_years, overlap, is_benchmark=True
    )
    if benchmark.dropna().empty:
        raise RuntimeError(
            f"Unable to obtain Nifty 50 benchmark history: {bench_report.error or 'no usable history'}"
        )
    calendar = TradingCalendar.from_series(benchmark)

    if skip_etf:
        _stage("Reusing existing ETF artifacts (--skip-etf)")
        etf_fetched, etf_sources, resolved_codes = _load_existing_etf_artifacts()
    else:
        etf_fetched, etf_sources, resolved_codes = fetch_etf_histories(etf_objects, years=seed_years)
    scheme_codes = {etf.symbol or etf.name: etf.scheme_code for etf in etf_objects if etf.scheme_code}
    etf_history, vehicle_reports = ingest_vehicles(store, etf_fetched, etf_sources, scheme_codes)
    stored_sources = {key: r.source for key, r in vehicle_reports.items() if r.source}

    _stage("Updating canonical index histories...")
    prices, index_reports = ingest_indices(
        store, exposure_names, calendar, today, seed_years, overlap, index_sources=_index_sources(registry)
    )
    source_by_exposure = {eid: r.source for eid, r in index_reports.items() if eid in prices and r.source}
    value_types = {eid: r.value_type for eid, r in index_reports.items() if eid in prices and r.value_type}
    resolved_names = {eid: exposure_names[eid] for eid in prices.columns}
    fetch_errors = {eid: r.error for eid, r in index_reports.items() if r.error}

    missing = {
        eid: name
        for eid, name in exposure_names.items()
        if eid not in prices or prices[eid].dropna().size < MIN_PROMOTION_OBSERVATIONS
    }
    if missing:
        promoted, promoted_sources, promoted_resolved = promote_etf_histories(
            missing, etf_history, PRIMARY_CANONICAL_ETF_BY_EXPOSURE
        )
        for eid, series in promoted.items():
            prices = prices.drop(columns=[eid], errors="ignore").join(series, how="outer")
            source_by_exposure[eid] = promoted_sources[eid]
            resolved_names[eid] = promoted_resolved[eid]
            value_types[eid] = "NAV"
    non_authoritative = [
        eid for eid in list(prices.columns) if source_by_exposure.get(eid) not in AUTHORITATIVE_CANONICAL_SOURCES
    ]
    if non_authoritative:
        prices = prices.drop(columns=non_authoritative, errors="ignore")

    cash = pd.Series(dtype=float, name="nav")
    cash_report = None
    if strategy.cash_proxy is not None:
        _stage("Updating the cash proxy (liquid fund NAV)...")
        cash, cash_report = ingest_cash(store, strategy.cash_proxy.scheme_code, strategy.cash_proxy.name)

    valid = [
        e.id for e in registry.all() if e.id in prices and prices[e.id].dropna().size >= MIN_DECISION_OBSERVATIONS
    ]
    skipped = [e.id for e in registry.all() if e.id not in valid]
    # Counted from what actually resolved.
    source_counts = {
        source: sum(v == source for v in source_by_exposure.values())
        for source in sorted(set(source_by_exposure.values()))
    }
    for etf_source in sorted(set(stored_sources.values())):
        source_counts[f"etf:{etf_source}"] = sum(v == etf_source for v in stored_sources.values())

    etf_keys = [etf.symbol or etf.name for etf in etf_objects]
    etf_valid = sum(k in etf_history and etf_history[k].dropna().size >= 20 for k in etf_keys)
    all_reports = {"__benchmark__": bench_report, **index_reports, **vehicle_reports}
    if cash_report is not None:
        all_reports["__cash__"] = cash_report
    health = {
        "total_canonical_exposures": len(registry.all()),
        "valid_canonical_series": len(valid),
        "skipped_canonical_series": len(skipped),
        "canonical_coverage_ratio": len(valid) / max(len(registry.all()), 1),
        "fallback_canonical_exposures": [
            eid for eid, source in source_by_exposure.items() if source not in AUTHORITATIVE_CANONICAL_SOURCES
        ],
        "skipped_canonical_exposures": skipped,
        "missing_yfinance_symbols": [e.id for e in registry.all() if not e.yfinance_symbol],
        "source_counts": source_counts,
        "source_by_canonical_exposure": source_by_exposure,
        "value_type_by_canonical_exposure": value_types,
        "benchmark_source": bench_report.source or "unknown",
        "benchmark_value_type": bench_report.value_type or "UNKNOWN",
        "canonical_fetch_errors": fetch_errors,
        "resolved_official_index_names": resolved_names,
        "etf_total": len(etf_objects),
        "etf_valid_series": etf_valid,
        "etf_coverage_ratio": etf_valid / max(len(etf_objects), 1),
        "etf_skipped_symbols": [k for k in etf_keys if k not in etf_history or etf_history[k].dropna().size < 20],
        "etf_source_by_symbol": stored_sources,
        "resolved_mfapi_scheme_codes": resolved_codes,
        "ingest": {
            "store": "data/raw",
            "overlap_sessions": overlap,
            "seed_years": seed_years,
            "benchmark": bench_report.as_dict(),
            "indices": {eid: r.as_dict() for eid, r in sorted(index_reports.items())},
            "vehicles_fetch_failed": sorted(k for k, r in vehicle_reports.items() if r.error),
        },
        "restatements": restatements(all_reports),
        "_cash_report": cash_report,
    }
    return prices, benchmark, _etf_frame(registry), etf_history, cash, health


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


def price_input_problems(prices: pd.DataFrame, benchmark: pd.Series) -> list[str]:
    """Everything wrong with the ranking inputs; empty when they are usable.

    Ranking, relative strength and the backtest all assume positive, unique,
    dated prices. A zero or negative level, a duplicated date or an infinite
    return would flow straight into every Z-score, so the run stops instead.
    """
    problems: list[str] = []
    for label, frame in (
        ("canonical index panel", prices),
        ("benchmark", benchmark.to_frame("benchmark")),
    ):
        problems += [f"{label}: {m}" for m in validate_price_matrix(frame)]
        problems += [
            f"{label}: {m}" for m in validate_returns(frame.pct_change(fill_method=None))
        ]
    return problems


def run(
    mode,
    skip_etf: bool = False,
    strict: bool = False,
    store_root: Path | None = None,
    seed_years: int = SEED_YEARS,
    overlap: int = DEFAULT_OVERLAP_SESSIONS,
):
    registry = UniverseRegistry.from_json(UNIVERSE_PATH)
    report = validate_universe(registry.all())
    if not report.valid:
        raise ValueError("Invalid universe: " + "; ".join(report.errors))
    strategy = load_strategy_config()
    if mode == "fixture":
        prices, benchmark, etfs, etf_history, cash, health = build_fixture(registry)
    elif mode == "live":
        _stage(f"Pipeline starting: {len(registry.all())} exposures, live mode")
        prices, benchmark, etfs, etf_history, cash, health = build_live(
            registry, strategy, skip_etf=skip_etf, store_root=store_root or STORE_ROOT,
            seed_years=seed_years, overlap=overlap,
        )
    else:
        raise ValueError("mode must be fixture or live")
    cash_report = health.pop("_cash_report", None)

    common = prices.index.intersection(benchmark.dropna().index)
    prices = prices.loc[common].sort_index()
    benchmark = benchmark.loc[common].sort_index()
    if prices.empty:
        raise RuntimeError("No overlapping authoritative benchmark/exposure history was downloaded")
    problems = price_input_problems(prices, benchmark)
    if problems:
        raise ValueError("Price validation failed before ranking: " + "; ".join(problems))
    etf_problems = (
        [f"ETF price history: {m}" for m in validate_price_matrix(etf_history)]
        if not etf_history.empty
        else []
    )

    _stage("Ranking and computing durability analytics...")
    meta = build_universe_metadata(prices.columns, registry)
    backcalculated = backcalculated_mask(prices, meta)
    # Absolute and relative returns per horizon, for display. The rank and score
    # are the strategy's own (src/config/strategy.json) as of the latest session,
    # so the board ranks on exactly what the portfolio is built from.
    rankings = rank_exposures(prices, benchmark)
    board = score_exposures(prices, prices.index.max(), strategy)
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
        observed = asset.notna()
        summary_rows.append(
            {
                "exposure_id": exposure.id,
                "exposure": exposure.name,
                "category": exposure.category.value,
                "benchmark": exposure.benchmark,
                "resolved_official_index_name": health.get("resolved_official_index_names", {}).get(
                    exposure.id, exposure.benchmark
                ),
                "data_source": health.get("source_by_canonical_exposure", {}).get(exposure.id, "unknown"),
                "value_type": health.get("value_type_by_canonical_exposure", {}).get(exposure.id, "UNKNOWN"),
                "launch_date": pd.Timestamp(exposure.launch_date) if exposure.launch_date else pd.NaT,
                "base_date": pd.Timestamp(exposure.base_date) if exposure.base_date else pd.NaT,
                # Share of the stored history that predates the index's launch.
                "backcalculated_share": (
                    float(backcalculated[exposure.id][observed].mean()) if observed.any() else np.nan
                ),
                "rs_ratio": latest_ratio,
                "rs_momentum": latest_momentum,
                "stage": rs_stage(latest_ratio, latest_momentum),
                "momentum_z": board.at[exposure.id, "score"],
                "rank": board.at[exposure.id, "universe_rank"],
                **{f"return_{label}": rank_row[f"return_{label}"] for label in ("1M", "3M", "6M", "12M")},
                **{f"relative_{label}": rank_row[f"relative_{label}"] for label in ("1M", "3M", "6M", "12M")},
                **_analytics_columns(asset, benchmark),
            }
        )

    summary = pd.DataFrame(summary_rows)
    summary["rank"] = summary["rank"].astype("Int64")
    summary["momentum_z"] = summary["momentum_z"].astype(float)
    summary["launch_date"] = pd.to_datetime(summary["launch_date"])
    summary["base_date"] = pd.to_datetime(summary["base_date"])
    summary = summary.sort_values("rank", na_position="last", kind="mergesort")
    # Liquidity and premium/discount decide whether a signal is actually
    # actionable. Best-effort: a snapshot failure must not fail a run that
    # already produced valid index history. NSE intermittently refuses GitHub's
    # runners, so a refused fetch carries the last good snapshot forward
    # rather than publishing blanks over it.
    if mode == "live":
        _stage("Fetching the NSE ETF snapshot...")
        fresh, snapshot_error = fetch_etf_snapshot()
        snapshot = resolve_snapshot(fresh, snapshot_error, load_last_snapshot(SNAPSHOT_PATH))
        if snapshot.status != "fresh":
            _stage(f"NSE ETF snapshot {snapshot.status}: {snapshot.error}")
    else:
        snapshot = SnapshotResolution(pd.DataFrame(columns=SNAPSHOT_COLUMNS), "skipped", None)
    etfs = merge_snapshot(etfs, snapshot.snapshot)
    is_etf = etfs["vehicle"].eq("etf") if "vehicle" in etfs else pd.Series(True, index=etfs.index)
    snapshot_report = snapshot.report(
        matched=int(pd.to_numeric(etfs.loc[is_etf, "traded_value"], errors="coerce").notna().sum()),
        total=int(is_etf.sum()),
    )

    # The canonical price panel is what makes an out-of-sample backtest possible.
    index_panel = prices.copy()
    index_panel[BENCHMARK_COLUMN] = benchmark
    index_panel = index_panel.sort_index()
    cash_frame = cash.dropna().sort_index().to_frame("nav") if cash is not None else pd.DataFrame(columns=["nav"])

    _stage("Building the target portfolio...")
    live = live_portfolio(prices, meta, strategy, cash.dropna() if cash is not None and not cash.empty else None)
    if live is None:
        raise RuntimeError("No completed rebalance date in the panel; cannot build a target portfolio")
    target = target_frame(live.target)

    metadata = {
        "mode": mode,
        "etf_ingestion": "reused" if (mode == "live" and skip_etf) else "refreshed",
        "benchmark": registry.benchmark_name,
        "strategy_version": strategy.version,
        "strategy_hash": strategy.config_hash,
        "strategy": strategy.model_dump(mode="json"),
        "last_updated_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "observations": int(len(prices)),
        "valid_series": int(prices.shape[1]),
        "etf_series": int(etf_history.shape[1]),
        "coverage_ratio": float(prices.shape[1] / max(len(registry.all()), 1)),
        "index_panel_start": str(index_panel.index.min().date()),
        "index_panel_end": str(index_panel.index.max().date()),
        "validation_warnings": list(report.warnings) + etf_problems,
        "inception_conflicts": inception_conflicts(registry, etf_history),
        "cash_proxy": _cash_info(strategy, cash, cash_report),
        "etf_snapshot": snapshot_report,
        "target_portfolio": {
            "as_of": f"{live.target.as_of:%Y-%m-%d}",
            "next_rebalance": f"{live.next_rebalance:%Y-%m-%d}",
            "weights": dict(live.target.weights),
            "cash_hurdle_12m": live.target.cash_hurdle_12m,
            "cash_hurdle_source": live.target.cash_hurdle_source,
        },
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

    # Fail closed: nothing is written unless every artifact meets its contract.
    frames = {
        "summary_rankings": summary,
        "etf_universe": etfs,
        "etf_prices": etf_history,
        "index_prices": index_panel,
        "cash_nav": cash_frame,
        "portfolio_target": target,
    }
    enforce(frames, metadata)

    _stage("Writing outputs...")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_parquet(summary, OUTPUT / "summary_rankings.parquet")
    write_parquet(pd.DataFrame(rs_series).sort_index(), OUTPUT / "rs_matrix.parquet")
    write_parquet(etfs, OUTPUT / "etf_universe.parquet")
    if snapshot.status == "fresh":
        write_parquet(snapshot.snapshot.reset_index(drop=True), SNAPSHOT_PATH)
    write_parquet(etf_history, OUTPUT / "etf_prices.parquet")
    write_parquet(index_panel, OUTPUT / "index_prices.parquet")
    write_parquet(cash_frame, OUTPUT / "cash_nav.parquet")
    write_parquet(target, OUTPUT / "portfolio_target.parquet")
    previous_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    for alert in quality.sorted_alerts():
        print(f"[{alert['severity'].upper()}] {alert['check']}: {alert['message']}")
    print(json.dumps(metadata, default=str))
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
    parser.add_argument("--seed-years", type=int, default=SEED_YEARS,
                        help="History to fetch for a series the store has never seen.")
    parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP_SESSIONS,
                        help="Stored sessions re-fetched on every run to detect restatements.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    run(args.mode, skip_etf=args.skip_etf, strict=args.strict, seed_years=args.seed_years, overlap=args.overlap)
