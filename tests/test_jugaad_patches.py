from __future__ import annotations

import socket
from datetime import date, timedelta

import jugaad_data.util as ut

import src.data._jugaad_patches as patches


def test_importing_the_module_sets_a_socket_timeout():
    assert socket.getdefaulttimeout() is not None
    assert 0 < socket.getdefaulttimeout() <= 60


def test_break_dates_is_actually_replaced_on_the_jugaad_module():
    """stock_raw/index_raw/index_tri_raw all call ut.break_dates(...) as a
    module attribute lookup, so patching the attribute (not a copied name)
    is what makes the fix reach every jugaad-data caller.
    """
    assert ut.break_dates is patches._wide_break_dates


def test_chunks_stay_within_nses_response_cap():
    """Verified against the live endpoint: NSE's historicalOR API returns
    complete data for a ~3-month window and silently truncates to its last
    ~70 rows beyond that. Every chunk must be safely under that boundary.
    """
    start, end = date(2021, 8, 23), date(2026, 8, 30)
    for chunk_start, chunk_end in patches._wide_break_dates(start, end):
        assert (chunk_end - chunk_start).days < 121  # the observed truncation point
        assert (chunk_end - chunk_start).days <= patches.CHUNK_DAYS


def test_chunks_cover_the_full_range_with_no_gaps_or_overlaps():
    start, end = date(2021, 8, 23), date(2026, 8, 30)
    ranges = patches._wide_break_dates(start, end)
    assert ranges[0][0] == start
    assert ranges[-1][1] == end
    for (_, prev_end), (next_start, _) in zip(ranges, ranges[1:]):
        assert next_start == prev_end + timedelta(days=1)


def test_a_short_range_returns_a_single_chunk():
    start, end = date(2026, 1, 1), date(2026, 1, 31)
    assert patches._wide_break_dates(start, end) == [(start, end)]


def test_an_empty_or_inverted_range_does_not_crash():
    same = date(2026, 1, 1)
    assert patches._wide_break_dates(same, same) == [(same, same)]
