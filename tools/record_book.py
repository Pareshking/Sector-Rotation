"""Append the model book's newly closed months to its forward record.

Run nightly after the pipeline, before the data is committed. Builds the same
replayed book the Portfolio page shows (``app.data.load_replayed_book``) and
adds every closed month from Nov 2026 that the record lacks
(``src/portfolio/record.py``). Rows already in the record are never changed,
so a later data revision cannot rewrite a recorded month.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# st.cache_data works without a running app; silence its "no runtime" warnings.
logging.getLogger("streamlit").setLevel(logging.ERROR)

from app.data import BOOK_RECORD, load_replayed_book  # noqa: E402
from src.portfolio.record import extend_record, read_record  # noqa: E402


def main() -> int:
    book = load_replayed_book()
    if not book.ok:
        print("Model book not built; nothing recorded.")
        return 0
    record = read_record(BOOK_RECORD)
    updated = extend_record(record, book.monthly, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    added = len(updated) - len(record)
    if added:
        updated.to_csv(BOOK_RECORD, index=False)
    print(f"Recorded {added} new month(s); {len(updated)} in the record.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
