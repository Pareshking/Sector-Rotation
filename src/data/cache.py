from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


def write_parquet(frame: pd.DataFrame, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(target, compression="zstd", index=True)
    return target


def read_parquet(path: str | Path) -> pd.DataFrame:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Prepared dataset not found: {target}")
    return pd.read_parquet(target)


def cache_key(url: str, params: dict[str, Any] | None = None) -> str:
    payload = json.dumps(params or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{url}|{payload}".encode("utf-8")).hexdigest()


def read_json_cache(path: str | Path, max_age_seconds: int | None = None) -> Any | None:
    target = Path(path)
    if not target.exists():
        return None
    if max_age_seconds is not None:
        age = pd.Timestamp.now(tz="UTC").timestamp() - target.stat().st_mtime
        if age > max_age_seconds:
            return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_json_cache(value: Any, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return target
