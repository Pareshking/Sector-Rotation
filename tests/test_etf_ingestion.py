import pandas as pd

from src.data import etf_data
from src.models.exposure import ETFMapping


def _mfapi_result(rows: int = 60):
    dates = pd.date_range("2026-01-01", periods=rows, freq="D")
    frame = pd.DataFrame(
        {
            "close": range(rows),
            "adjusted_close": range(rows),
        },
        index=dates,
    )
    return type(
        "Result",
        (),
        {"frame": frame, "scheme_code": 150162},
    )()


def _no_nse(monkeypatch):
    """Silence the NSE leg so a test can exercise the fallbacks behind it."""
    monkeypatch.setattr(etf_data, "fetch_nse_histories", lambda *a, **k: {})


def test_nse_is_tried_before_every_other_source(monkeypatch):
    """An ETF is an NSE-listed security; the exchange comes first.

    Yahoo going down previously dropped healthy ETFs out of the dataset because
    instruments without a scheme code went straight to it.
    """
    etf = ETFMapping(symbol="ITBEES", name="Nippon India Nifty IT ETF",
                     yfinance_symbol="ITBEES.NS")
    series = pd.Series(range(1, 300), index=pd.date_range("2026-01-01", periods=299), name="ITBEES")
    monkeypatch.setattr(etf_data, "fetch_nse_histories", lambda *a, **k: {"ITBEES": series})
    monkeypatch.setattr(etf_data, "download_market_history",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Yahoo must not run")))
    monkeypatch.setattr(etf_data, "fetch_etf_nav",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("MFAPI must not run")))

    frame, sources, _ = etf_data.fetch_etf_histories([etf])
    assert sources["ITBEES"] == "nse"
    assert "ITBEES" in frame


