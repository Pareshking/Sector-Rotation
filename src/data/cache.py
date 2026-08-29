from __future__ import annotations

from pathlib import Path
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
