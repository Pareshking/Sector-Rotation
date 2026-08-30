"""Data-quality checks run against a freshly built dataset.

The pipeline already fails closed on canonical coverage. These checks catch the
quieter failures: a number that used to be right and silently got worse. ETF
coverage moved 31 -> 29 between two production runs and nothing anywhere said
so, because every individual run looked internally consistent.

Every check compares the new run against the previous ``metadata.json`` where a
comparison is meaningful, and against the data itself where it is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

# A series that has not moved in this many trading days is almost certainly a
# stale feed repeating its last value rather than a genuinely flat index.
FLATLINE_DAYS = 15
# Trading days of slack before the newest observation counts as stale. NSE
# holidays and long weekends routinely account for three or four.
STALE_DAYS = 5

# A GitHub Actions timeout reports as "cancelled", which looks identical to a
# run superseded by concurrency. Two nights of failed publishing went unnoticed
# because nothing checked the consequence: how old the published data is.
MAX_DATA_AGE_HOURS = 36

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass
class QualityReport:
    alerts: list[dict[str, str]] = field(default_factory=list)

    def add(self, severity: str, check: str, message: str) -> None:
        self.alerts.append({"severity": severity, "check": check, "message": message})

    @property
    def errors(self) -> list[dict[str, str]]:
        return [a for a in self.alerts if a["severity"] == "error"]

    @property
    def warnings(self) -> list[dict[str, str]]:
        return [a for a in self.alerts if a["severity"] == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def sorted_alerts(self) -> list[dict[str, str]]:
        return sorted(self.alerts, key=lambda a: SEVERITY_ORDER.get(a["severity"], 9))


def _coverage_regression(report: QualityReport, new: dict, previous: dict) -> None:
    checks = (
        ("valid_canonical_series", "canonical index histories", "error"),
        ("etf_valid_series", "ETF price histories", "warning"),
    )
    for key, label, severity in checks:
        before, after = previous.get(key), new.get(key)
        if not isinstance(before, int) or not isinstance(after, int):
            continue
        if after < before:
            report.add(
                severity,
                "coverage_regression",
                f"{label} fell from {before} to {after} since the previous run.",
            )


def _dropped_series(report: QualityReport, new: dict, previous: dict) -> None:
    for key, label in (
        ("source_by_canonical_exposure", "canonical exposure"),
        ("etf_source_by_symbol", "ETF series"),
    ):
        before = set((previous.get(key) or {}))
        after = set((new.get(key) or {}))
        lost = sorted(before - after)
        if lost:
            severity = "error" if key == "source_by_canonical_exposure" else "warning"
            report.add(
                severity,
                "series_dropped",
                f"{len(lost)} {label} entries present last run are missing now: {', '.join(lost[:8])}"
                + (" …" if len(lost) > 8 else ""),
            )


def _staleness(report: QualityReport, prices: pd.DataFrame) -> None:
    if prices is None or prices.empty:
        return
    latest = prices.index.max()
    expected = pd.Timestamp.now().normalize()
    gap = len(pd.bdate_range(latest, expected)) - 1
    if gap > STALE_DAYS:
        report.add(
            "warning",
            "stale_data",
            f"Newest observation is {latest:%d %b %Y}, {gap} business days behind today.",
        )


def _flatlines(report: QualityReport, prices: pd.DataFrame, label: str, severity: str) -> None:
    if prices is None or prices.empty or len(prices) < FLATLINE_DAYS:
        return
    tail = prices.tail(FLATLINE_DAYS)
    flat = [
        column
        for column in tail.columns
        if tail[column].notna().sum() >= FLATLINE_DAYS and tail[column].nunique(dropna=True) <= 1
    ]
    if flat:
        report.add(
            severity,
            "flatline",
            f"{len(flat)} {label} have not moved in {FLATLINE_DAYS} trading days "
            f"({', '.join(sorted(flat)[:8])}). A repeated last value usually means a stale feed.",
        )


def _observation_drop(report: QualityReport, new: dict, previous: dict) -> None:
    before, after = previous.get("observations"), new.get("observations")
    if isinstance(before, int) and isinstance(after, int) and after < before * 0.95:
        report.add(
            "error",
            "history_truncated",
            f"Observation count fell from {before} to {after}, a {1 - after / before:.0%} drop. "
            "A parser or date-format change can truncate a history without any request failing.",
        )


def _publication_age(report: QualityReport, new: dict) -> None:
    """Catch a silent publishing failure by its symptom, not its cause."""
    stamp = new.get("last_updated_utc")
    if not stamp:
        return
    try:
        published = datetime.fromisoformat(str(stamp))
    except ValueError:
        return
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    hours = (datetime.now(timezone.utc) - published).total_seconds() / 3600.0
    if hours > MAX_DATA_AGE_HOURS:
        report.add(
            "error",
            "stale_publication",
            f"Published dataset is {hours:.0f} hours old, past the {MAX_DATA_AGE_HOURS}-hour "
            "limit. The scheduled refresh is not completing — check whether the pipeline job "
            "timed out (Actions reports a timeout as 'cancelled', not 'failed').",
        )


def check_dataset(
    new_metadata: dict,
    previous_metadata: dict | None,
    index_prices: pd.DataFrame | None = None,
    etf_prices: pd.DataFrame | None = None,
) -> QualityReport:
    """Compare a freshly built dataset against the last published one."""
    report = QualityReport()
    previous = previous_metadata or {}
    if previous:
        _coverage_regression(report, new_metadata, previous)
        _dropped_series(report, new_metadata, previous)
        _observation_drop(report, new_metadata, previous)
    else:
        report.add("info", "baseline", "No previous metadata found; skipped regression checks.")

    _publication_age(report, new_metadata)
    _staleness(report, index_prices)
    _flatlines(report, index_prices, "canonical index histories", "error")
    _flatlines(report, etf_prices, "ETF price histories", "warning")
    if not report.alerts:
        report.add("info", "clean", "No data-quality regressions detected.")
    return report
