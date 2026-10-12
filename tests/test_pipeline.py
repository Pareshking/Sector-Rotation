from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "data_pipeline.yml"


def test_production_workflow_runs_the_pipeline_strict():
    """A quality error must stop the run, not just get logged into metadata.json.

    run_pipeline.py only raises on an error-level alert when --strict is passed;
    the flag defaulting to off is invisible from inside the module itself, so
    the thing that actually needs pinning down is the production workflow's
    own invocation.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    line = next(line for line in text.splitlines() if "pipeline.run_pipeline --mode live" in line)
    assert "--strict" in line


def test_the_pipeline_imports_the_jugaad_patches_module():
    """jugaad-data's HTTP layer issues requests with no read timeout and chunks
    date ranges three times wider than NSE's own response cap allows — see
    src/data/_jugaad_patches.py, which fixes both. Importing the production
    entrypoint must pull that module in transitively (via etf_data/nse_equity
    and index_data/jugaad_indices) so the fix is never accidentally dropped
    from the import chain. The patches' own effects are exercised directly in
    test_jugaad_patches.py.
    """
    import sys

    import pipeline.run_pipeline  # noqa: F401

    assert "src.data._jugaad_patches" in sys.modules


def _panel(days: int = 30):
    import numpy as np
    import pandas as pd

    index = pd.bdate_range("2026-01-01", periods=days)
    prices = pd.DataFrame({"auto": np.linspace(100, 130, days), "bank": np.linspace(50, 40, days)}, index=index)
    benchmark = pd.Series(np.linspace(1000, 1100, days), index=index)
    return prices, benchmark


def test_clean_price_inputs_pass_validation():
    from pipeline.run_pipeline import price_input_problems

    assert price_input_problems(*_panel()) == []


def test_a_non_positive_index_level_is_caught_before_ranking():
    from pipeline.run_pipeline import price_input_problems

    prices, benchmark = _panel()
    prices.iloc[10, 0] = 0.0
    problems = price_input_problems(prices, benchmark)
    assert any("canonical index panel" in p and "non-positive" in p for p in problems)
    assert any("infinite" in p for p in problems)


def test_a_duplicated_date_is_caught_before_ranking():
    import pandas as pd

    from pipeline.run_pipeline import price_input_problems

    prices, benchmark = _panel()
    prices = pd.concat([prices, prices.iloc[[-1]]])
    assert any("duplicate dates" in p for p in price_input_problems(prices, benchmark))


def test_a_bad_benchmark_is_caught_before_ranking():
    from pipeline.run_pipeline import price_input_problems

    prices, benchmark = _panel()
    benchmark.iloc[5] = -1.0
    assert any(p.startswith("benchmark:") for p in price_input_problems(prices, benchmark))


def test_invalid_prices_stop_the_run_before_anything_is_written(monkeypatch, tmp_path):
    import pytest

    import pipeline.run_pipeline as rp

    monkeypatch.setattr(rp, "OUTPUT", tmp_path)
    real_fixture = rp.build_fixture

    def broken(registry):
        prices, benchmark, etfs, etf_prices, cash, health = real_fixture(registry, days=400)
        prices.iloc[100, 0] = -5.0
        return prices, benchmark, etfs, etf_prices, cash, health

    monkeypatch.setattr(rp, "build_fixture", broken)
    with pytest.raises(ValueError, match="Price validation failed before ranking"):
        rp.run("fixture")
    assert not any(tmp_path.iterdir())


def _fake_nse(calls, value_type_by_name=None, fail=()):
    """A stand-in for fetch_jugaad_index: a straight-line series over the requested window."""
    import pandas as pd

    def fetch(name, start, end, calendar=None, value_types=("TRI", "CLOSE"), min_observations=60):
        calls.append({"name": name, "start": pd.Timestamp(start), "calendar": calendar, "value_types": value_types})
        if name in fail:
            empty = pd.Series(dtype=float)
            empty.attrs["errors"] = ["TRI: ConnectionError: down", "CLOSE: ConnectionError: down"]
            return empty
        index = pd.bdate_range(start, end)
        days = (index - pd.Timestamp("2015-01-01")).days.to_numpy()
        series = pd.Series(1000.0 + days * (1 + len(name) / 100), index=index, name=name)
        kind = (value_type_by_name or {}).get(name, "TRI")
        series.attrs.update(source="niftyindices_jugaad", resolved_name=name, value_type=kind)
        return series

    return fetch


def _offline(monkeypatch, fetch):
    """Point build_live at the fake NSE fetcher and keep every other source offline."""
    import pandas as pd

    import pipeline.run_pipeline as rp
    import src.data.ingest as ingest

    monkeypatch.setattr(ingest, "_fetcher", lambda: fetch)
    monkeypatch.setattr(rp, "fetch_etf_histories", lambda etfs, years: (pd.DataFrame(), {}, {}))

    def no_cash(store, scheme_code, expected_name, fetch=None):
        return pd.Series(dtype=float, name="nav"), ingest.SeriesIngest(str(scheme_code), "seed", error="offline")

    monkeypatch.setattr(rp, "ingest_cash", no_cash)
    return rp


def test_the_live_build_records_the_benchmark_value_type_and_uses_its_calendar(monkeypatch, tmp_path):
    """The benchmark's own value type reaches metadata, and its sessions are every exposure's calendar."""
    from datetime import date

    from src.config import load_strategy_config
    from src.data.calendar import TradingCalendar
    from src.universe.registry import UniverseRegistry

    calls = []
    rp = _offline(monkeypatch, _fake_nse(calls, {"NIFTY 50": "CLOSE"}))
    registry = UniverseRegistry.from_json(rp.UNIVERSE_PATH)
    prices, benchmark, _, _, _, health = rp.build_live(
        registry, load_strategy_config(), store_root=tmp_path, today=date(2026, 9, 30)
    )
    assert health["benchmark_value_type"] == "CLOSE"
    assert health["benchmark_source"] == "niftyindices_jugaad"
    exposure_calls = [c for c in calls if c["name"] != "NIFTY 50"]
    assert exposure_calls and all(isinstance(c["calendar"], TradingCalendar) for c in exposure_calls)
    assert exposure_calls[0]["calendar"].sessions.equals(benchmark.index)
    assert health["ingest"]["benchmark"]["mode"] == "seed"
    assert (tmp_path / "index" / "nifty-50").exists()


def test_an_unreachable_benchmark_reports_why(monkeypatch, tmp_path):
    from datetime import date

    import pytest

    from src.config import load_strategy_config
    from src.universe.registry import UniverseRegistry

    rp = _offline(monkeypatch, _fake_nse([], fail=("NIFTY 50",)))
    with pytest.raises(RuntimeError, match="ConnectionError: down"):
        rp.build_live(
            UniverseRegistry.from_json(rp.UNIVERSE_PATH), load_strategy_config(),
            store_root=tmp_path, today=date(2026, 9, 30),
        )


def test_a_second_run_fetches_only_new_sessions_plus_the_overlap(monkeypatch, tmp_path):
    """The archive grows: night two asks for 10 stored sessions plus what is new, nothing older."""
    from datetime import date

    import pandas as pd

    from src.config import load_strategy_config
    from src.universe.registry import UniverseRegistry

    calls = []
    rp = _offline(monkeypatch, _fake_nse(calls))
    registry = UniverseRegistry.from_json(rp.UNIVERSE_PATH)
    strategy = load_strategy_config()
    first, *_ = rp.build_live(registry, strategy, store_root=tmp_path, today=date(2026, 9, 30))
    calls.clear()
    second, benchmark, *_rest, health = rp.build_live(registry, strategy, store_root=tmp_path, today=date(2026, 10, 9))
    sessions = benchmark.index
    expected_start = sessions[sessions.get_loc(pd.Timestamp("2026-09-30")) - 10]
    assert {c["start"] for c in calls} == {expected_start}
    assert all(c["value_types"] == ("TRI",) for c in calls)
    assert second.index.min() == first.index.min()  # nothing dropped
    assert second.index.max() == pd.Timestamp("2026-10-09")
    assert health["ingest"]["indices"]["auto"] == {"mode": "incremental", "new_sessions": 7, "value_type": "TRI"}
