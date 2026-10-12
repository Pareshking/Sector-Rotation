"""Append-only raw price store: ``data/raw/{kind}/{id}/{yyyy}.parquet``.

Every observation the pipeline has ever accepted is kept. A partition only
ever gains rows: a new session is appended, and a value NSE or AMFI later
restates is appended again with a later ``fetched_at`` instead of overwriting
the original, so the archive records what was published *and* what it was
changed to. Reading a series takes the latest row per date.

This replaces the nightly rolling five-year re-download, which discarded the
oldest day every night, so the history could never grow and a restatement
was invisible.

Rows: ``date``, ``value``, ``value_type`` (TRI / CLOSE / NAV), ``source``,
``fetched_at`` (UTC). ``kind`` is ``index`` or ``vehicle``; vehicles are keyed
by AMFI scheme code, which is unique and filesystem-safe.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.data.calendar import TradingCalendar

logger = logging.getLogger(__name__)

KINDS = ("index", "vehicle")
COLUMNS = ("date", "value", "value_type", "source", "fetched_at")
DEFAULT_OVERLAP_SESSIONS = 10
# A restatement is any overlap value that moved by more than both of these.
# Index levels are published to two decimals and NAVs to four, so anything
# smaller is rounding.
RESTATEMENT_REL_TOL = 1e-6
RESTATEMENT_ABS_TOL = 0.005
# When most of the overlap disagrees by more than this, the fetch returned a
# different series (a swapped response, a price index served for a total-return
# index), not a correction. That is refused, never merged.
DISCONTINUITY_REL = 0.02
DISCONTINUITY_SHARE = 0.5

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")


class SeriesMismatch(ValueError):
    """A fetch cannot be merged into the stored series without corrupting it."""


@dataclass(frozen=True)
class Restatement:
    kind: str
    series_id: str
    date: pd.Timestamp
    stored: float
    fetched: float

    @property
    def rel_change(self) -> float:
        return float(self.fetched / self.stored - 1.0) if self.stored else float("inf")

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "series_id": self.series_id,
            "date": f"{self.date:%Y-%m-%d}",
            "stored": self.stored,
            "fetched": self.fetched,
            "rel_change": self.rel_change,
        }


@dataclass
class MergeResult:
    series_id: str
    new_sessions: int = 0
    unchanged_overlap: int = 0
    restatements: list[Restatement] = field(default_factory=list)


class RawStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ paths
    def _dir(self, kind: str, series_id: str) -> Path:
        if kind not in KINDS:
            raise ValueError(f"unknown store kind {kind!r}; expected one of {KINDS}")
        sid = str(series_id)
        if not _SAFE_ID.fullmatch(sid):
            raise ValueError(f"unsafe series id {sid!r}")
        return self.root / kind / sid

    def partition(self, kind: str, series_id: str, year: int) -> Path:
        return self._dir(kind, series_id) / f"{int(year)}.parquet"

    def ids(self, kind: str) -> list[str]:
        base = self.root / kind
        return sorted(p.name for p in base.iterdir() if p.is_dir()) if base.exists() else []

    # ------------------------------------------------------------------ reads
    def rows(self, kind: str, series_id: str) -> pd.DataFrame:
        """Every stored row, all versions, oldest first."""
        folder = self._dir(kind, series_id)
        files = sorted(folder.glob("*.parquet")) if folder.exists() else []
        if not files:
            return pd.DataFrame(columns=list(COLUMNS))
        frame = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
        return frame.sort_values(["date", "fetched_at"], kind="mergesort", ignore_index=True)

    def series(self, kind: str, series_id: str, source: str | None = None) -> pd.Series:
        """The current series: latest version of each date. ``attrs`` carry type and source."""
        rows = self.rows(kind, series_id)
        if source is not None and not rows.empty:
            rows = rows[rows["source"] == source]
        if rows.empty:
            out = pd.Series(dtype="float64", name=str(series_id))
            out.attrs.update(value_type=None, source=None)
            return out
        latest = rows.drop_duplicates("date", keep="last")
        out = pd.Series(
            latest["value"].to_numpy(float),
            index=pd.DatetimeIndex(latest["date"]).rename(None),
            name=str(series_id),
        )
        out.attrs.update(
            value_type=str(latest["value_type"].iloc[-1]), source=str(latest["source"].iloc[-1])
        )
        return out

    def last_date(self, kind: str, series_id: str) -> pd.Timestamp | None:
        current = self.series(kind, series_id)
        return pd.Timestamp(current.index.max()) if not current.empty else None

    def window_start(
        self,
        kind: str,
        series_id: str,
        overlap_sessions: int = DEFAULT_OVERLAP_SESSIONS,
        calendar: TradingCalendar | None = None,
    ) -> pd.Timestamp | None:
        """Where an incremental fetch should begin: ``overlap_sessions`` before the last stored session.

        ``None`` when nothing is stored (seed from scratch). The overlap is
        counted on the benchmark calendar when given, otherwise on the
        series' own stored sessions.
        """
        current = self.series(kind, series_id)
        if current.empty:
            return None
        sessions = calendar if calendar is not None else TradingCalendar(current.index)
        start = sessions.sessions_back(current.index.max(), overlap_sessions)
        return start if start is not None else pd.Timestamp(current.index.min())

    # ----------------------------------------------------------------- writes
    def merge(
        self,
        kind: str,
        series_id: str,
        fetched: pd.Series,
        value_type: str,
        source: str,
        fetched_at: pd.Timestamp | None = None,
    ) -> MergeResult:
        """Append what is new or restated; never rewrite or drop a stored row."""
        result = MergeResult(series_id=str(series_id))
        incoming = pd.to_numeric(fetched, errors="coerce").dropna()
        incoming = incoming[incoming > 0]
        if incoming.empty:
            return result
        incoming.index = pd.DatetimeIndex(incoming.index).normalize()
        incoming = incoming[~incoming.index.duplicated(keep="last")].sort_index()
        stamp = pd.Timestamp(fetched_at) if fetched_at is not None else pd.Timestamp.now(tz="UTC")
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")

        current = self.series(kind, series_id)
        if not current.empty:
            stored_type = current.attrs.get("value_type")
            if stored_type and stored_type != value_type:
                raise SeriesMismatch(
                    f"{kind}/{series_id}: stored as {stored_type}, fetched as {value_type}; "
                    "splicing them would corrupt every return across the join"
                )
            overlap = current.index.intersection(incoming.index)
            if len(overlap):
                old = current.loc[overlap].astype(float)
                new = incoming.loc[overlap].astype(float)
                rel = (new / old - 1.0).abs()
                if (rel > DISCONTINUITY_REL).mean() > DISCONTINUITY_SHARE:
                    raise SeriesMismatch(
                        f"{kind}/{series_id}: {int((rel > DISCONTINUITY_REL).sum())} of {len(overlap)} "
                        f"overlapping sessions differ by more than {DISCONTINUITY_REL:.0%}; "
                        "this is a different series, not a restatement"
                    )
                changed = (rel > RESTATEMENT_REL_TOL) & ((new - old).abs() > RESTATEMENT_ABS_TOL)
                for when in overlap[changed.to_numpy()]:
                    result.restatements.append(
                        Restatement(kind, str(series_id), pd.Timestamp(when), float(old[when]), float(new[when]))
                    )
                result.unchanged_overlap = int((~changed).sum())
                keep = incoming.index.difference(current.index).union(overlap[changed.to_numpy()])
                incoming = incoming.loc[keep]
            result.new_sessions = int(len(incoming.index.difference(current.index)))
        else:
            result.new_sessions = len(incoming)

        if incoming.empty:
            return result
        rows = pd.DataFrame(
            {
                "date": incoming.index,
                "value": incoming.to_numpy(float),
                "value_type": value_type,
                "source": source,
                "fetched_at": stamp,
            }
        )
        for year, chunk in rows.groupby(rows["date"].dt.year):
            path = self.partition(kind, series_id, int(year))
            path.parent.mkdir(parents=True, exist_ok=True)
            existing = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=list(COLUMNS))
            combined = pd.concat([existing, chunk], ignore_index=True) if len(existing) else chunk
            combined = combined.sort_values(["date", "fetched_at"], kind="mergesort", ignore_index=True)
            combined.to_parquet(path, compression="zstd", index=False)
        for item in result.restatements:
            logger.warning(
                "Restatement %s/%s %s: %.6g -> %.6g (%+.4f%%)",
                kind, series_id, f"{item.date:%Y-%m-%d}", item.stored, item.fetched, 100 * item.rel_change,
            )
        return result


def panel(store: RawStore, kind: str, ids, sources: dict[str, str] | None = None) -> pd.DataFrame:
    """Current series for ``ids`` as one date-indexed frame (missing ids are absent)."""
    columns = {}
    for sid in ids:
        series = store.series(kind, str(sid), (sources or {}).get(str(sid)))
        if not series.empty:
            columns[str(sid)] = series
    return pd.DataFrame(columns).sort_index() if columns else pd.DataFrame()


__all__ = [
    "DEFAULT_OVERLAP_SESSIONS",
    "MergeResult",
    "RawStore",
    "Restatement",
    "SeriesMismatch",
    "panel",
]
