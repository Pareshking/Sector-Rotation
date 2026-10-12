"""Detect changes in the target portfolio between two published runs.

A rotation model only asks for action when its target changes, and since
strategy v1.0 the target only changes at a month-end rebalance. Comparing the
target built from tonight's data with the one built from the last committed
data turns that into an event: what to buy, what to sell, by how much. Between
rebalances both nights produce the same decision and nothing is raised.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.portfolio.construct import BUY, CASH, SELL, TRIM, TargetPortfolio

_EPS = 1e-9


@dataclass
class AlertSet:
    entered: list[dict[str, str]] = field(default_factory=list)  # bought into the target
    exited: list[dict[str, str]] = field(default_factory=list)  # sold out of it
    changed: list[dict[str, str]] = field(default_factory=list)  # weight changed, still held
    as_of: str = ""
    previous_as_of: str = ""

    @property
    def any(self) -> bool:
        return bool(self.entered or self.exited or self.changed)

    def as_rows(self) -> list[dict[str, str]]:
        return [*self.entered, *self.exited, *self.changed]


def _pct(value: float) -> str:
    return f"{value:.0%}"


def diff_targets(
    previous: TargetPortfolio | None,
    current: TargetPortfolio | None,
    names: dict[str, str] | None = None,
) -> AlertSet:
    """Orders implied by moving from the previous published target to the current one."""
    alerts = AlertSet()
    if current is None:
        return alerts
    names = names or {}
    alerts.as_of = f"{current.as_of:%d %b %Y}"
    alerts.previous_as_of = f"{previous.as_of:%d %b %Y}" if previous is not None else ""
    before = dict(previous.weights) if previous is not None else {CASH: 1.0}
    after = dict(current.weights)
    decisions = {d.exposure_id: d for d in current.decisions}
    ranking = current.ranking
    ranks = ranking["rank"] if "rank" in ranking else pd.Series(dtype=float)

    for exposure_id in sorted((set(before) | set(after)) - {CASH}):
        was, now = before.get(exposure_id, 0.0), after.get(exposure_id, 0.0)
        if abs(now - was) <= _EPS:
            continue
        # The order is the move between the two *published* targets, so the
        # action is read from that move, never copied from the decision (whose
        # action is relative to its own prior).
        if was <= _EPS:
            action, bucket = BUY, alerts.entered
        elif now <= _EPS:
            action, bucket = SELL, alerts.exited
        else:
            action, bucket = (TRIM if now < was else BUY), alerts.changed
        decision = decisions.get(exposure_id)
        if decision is not None:
            reason = decision.reason
        elif exposure_id in ranking.index:
            reason = f"Not in the target ({ranking.at[exposure_id, 'status']}): {ranking.at[exposure_id, 'reason']}."
        else:
            reason = "No longer in the scored universe."
        rank = ranks.get(exposure_id)
        bucket.append(
            {
                "exposure": names.get(exposure_id, exposure_id),
                "exposure_id": exposure_id,
                "action": action,
                "from": _pct(was),
                "to": _pct(now),
                "rank": "—" if rank is None or pd.isna(rank) else str(int(rank)),
                "reason": reason,
            }
        )
    return alerts


def render_markdown(alerts: AlertSet, updated: str = "") -> str:
    """A short report suitable for an issue body or an email."""
    if not alerts.any:
        return ""
    lines: list[str] = []
    if updated:
        lines.append(f"Dataset refreshed **{updated}**.\n")
    if alerts.as_of:
        since = f" (previous decision {alerts.previous_as_of})" if alerts.previous_as_of else ""
        lines.append(
            f"New target portfolio at the **{alerts.as_of}** close{since}. "
            "Orders execute at the next session's close.\n"
        )

    def block(title: str, rows: list[dict[str, str]]) -> None:
        if not rows:
            return
        lines.append(f"### {title}\n")
        lines.append("| Exposure | Action | Weight | Rank | Why |")
        lines.append("| --- | --- | --- | --- | --- |")
        for r in rows:
            lines.append(
                f"| {r['exposure']} | **{r['action']}** | {r['from']} → {r['to']} | "
                f"{r['rank']} | {r['reason']} |"
            )
        lines.append("")

    block("Buy", alerts.entered)
    block("Sell", alerts.exited)
    block("Resize", alerts.changed)
    lines.append(
        "_Target changes only. Verify the vehicle, its tracking difference and its premium to "
        "NAV before acting._"
    )
    return "\n".join(lines)


__all__ = ["AlertSet", "diff_targets", "render_markdown"]
