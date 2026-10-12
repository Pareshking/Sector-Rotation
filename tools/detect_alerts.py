"""Compare the working-tree target portfolio against the one the last commit implied.

Run after the pipeline, before the data is committed: the previous dataset is
still in git, so both targets come from the same code — ``src/portfolio``,
the function the dashboard and the backtest use — applied to tonight's data
and to the last published data. Writes a markdown report to stdout and to
--out; exits 0 whether or not anything changed so it can never fail a
pipeline run.

Depends only on ``src/``: no Streamlit, so the nightly job cannot break
because the UI package did.
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

from src.formatting import format_updated  # noqa: E402
from src.portfolio.live import (  # noqa: E402
    LivePortfolio,
    live_portfolio_from_artifacts,
)
from src.quantitative.alerts import diff_targets, render_markdown  # noqa: E402

PROCESSED = "data/processed"
INDEX_PRICES = f"{PROCESSED}/index_prices.parquet"
ETF_UNIVERSE = f"{PROCESSED}/etf_universe.parquet"
ETF_PRICES = f"{PROCESSED}/etf_prices.parquet"
SUMMARY = f"{PROCESSED}/summary_rankings.parquet"


def _committed(path: str, ref: str = "HEAD") -> pd.DataFrame:
    try:
        blob = subprocess.run(
            ["git", "show", f"{ref}:{path}"], cwd=ROOT, capture_output=True, check=True
        ).stdout
    except subprocess.CalledProcessError:
        return pd.DataFrame()
    return pd.read_parquet(io.BytesIO(blob))


def _working(path: str) -> pd.DataFrame:
    target = ROOT / path
    return pd.read_parquet(target) if target.exists() else pd.DataFrame()


def _names(summary: pd.DataFrame) -> dict[str, str]:
    if summary.empty or "exposure_id" not in summary:
        return {}
    return {str(k): str(v) for k, v in zip(summary["exposure_id"], summary["exposure"])}


def portfolio_from(load, names: dict[str, str]) -> LivePortfolio | None:
    panel = load(INDEX_PRICES)
    if panel.empty:
        return None
    return live_portfolio_from_artifacts(panel, load(ETF_UNIVERSE), load(ETF_PRICES), names=names)


def main() -> None:
    parser = argparse.ArgumentParser(description="Report target-portfolio changes since the last commit")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--ref", default="HEAD")
    args = parser.parse_args()

    names = _names(_working(SUMMARY))
    current = portfolio_from(_working, names)
    if current is None:
        print("No current index panel; nothing to compare.")
        if args.out:
            args.out.write_text("", encoding="utf-8")
        return
    previous = portfolio_from(lambda path: _committed(path, args.ref), names)

    updated = ""
    metadata = ROOT / PROCESSED / "metadata.json"
    if metadata.exists():
        try:
            absolute, _ = format_updated(json.loads(metadata.read_text())["last_updated_utc"])
            updated = absolute
        except (KeyError, ValueError, json.JSONDecodeError):
            pass

    alerts = diff_targets(previous.target if previous else None, current.target, names)
    report = render_markdown(alerts, updated)
    if not report:
        print(f"No target-portfolio changes (decision {current.target.as_of:%d %b %Y}).")
        if args.out:
            args.out.write_text("", encoding="utf-8")
        return

    print(report)
    if args.out:
        args.out.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
