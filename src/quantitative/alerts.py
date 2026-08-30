"""Detect changes in the decision set between two published runs.

The dashboard answers "what should I do today", but a rotation model only asks
for action when something *changes*. Watching a board daily for a transition
that happens a few times a year is the wrong use of a person; this turns the
transitions into events.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# Only these transitions are worth interrupting someone for. WATCH drifting to
# WATCH / IMPROVING is information, not an instruction.
ACTIONABLE = {"BUY", "REDUCE / EXIT"}


@dataclass
class AlertSet:
    entered: list[dict[str, str]] = field(default_factory=list)
    exited: list[dict[str, str]] = field(default_factory=list)
    changed: list[dict[str, str]] = field(default_factory=list)

    @property
    def any(self) -> bool:
        return bool(self.entered or self.exited or self.changed)

    def as_rows(self) -> list[dict[str, str]]:
        return [*self.entered, *self.exited, *self.changed]


def _index(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    if frame is None or frame.empty or "exposure_id" not in frame.columns:
        return {}
    return {
        str(row["exposure_id"]): row
        for row in frame.to_dict("records")
        if row.get("exposure_id") is not None
    }


def diff_actions(previous: pd.DataFrame, current: pd.DataFrame) -> AlertSet:
    """Compare two decision frames and report the transitions that matter."""
    alerts = AlertSet()
    before, after = _index(previous), _index(current)
    if not after:
        return alerts

    for exposure_id, row in after.items():
        now = str(row.get("model_action", ""))
        was = str(before.get(exposure_id, {}).get("model_action", "")) if exposure_id in before else ""
        if not was:
            # A brand new exposure only warrants an alert if it lands actionable.
            if now in ACTIONABLE:
                alerts.entered.append(_event(row, "NEW", now))
            continue
        if now == was:
            continue
        if now in ACTIONABLE:
            alerts.entered.append(_event(row, was, now))
        elif was in ACTIONABLE:
            alerts.exited.append(_event(row, was, now))
        else:
            alerts.changed.append(_event(row, was, now))
    return alerts


def _event(row: dict, was: str, now: str) -> dict[str, str]:
    tradeable = row.get("tradeable")
    return {
        "exposure": str(row.get("exposure", row.get("exposure_id", "?"))),
        "from": was,
        "to": now,
        "stage": str(row.get("stage", "")),
        "rank": str(int(row["rank"])) if pd.notna(row.get("rank")) else "—",
        "tradeable": "yes" if tradeable else ("no" if tradeable is not None else "?"),
    }


def render_markdown(alerts: AlertSet, updated: str = "") -> str:
    """A short report suitable for an issue body or an email."""
    if not alerts.any:
        return ""
    lines: list[str] = []
    if updated:
        lines.append(f"Dataset refreshed **{updated}**.\n")

    def block(title: str, rows: list[dict[str, str]]) -> None:
        if not rows:
            return
        lines.append(f"### {title}\n")
        lines.append("| Exposure | Change | Stage | Rank | Buyable |")
        lines.append("| --- | --- | --- | --- | --- |")
        for r in rows:
            lines.append(
                f"| {r['exposure']} | {r['from']} → **{r['to']}** | {r['stage']} | "
                f"{r['rank']} | {r['tradeable']} |"
            )
        lines.append("")

    block("Entered an actionable state", alerts.entered)
    block("Left an actionable state", alerts.exited)
    block("Other changes", alerts.changed)
    lines.append(
        "_Signal changes only. Verify the vehicle, its tracking difference and its premium to "
        "NAV before acting._"
    )
    return "\n".join(lines)
