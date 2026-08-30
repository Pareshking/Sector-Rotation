"""Patches applied to jugaad-data before any NSE fetch happens.

Imported once, for side effects only, by every module that talks to NSE
through jugaad-data (src/data/nse_equity.py, src/data/jugaad_indices.py).
Both fixes address the same class of problem: jugaad-data's HTTP layer was
written for occasional interactive use, not for the ~150-vehicle concurrent
fan-out this pipeline runs nightly.

1. No read timeout. NSEHistory._get / NSEIndexHistory._get issue requests
   with no timeout at all. A single stalled response hangs that thread
   forever, and ThreadPoolExecutor.__exit__ — plus the interpreter's own
   non-daemon worker-thread joins at shutdown — then wait on it indefinitely.
   One slow response was enough to consume an entire CI budget.

2. Chunking three times wider than necessary. util.break_dates() always
   chunks a date range by calendar month, and stock_raw/index_raw/
   index_tri_raw all fetch through it, so a 5-year history costs ~60 requests
   per symbol regardless of how much data each request could actually carry.
   Verified directly against the live endpoint: a 3-calendar-month window
   (~92 days) returns complete, correct data; a 4-month window silently
   truncates to NSE's ~70-row response cap instead of erroring. CHUNK_DAYS is
   set well inside that margin — wide enough to cut request volume by roughly
   3x, short enough to stay safely clear of the cap.
"""

from __future__ import annotations

import socket
from datetime import timedelta

import jugaad_data.util as _ut

socket.setdefaulttimeout(30)

CHUNK_DAYS = 90


def _wide_break_dates(from_date, to_date):
    if from_date >= to_date:
        return [(from_date, to_date)]
    ranges = []
    start = from_date
    step = timedelta(days=CHUNK_DAYS - 1)
    while start < to_date:
        end = min(start + step, to_date)
        ranges.append((start, end))
        start = end + timedelta(days=1)
    return ranges


_ut.break_dates = _wide_break_dates
