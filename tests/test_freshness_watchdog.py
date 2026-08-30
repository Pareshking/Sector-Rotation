from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from tools.check_freshness import MAX_DATA_AGE_HOURS, check


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_fresh_dataset_passes(tmp_path):
    fresh = dt.datetime.now(dt.timezone.utc).isoformat()
    ok, _ = check(_write(tmp_path, {"last_updated_utc": fresh}))
    assert ok


def test_stale_dataset_fails(tmp_path):
    """The scenario the pipeline's own check can never catch: nothing ran."""
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=MAX_DATA_AGE_HOURS + 6)).isoformat()
    ok, message = check(_write(tmp_path, {"last_updated_utc": old}))
    assert not ok
    assert "hours old" in message


def test_missing_dataset_fails(tmp_path):
    ok, message = check(tmp_path / "does-not-exist.json")
    assert not ok
    assert "does not exist" in message


def test_missing_timestamp_fails(tmp_path):
    ok, _ = check(_write(tmp_path, {}))
    assert not ok


def test_unparseable_timestamp_fails(tmp_path):
    ok, _ = check(_write(tmp_path, {"last_updated_utc": "not a date"}))
    assert not ok
