"""Run the full backtest control matrix against canonical production data.

This is a diagnostic tool only. It does not change strategy behavior or assert
that the absolute filter must change historical returns; it reports whether it
did, and where holdings/cash decisions differ.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.quantitative.backtest import run_backtest


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "index_prices.parquet"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="Optional CSV output path")
    args = parser.parse_args()

    if not DATA.exists():
        raise SystemExit(f"Missing canonical data: {DATA}")

    panel = pd.read_parquet(DATA)
    if "__benchmark__" not in panel.columns:
        raise SystemExit("Canonical panel has no __benchmark__ column")

    benchmark = panel["__benchmark__"].dropna()
    prices = panel.drop(columns=["__benchmark__"])
    rows: list[dict[str, object]] = []

    for top_n in (1, 2, 3, 5):
        for months in (12, 24, 36, 60):
            off = run_backtest(prices, benchmark, top_n=top_n, months=months, absolute_filter=False)
            on = run_backtest(prices, benchmark, top_n=top_n, months=months, absolute_filter=True)
            if not off.ok or not on.ok:
                rows.append(
                    {
                        "top_n": top_n,
                        "window_requested": months,
                        "filter": "error",
                        "error_off": off.error,
                        "error_on": on.error,
                    }
                )
                continue

            off_holdings = off.monthly["holdings"].astype(str)
            on_holdings = on.monthly["holdings"].astype(str)
            aligned = pd.DataFrame({"off": off_holdings, "on": on_holdings}).reset_index(drop=True)
            changed = aligned["off"] != aligned["on"]

            rows.extend(
                [
                    {
                        "top_n": top_n,
                        "window_requested": months,
                        "filter": "OFF",
                        "actual_months": int(off.stats["months"]),
                        "total_return": off.stats["total_return"],
                        "cash_months": int(off.stats["cash_months"]),
                        "avg_turnover": off.stats["avg_turnover"],
                    },
                    {
                        "top_n": top_n,
                        "window_requested": months,
                        "filter": "ON",
                        "actual_months": int(on.stats["months"]),
                        "total_return": on.stats["total_return"],
                        "cash_months": int(on.stats["cash_months"]),
                        "avg_turnover": on.stats["avg_turnover"],
                        "holding_months_different_from_off": int(changed.sum()),
                    },
                ]
            )

    result = pd.DataFrame(rows)
    print(result.to_string(index=False))
    if args.output:
        result.to_csv(args.output, index=False)
        print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
