"""Compare the working-tree decision set against the last committed one.

Run after the pipeline, before the data is committed: the previous dataset is
still in git, so the diff is exactly what changed in this refresh. Writes a
markdown report to stdout and to --out; exits 0 whether or not anything changed
so it can never fail a pipeline run.
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.components.metrics import decision_frame, format_updated  # noqa: E402
from src.quantitative.alerts import diff_actions, render_markdown  # noqa: E402
from src.universe.tradeability import attach_tradeability  # noqa: E402

SUMMARY = "data/processed/summary_rankings.parquet"


def _committed(path: str, ref: str = "HEAD") -> pd.DataFrame:
    try:
        blob = subprocess.run(
            ["git", "show", f"{ref}:{path}"], cwd=ROOT, capture_output=True, check=True
        ).stdout
    except subprocess.CalledProcessError:
        return pd.DataFrame()
    return pd.read_parquet(io.BytesIO(blob))


def main() -> None:
    parser = argparse.ArgumentParser(description="Report decision changes since the last commit")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--ref", default="HEAD")
    args = parser.parse_args()

    current_path = ROOT / SUMMARY
    if not current_path.exists():
        print("No current summary; nothing to compare.")
        return

    etfs_path = ROOT / "data" / "processed" / "etf_universe.parquet"
    prices_path = ROOT / "data" / "processed" / "etf_prices.parquet"
    etfs = pd.read_parquet(etfs_path) if etfs_path.exists() else pd.DataFrame()
    etf_prices = pd.read_parquet(prices_path) if prices_path.exists() else pd.DataFrame()

    current = attach_tradeability(decision_frame(pd.read_parquet(current_path)), etfs, etf_prices)
    previous_raw = _committed(SUMMARY, args.ref)
    previous = decision_frame(previous_raw) if not previous_raw.empty else pd.DataFrame()

    updated = ""
    metadata = ROOT / "data" / "processed" / "metadata.json"
    if metadata.exists():
        try:
            absolute, _ = format_updated(json.loads(metadata.read_text())["last_updated_utc"])
            updated = absolute
        except (KeyError, ValueError, json.JSONDecodeError):
            pass

    alerts = diff_actions(previous, current)
    report = render_markdown(alerts, updated)
    if not report:
        print("No decision changes in this refresh.")
        if args.out:
            args.out.write_text("", encoding="utf-8")
        return

    print(report)
    if args.out:
        args.out.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
