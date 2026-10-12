"""Artifact contracts: what the pipeline may publish, and that it fails closed otherwise."""

import json

import numpy as np
import pandas as pd
import pytest

from src.data.contracts import (
    ContractViolation,
    enforce,
    metadata_problems,
    validate_artifacts,
)


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    """Run the fixture pipeline end to end into a temp folder and load what it wrote."""
    import pipeline.run_pipeline as rp

    out = tmp_path_factory.mktemp("processed")
    original = rp.OUTPUT
    rp.OUTPUT = out
    try:
        rp.run("fixture")
    finally:
        rp.OUTPUT = original
    frames = {
        name: pd.read_parquet(out / f"{name}.parquet")
        for name in ("summary_rankings", "etf_universe", "etf_prices", "index_prices", "cash_nav", "portfolio_target")
    }
    metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
    return out, frames, metadata


def test_the_fixture_pipeline_publishes_every_artifact_within_contract(published):
    out, frames, metadata = published
    assert sorted(p.name for p in out.iterdir()) == sorted(
        [f"{n}.parquet" for n in frames] + ["rs_matrix.parquet", "metadata.json"]
    )
    assert validate_artifacts(frames, metadata) == []


def test_the_published_target_portfolio_is_whole(published):
    _, frames, metadata = published
    target = frames["portfolio_target"]
    assert target["weight"].sum() == pytest.approx(1.0)
    assert (target["exposure_id"] == "__cash__").sum() == 1
    assert target["config_hash"].iloc[0] == metadata["strategy_hash"]
    assert metadata["target_portfolio"]["cash_hurdle_source"] in {"nav", "constant"}


def _broken(frames, name, mutate):
    copy = {k: v.copy() for k, v in frames.items()}
    copy[name] = mutate(copy[name])
    return validate_artifacts(copy)


def test_index_prices_violations(published):
    _, frames, _ = published

    def duplicate(f):
        return pd.concat([f, f.iloc[[-1]]])

    def negative(f):
        f.iloc[5, 0] = -1.0
        return f

    def benchmark_gap(f):
        f.loc[f.index[10], "__benchmark__"] = np.nan
        return f

    def unsorted(f):
        return f.iloc[::-1]

    assert any("duplicate dates" in p for p in _broken(frames, "index_prices", duplicate))
    assert any("below" in p for p in _broken(frames, "index_prices", negative))
    assert any("__benchmark__" in p for p in _broken(frames, "index_prices", benchmark_gap))
    assert any("not sorted" in p for p in _broken(frames, "index_prices", unsorted))
    assert any("missing required column '__benchmark__'" in p
               for p in _broken(frames, "index_prices", lambda f: f.drop(columns="__benchmark__")))
    assert any("rows, need at least 253" in p for p in _broken(frames, "index_prices", lambda f: f.iloc[:100]))


def test_cash_nav_must_look_like_a_liquid_fund(published):
    _, frames, _ = published

    def equity_like(f):
        f.iloc[-1, 0] = f.iloc[-2, 0] * 1.2
        return f

    assert any("not a liquid fund" in p for p in _broken(frames, "cash_nav", equity_like))


def test_summary_violations(published):
    _, frames, _ = published

    def bad_type(f):
        f.loc[f.index[0], "value_type"] = "UNKNOWN"
        return f

    def duplicated_id(f):
        return pd.concat([f, f.iloc[[0]]])

    assert any("value_type" in p for p in _broken(frames, "summary_rankings", bad_type))
    assert any("duplicate values" in p for p in _broken(frames, "summary_rankings", duplicated_id))
    assert any("missing required column 'stage'" in p
               for p in _broken(frames, "summary_rankings", lambda f: f.drop(columns="stage")))


def test_etf_universe_needs_known_vehicles_and_real_dates(published):
    _, frames, _ = published

    def bad_vehicle(f):
        f.loc[f.index[0], "vehicle"] = "crypto"
        return f

    def text_dates(f):
        f["inception_date"] = f["inception_date"].astype(str)
        return f

    assert any("vehicle" in p for p in _broken(frames, "etf_universe", bad_vehicle))
    assert any("expected datetime" in p for p in _broken(frames, "etf_universe", text_dates))


def test_portfolio_target_violations(published):
    _, frames, _ = published

    def leaky(f):
        f.loc[f.index[0], "weight"] = float(f.loc[f.index[0], "weight"]) - 0.1
        return f

    def two_dates(f):
        f.loc[f.index[0], "as_of"] = f["as_of"].iloc[0] - pd.Timedelta(days=31)
        return f

    def odd_action(f):
        f.loc[f.index[0], "action"] = "REDUCE / EXIT"
        return f

    assert any("weights sum to" in p for p in _broken(frames, "portfolio_target", leaky))
    assert any("decision dates" in p for p in _broken(frames, "portfolio_target", two_dates))
    assert any("action" in p for p in _broken(frames, "portfolio_target", odd_action))


def test_metadata_violations(published):
    _, _, metadata = published
    assert metadata_problems(metadata) == []
    assert any("benchmark_value_type" in p for p in metadata_problems({**metadata, "benchmark_value_type": "UNKNOWN"}))
    assert any("strategy_hash" in p for p in metadata_problems({**metadata, "strategy_hash": "abc"}))
    assert any("last_updated_utc" in p for p in metadata_problems({**metadata, "last_updated_utc": "2026-10-12T01:31:42"}))
    bad_alert = {**metadata, "quality_alerts": [{"severity": "fatal", "check": "x", "message": "y"}]}
    assert any("quality_alerts" in p for p in metadata_problems(bad_alert))
    missing = {k: v for k, v in metadata.items() if k != "restatements"}
    assert any("restatements" in p for p in metadata_problems(missing))


def test_an_artifact_without_a_contract_is_refused():
    assert validate_artifacts({"mystery": pd.DataFrame({"a": [1]})}) == [
        "mystery: no contract defined; every published artifact needs one"
    ]


def test_enforce_lists_every_problem_at_once(published):
    _, frames, metadata = published
    bad = {**frames, "cash_nav": frames["cash_nav"].iloc[::-1]}
    with pytest.raises(ContractViolation) as caught:
        enforce(bad, {**metadata, "strategy_hash": "abc"})
    assert len(caught.value.problems) >= 2


def test_the_pipeline_fails_closed_before_writing_anything(monkeypatch, tmp_path):
    """A contract breach in any artifact stops the run with nothing published."""
    import pipeline.run_pipeline as rp

    monkeypatch.setattr(rp, "OUTPUT", tmp_path)
    real = rp.target_frame

    def leaky(target):
        frame = real(target)
        frame.loc[frame.index[0], "weight"] = float(frame.loc[frame.index[0], "weight"]) - 0.25
        return frame

    monkeypatch.setattr(rp, "target_frame", leaky)
    with pytest.raises(ContractViolation, match="weights sum to"):
        rp.run("fixture")
    assert list(tmp_path.iterdir()) == []
