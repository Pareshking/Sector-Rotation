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
from src.quantitative.returns import LOOKBACK_DAYS


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "index_prices.parquet"


def _absolute_return(prices: pd.DataFrame, exposure_id: str, asof: pd.Timestamp) -> float | None:
    series = prices[exposure_id].loc[:asof].dropna()
    days = LOOKBACK_DAYS["12M"]
    if len(series) <= days:
        return None
    return float(series.iloc[-1] / series.iloc[-days - 1] - 1.0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="Optional summary CSV output path")
    parser.add_argument("--decisions-output", type=Path, help="Optional decision-difference CSV output path")
    args = parser.parse_args()

    if not DATA.exists():
        raise SystemExit(f"Missing canonical data: {DATA}")

    panel = pd.read_parquet(DATA)
    if "__benchmark__" not in panel.columns:
        raise SystemExit("Canonical panel has no __benchmark__ column")

    benchmark = panel["__benchmark__"].dropna()
    prices = panel.drop(columns=["__benchmark__"])
    summary_rows: list[dict[str, object]] = []
    decision_rows: list[dict[str, object]] = []

    for top_n in (1, 2, 3, 5):
        for months in (12, 24, 36, 60):
            off = run_backtest(prices, benchmark, top_n=top_n, months=months, absolute_filter=False)
            on = run_backtest(prices, benchmark, top_n=top_n, months=months, absolute_filter=True)
            if not off.ok or not on.ok:
                summary_rows.append(
                    {
                        "top_n": top_n,
                        "window_requested": months,
                        "filter": "error",
                        "error_off": off.error,
                        "error_on": on.error,
                    }
                )
                continue

            off_monthly = off.monthly.reset_index(drop=True)
            on_monthly = on.monthly.reset_index(drop=True)
            aligned = pd.DataFrame(
                {
                    "rebalance": off_monthly["rebalance"],
                    "off_holdings": off_monthly["holdings"].astype(str),
                    "on_holdings": on_monthly["holdings"].astype(str),
                    "off_return": off_monthly["strategy_return"],
                    "on_return": on_monthly["strategy_return"],
                    "off_cash_slots": off_monthly["cash_slots"],
                    "on_cash_slots": on_monthly["cash_slots"],
                }
            )
            changed = aligned["off_holdings"] != aligned["on_holdings"]

            for row in aligned.loc[changed].itertuples(index=False):
                off_names = [name.strip() for name in row.off_holdings.split(",") if name.strip() and name != "cash"]
                on_names = [name.strip() for name in row.on_holdings.split(",") if name.strip() and name != "cash"]
                off_only = [name for name in off_names if name not in on_names]
                absolute_returns = [
                    _absolute_return(prices, name, row.rebalance) for name in off_only
                ]
                decision_rows.append(
                    {
                        "top_n": top_n,
                        "window_requested": months,
                        "rebalance": row.rebalance,
                        "off_holdings": row.off_holdings,
                        "on_holdings": row.on_holdings,
                        "off_only_rejected_by_filter": ", ".join(off_only),
                        "off_only_12m_absolute_returns": ", ".join(
                            "NA" if value is None else f"{value:.6f}" for value in absolute_returns
                        ),
                        "off_return": row.off_return,
                        "on_return": row.on_return,
                        "off_cash_slots": row.off_cash_slots,
                        "on_cash_slots": row.on_cash_slots,
                    }
                )

            summary_rows.extend(
                [
                    {
                        "top_n": top_n,
                        "window_requested": months,
                        "filter": "OFF",
                        "actual_months": int(off.stats["months"]),
                        "total_return": off.stats["total_return"],
                        "cash_months": int(off.stats["cash_months"]),
                        "avg_turnover": off.stats["avg_turnover"],
                        "holding_months_different_from_on": int(changed.sum()),
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

    summary = pd.DataFrame(summary_rows)
    decisions = pd.DataFrame(decision_rows)
    print("\n=== SUMMARY ===")
    print(summary.to_string(index=False))
    print("\n=== HOLDING DIFFERENCES ===")
    print(decisions.to_string(index=False) if not decisions.empty else "None")

    if args.output:
        summary.to_csv(args.output, index=False)
        print(f"\nWrote {args.output}")
    if args.decisions_output:
        decisions.to_csv(args.decisions_output, index=False)
        print(f"Wrote {args.decisions_output}")


if __name__ == "__main__":
    main()
