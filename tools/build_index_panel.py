"""Build data/processed/index_prices.parquet from NSE index history alone.

The full pipeline also refreshes ETF prices from Yahoo/AMFI. This script writes
only the canonical index panel the backtest needs, so it can be regenerated
without touching the ETF artifacts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.run_pipeline import BENCHMARK_COLUMN  # noqa: E402
from src.data.cache import write_parquet  # noqa: E402
from src.data.jugaad_indices import fetch_benchmark, fetch_jugaad_canonical_indices  # noqa: E402
from src.universe.registry import UniverseRegistry  # noqa: E402

PROCESSED = ROOT / "data" / "processed"
OUTPUT = PROCESSED / "index_prices.parquet"
METADATA = PROCESSED / "metadata.json"


def main(years: int = 5) -> None:
    registry = UniverseRegistry.from_json(ROOT / "data" / "universe" / "universe.json")
    names = {e.id: e.benchmark for e in registry.all()}
    print(f"fetching {len(names)} canonical indices …", flush=True)
    prices, sources, resolved, value_types = fetch_jugaad_canonical_indices(names, years=years, workers=6)
    print(f"resolved {prices.shape[1]}/{len(names)} exposures", flush=True)
    del sources, resolved

    benchmark = fetch_benchmark(registry.benchmark_name.upper(), years=years)
    if benchmark.dropna().empty:
        raise SystemExit("benchmark history unavailable")
    print(f"benchmark {registry.benchmark_name}: {len(benchmark)} rows "
          f"({benchmark.attrs.get('value_type')})", flush=True)

    panel = prices.copy()
    panel[BENCHMARK_COLUMN] = benchmark
    panel = panel.sort_index()
    common = panel.index.intersection(benchmark.dropna().index)
    panel = panel.loc[common]

    write_parquet(panel, OUTPUT)

    # Record what each series actually is. Without this the Data Health "Value"
    # column cannot distinguish a total-return series from a price index.
    if METADATA.exists():
        metadata = json.loads(METADATA.read_text(encoding="utf-8"))
        metadata["value_type_by_canonical_exposure"] = value_types
        metadata["benchmark_source"] = "niftyindices_jugaad"
        metadata["benchmark_value_type"] = benchmark.attrs.get("value_type", "UNKNOWN")
        metadata["index_panel_start"] = str(panel.index.min().date())
        metadata["index_panel_end"] = str(panel.index.max().date())
        METADATA.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print("metadata updated with per-exposure value types", flush=True)
    print(json.dumps({
        "rows": int(len(panel)),
        "columns": int(panel.shape[1]),
        "start": str(panel.index.min().date()),
        "end": str(panel.index.max().date()),
        "tri": sum(v == "TRI" for v in value_types.values()),
        "close": sum(v == "CLOSE" for v in value_types.values()),
        "missing": sorted(set(names) - set(prices.columns)),
    }, indent=2))


if __name__ == "__main__":
    main()
