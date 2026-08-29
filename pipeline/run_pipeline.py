from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.cache import write_parquet
from src.data.index_data import download_history
from src.quantitative.relative_strength import mansfield_relative_strength, rs_momentum, rs_ratio, rs_stage
from src.quantitative.ranking import rank_exposures
from src.universe.registry import UniverseRegistry
from src.universe.validation import validate_universe

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_PATH = ROOT / "data" / "universe" / "universe.json"
OUTPUT = ROOT / "data" / "processed"


def build_fixture(registry: UniverseRegistry, days: int = 1300) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(42)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    benchmark = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.00035, 0.008, len(dates)))), index=dates, name=registry.benchmark_name)
    columns: dict[str, pd.Series] = {}
    for i, exposure in enumerate(registry.all()):
        drift = 0.00015 + (i % 7) * 0.00003
        noise = rng.normal(drift, 0.011, len(dates))
        columns[exposure.id] = pd.Series(100 * np.exp(np.cumsum(noise)), index=dates)
    return pd.DataFrame(columns), benchmark


def build_live(registry: UniverseRegistry) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    benchmark = download_history([registry.benchmark_symbol], years=5).iloc[:, 0]
    symbols = {exposure.id: exposure.yfinance_symbol for exposure in registry.all() if exposure.yfinance_symbol}
    history = download_history(symbols.values(), years=5)
    reverse = {symbol: exposure_id for exposure_id, symbol in symbols.items()}
    history = history.rename(columns=reverse)
    return history, benchmark, _etf_frame(registry)


def _etf_frame(registry: UniverseRegistry) -> pd.DataFrame:
    rows: list[dict[str, str | float | None]] = []
    for exposure in registry.all():
        for etf in exposure.etfs:
            rows.append({"exposure_id": exposure.id, "exposure": exposure.name, "category": exposure.category.value, "symbol": etf.symbol, "name": etf.name, "yfinance_symbol": etf.yfinance_symbol, "aum_crore": etf.tracking.aum_crore, "expense_ratio": etf.tracking.expense_ratio, "liquidity_score": etf.tracking.liquidity_score, "tracking_error": etf.tracking.tracking_error})
    return pd.DataFrame(rows)


def run(mode: str) -> None:
    registry = UniverseRegistry.from_json(UNIVERSE_PATH)
    report = validate_universe(registry.all())
    if not report.valid:
        raise ValueError("Invalid universe: " + "; ".join(report.errors))
    if mode == "fixture":
        prices, benchmark = build_fixture(registry)
        etfs = _etf_frame(registry)
    elif mode == "live":
        prices, benchmark, etfs = build_live(registry)
    else:
        raise ValueError("mode must be fixture or live")
    prices = prices.sort_index()
    benchmark = benchmark.dropna().sort_index()
    common = prices.index.intersection(benchmark.index)
    prices = prices.loc[common]
    benchmark = benchmark.loc[common]
    if prices.empty:
        raise RuntimeError("No overlapping benchmark/exposure history was downloaded")

    rankings = rank_exposures(prices, benchmark)
    summary_rows: list[dict[str, object]] = []
    rs_series: dict[str, pd.Series] = {}
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
        summary_rows.append({"exposure_id": exposure.id, "exposure": exposure.name, "category": exposure.category.value, "benchmark": exposure.benchmark, "rs_ratio": latest_ratio, "rs_momentum": latest_momentum, "stage": rs_stage(latest_ratio, latest_momentum), "momentum_z": rank_row["momentum_z"], "rank": rank_row["rank"], **{f"return_{label}": rank_row[f"return_{label}"] for label in ("1M", "3M", "6M", "12M")}})
    summary = pd.DataFrame(summary_rows).sort_values("rank")
    rs_matrix = pd.DataFrame(rs_series).sort_index()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_parquet(summary, OUTPUT / "summary_rankings.parquet")
    write_parquet(rs_matrix, OUTPUT / "rs_matrix.parquet")
    write_parquet(etfs, OUTPUT / "etf_universe.parquet")
    metadata = {"mode": mode, "benchmark": registry.benchmark_name, "generated_at": pd.Timestamp.utcnow().isoformat(), "observations": int(len(prices)), "exposures_with_history": int(prices.shape[1])}
    (OUTPUT / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the Sector-Rotation prepared dataset")
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    run(parser.parse_args().mode)