def test_amfi_is_tried_before_yahoo(monkeypatch):
    etf = ETFMapping(name="Kotak Nifty Realty Index Fund", scheme_code=999001,
                     vehicle="index_fund")
    _no_nse(monkeypatch)
    monkeypatch.setattr(etf_data, "fetch_all_mfapi_histories", lambda *a, **k: ({}, {}, [etf]))
    nav = pd.Series(range(1, 200), index=pd.date_range("2026-01-01", periods=199))
    monkeypatch.setattr(
        etf_data, "_amfi_fallback_batch", lambda etfs, **k: {"Kotak Nifty Realty Index Fund": nav}
    )
    monkeypatch.setattr(etf_data, "download_market_history",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Yahoo must not run")))

    _, sources, _ = etf_data.fetch_etf_histories([etf])
    assert sources["Kotak Nifty Realty Index Fund"] == "amfi"


def test_complete_mfapi_series_never_calls_yahoo(monkeypatch):
    _no_nse(monkeypatch)
    etf = ETFMapping(
        symbol="METALIETF",
        name="ICICI Prudential Nifty Metal ETF",
        scheme_code=150162,
        yfinance_symbol="METALIETF.NS",
    )
    calls = {"mfapi": 0, "yahoo": 0}

    def fake_mfapi(*args, **kwargs):
        calls["mfapi"] += 1
        return _mfapi_result()

    def fake_yahoo(*args, **kwargs):
        calls["yahoo"] += 1
        raise AssertionError("Yahoo must not run after a complete MFAPI series")

    monkeypatch.setattr(etf_data, "fetch_etf_nav", fake_mfapi)
    monkeypatch.setattr(etf_data, "download_market_history", fake_yahoo)

    frame, sources, codes = etf_data.fetch_etf_histories([etf])

    assert calls == {"mfapi": 1, "yahoo": 0}
    assert "METALIETF" in frame
    assert sources["METALIETF"] == "mfapi"
    assert codes["METALIETF"] == 150162


def test_scheme_without_complete_mfapi_can_fall_back_to_yahoo(monkeypatch):
    _no_nse(monkeypatch)
    etf = ETFMapping(
        symbol="B22",
        name="Bharat 22 ETF",
        scheme_code=143265,
        yfinance_symbol="ICICIB22.NS",
    )

    empty = type("Result", (), {"frame": pd.DataFrame(), "scheme_code": 143265})()
    yahoo = pd.DataFrame({"ICICIB22.NS": range(60)}, index=pd.date_range("2026-01-01", periods=60))

    monkeypatch.setattr(etf_data, "fetch_etf_nav", lambda *args, **kwargs: empty)
    # AMFI now sits ahead of Yahoo; it must come up empty for Yahoo to be reached.
    monkeypatch.setattr(etf_data, "_amfi_fallback_batch", lambda etfs, **k: {})
    monkeypatch.setattr(etf_data, "download_market_history", lambda *args, **kwargs: yahoo)

    frame, sources, _ = etf_data.fetch_etf_histories([etf])

    assert "B22" in frame
    assert sources["B22"] == "yahoo"


def test_amfi_fallback_downloads_the_market_report_once_for_the_whole_batch(monkeypatch):
    """AMFI's history endpoint returns every scheme for the requested window
    regardless of which one you want, and can take minutes to stream. Calling
    it once per vehicle instead of once per batch is what turned a handful of
    fallback vehicles into a pipeline run that never finished.
    """
    _no_nse(monkeypatch)
    etf_a = ETFMapping(name="Fund A", scheme_code=1001, vehicle="index_fund")
    etf_b = ETFMapping(name="Fund B", scheme_code=1002, vehicle="index_fund")
    monkeypatch.setattr(etf_data, "fetch_all_mfapi_histories", lambda *a, **k: ({}, {}, [etf_a, etf_b]))
    monkeypatch.setattr(etf_data, "download_market_history", lambda *a, **k: pd.DataFrame())

    calls = {"n": 0}
    dates = pd.date_range("2026-01-01", periods=100)

    def fake_history(*args, **kwargs):
        calls["n"] += 1
        codes = kwargs["scheme_codes"]
        rows = [{"scheme_code": code, "nav": 100.0 + i, "date": d} for code in codes for i, d in enumerate(dates)]
        return pd.DataFrame(rows)

    monkeypatch.setattr(etf_data, "fetch_amfi_history", fake_history)

    _, sources, _ = etf_data.fetch_etf_histories([etf_a, etf_b])

    assert calls["n"] == 1, "AMFI history must be fetched once for the batch, not once per vehicle"
    assert sources["Fund A"] == "amfi"
    assert sources["Fund B"] == "amfi"


def test_snapshot_merge_matches_on_nse_symbol():
    import pandas as pd

    from src.data.nse_etf import merge_snapshot

    etfs = pd.DataFrame([{"exposure_id": "auto", "symbol": "AUTOBEES"},
                         {"exposure_id": "bank", "symbol": "BANKBEES"}])
    snapshot = pd.DataFrame([{"symbol": "AUTOBEES", "traded_value": 5.0, "traded_quantity": 1.0,
                              "last_price": 100.0, "nav": 99.0, "premium_discount_pct": 1.01,
                              "week52_high": 1.0, "week52_low": 1.0, "snapshot_utc": "x"}])
    merged = merge_snapshot(etfs, snapshot)
    assert float(merged.loc[merged.symbol == "AUTOBEES", "traded_value"].iat[0]) == 5.0
    assert pd.isna(merged.loc[merged.symbol == "BANKBEES", "traded_value"].iat[0])


def test_snapshot_failure_never_breaks_the_universe():
    """A decorative live feed must not be able to fail a valid pipeline run."""
    import pandas as pd

    from src.data.nse_etf import merge_snapshot

    etfs = pd.DataFrame([{"exposure_id": "auto", "symbol": "AUTOBEES"}])
    merged = merge_snapshot(etfs, pd.DataFrame())
    assert len(merged) == 1
    assert "traded_value" in merged.columns
    assert merged["traded_value"].isna().all()


def test_premium_is_computed_from_price_over_nav():
    import pandas as pd

    from src.data.nse_etf import _number

    assert _number("1,234.50") == 1234.5
    assert pd.isna(_number("-"))
    assert pd.isna(_number(None))


def test_every_mapped_vehicle_has_a_symbol_or_a_scheme_code():
    """A vehicle nothing can be fetched by is a dead mapping."""
    from pathlib import Path

    from src.universe.registry import UniverseRegistry

    root = Path(__file__).resolve().parents[1]
    registry = UniverseRegistry.from_json(root / "data" / "universe" / "universe.json")
    for exposure in registry.all():
        for etf in exposure.etfs:
            assert etf.symbol or etf.scheme_code, f"{exposure.id}/{etf.name} has neither"


def test_index_funds_carry_a_scheme_code_not_a_ticker():
    from pathlib import Path

    from src.models.exposure import VehicleType
    from src.universe.registry import UniverseRegistry

    root = Path(__file__).resolve().parents[1]
    registry = UniverseRegistry.from_json(root / "data" / "universe" / "universe.json")
    funds = [e for x in registry.all() for e in x.etfs if e.vehicle is VehicleType.INDEX_FUND]
    assert funds, "expected at least one open-ended index fund in the universe"
    for fund in funds:
        assert fund.scheme_code, f"{fund.name} has no AMFI scheme code"
        assert fund.symbol is None, f"{fund.name} is not exchange-traded but carries a ticker"


def test_nse_timestamps_are_normalised_to_the_ist_trading_date():
    """jugaad returns UTC instants; an IST session lands at 18:30 the day before.

    Left alone, every NSE series is shifted a day against the index panel and
    silently fails to align with it at all.
    """
    import pandas as pd

    from src.data.nse_equity import _trading_dates

    utc = pd.Series(pd.to_datetime(["2026-08-27T18:30:00Z", "2026-08-28T18:30:00Z"]))
    out = _trading_dates(utc)
    assert list(out.dt.strftime("%Y-%m-%d")) == ["2026-08-28", "2026-08-29"]
    assert (out.dt.hour == 0).all()


def test_naive_midnight_dates_are_left_alone():
    import pandas as pd

    from src.data.nse_equity import _trading_dates

    naive = pd.Series(pd.to_datetime(["2026-08-27", "2026-08-28"]))
    assert list(_trading_dates(naive).dt.strftime("%Y-%m-%d")) == ["2026-08-27", "2026-08-28"]


# --------------------------------------------------------------------------- #
# NSE snapshot: retries, and carrying the last good one forward
# --------------------------------------------------------------------------- #
class _Response:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self.payload


class _Session:
    def __init__(self, response):
        self.headers, self.response = {}, response

    def get(self, url, timeout=None):
        return self.response if "api" in url else _Response({})


_ROW = {"symbol": "autobees", "ltP": "101", "nav": "100", "trdVal": "5,000", "qty": "50", "wkhi": "1", "wklo": "1"}


def test_snapshot_fetch_retries_with_a_fresh_session_until_nse_answers():
    from src.data.nse_etf import fetch_etf_snapshot

    responses = iter([_Response({}, 403), _Response({"data": [_ROW]})])
    sessions, pauses = [], []

    def factory():
        sessions.append(_Session(next(responses)))
        return sessions[-1]

    frame, error = fetch_etf_snapshot(factory, attempts=3, pause=2.0, sleep=pauses.append)
    assert error == "" and len(sessions) == 2 and pauses == [2.0]
    assert frame["symbol"].tolist() == ["AUTOBEES"]
    assert float(frame["traded_value"].iat[0]) == 5000.0
    assert abs(float(frame["premium_discount_pct"].iat[0]) - 1.0) < 1e-9


def test_a_refused_snapshot_returns_its_reason_instead_of_raising():
    from src.data.nse_etf import fetch_etf_snapshot

    frame, error = fetch_etf_snapshot(lambda: _Session(_Response({}, 403)), attempts=2, pause=0, sleep=lambda _: None)
    assert frame.empty and "HTTP 403" in error and "2 attempt" in error


def _last_good(stamp):
    import pandas as pd

    from src.data.nse_etf import COLUMNS

    row = {c: 1.0 for c in COLUMNS} | {"symbol": "AUTOBEES", "snapshot_utc": stamp}
    return pd.DataFrame([row], columns=COLUMNS)


def test_a_fresh_snapshot_wins_over_the_last_good_one():
    from src.data.nse_etf import resolve_snapshot

    fresh = _last_good("2026-10-12T09:00:00+00:00")
    resolved = resolve_snapshot(fresh, "", _last_good("2026-10-01T09:00:00+00:00"))
    assert resolved.status == "fresh" and resolved.as_of_utc == "2026-10-12T09:00:00+00:00"


def test_a_refused_snapshot_carries_the_last_good_one_forward_with_its_own_date():
    from datetime import datetime, timezone

    import pandas as pd

    from src.data.nse_etf import merge_snapshot, resolve_snapshot

    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    resolved = resolve_snapshot(pd.DataFrame(), "HTTP 403", _last_good("2026-10-11T01:09:00+00:00"), now=now)
    assert resolved.status == "carried_forward" and resolved.error == "HTTP 403"
    assert resolved.as_of_utc.startswith("2026-10-11T01:09")
    merged = merge_snapshot(pd.DataFrame([{"symbol": "AUTOBEES"}]), resolved.snapshot)
    assert merged["snapshot_utc"].iat[0] == "2026-10-11T01:09:00+00:00"


def test_a_snapshot_older_than_the_limit_is_dropped_not_shown():
    from datetime import datetime, timezone

    import pandas as pd

    from src.data.nse_etf import resolve_snapshot

    now = datetime(2026, 10, 30, tzinfo=timezone.utc)
    resolved = resolve_snapshot(pd.DataFrame(), "HTTP 403", _last_good("2026-10-11T01:09:00+00:00"), now=now)
    assert resolved.status == "unavailable" and resolved.snapshot.empty
    assert "older than 14 days" in resolved.error
    assert resolve_snapshot(pd.DataFrame(), "timeout", pd.DataFrame()).status == "unavailable"


def test_the_last_good_snapshot_survives_a_missing_file(tmp_path):
    from src.data.nse_etf import COLUMNS, load_last_snapshot

    assert load_last_snapshot(tmp_path / "absent.parquet").columns.tolist() == COLUMNS


def test_a_stale_or_missing_snapshot_is_a_warning_never_an_error():
    from src.quantitative.quality import check_dataset

    for status, check in (("carried_forward", "etf_snapshot_carried_forward"), ("unavailable", "etf_snapshot_unavailable")):
        report = check_dataset({"etf_snapshot": {"status": status, "as_of_utc": "x", "error": "HTTP 403"}}, None)
        alerts = [a for a in report.alerts if a["check"] == check]
        assert alerts and alerts[0]["severity"] == "warning" and "HTTP 403" in alerts[0]["message"]
        assert report.ok
    fresh = check_dataset({"etf_snapshot": {"status": "fresh"}}, None)
    assert not [a for a in fresh.alerts if a["check"].startswith("etf_snapshot")]
