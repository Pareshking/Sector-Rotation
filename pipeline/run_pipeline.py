from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.cache import write_parquet
from src.data.etf_data import fetch_etf_histories
from src.data.index_data import download_canonical_indices, download_history
from src.quantitative.relative_strength import mansfield_relative_strength, rs_momentum, rs_ratio, rs_stage
from src.quantitative.ranking import rank_exposures
from src.universe.registry import UniverseRegistry
from src.universe.validation import validate_universe

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_PATH = ROOT / "data" / "universe" / "universe.json"
OUTPUT = ROOT / "data" / "processed"


def build_fixture(registry, days=1300):
    rng = np.random.default_rng(42); dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    benchmark = pd.Series(100*np.exp(np.cumsum(rng.normal(.00035,.008,len(dates)))), index=dates, name=registry.benchmark_name)
    columns = {e.id: pd.Series(100*np.exp(np.cumsum(rng.normal(.00015+(i%7)*.00003,.011,len(dates)))), index=dates) for i,e in enumerate(registry.all())}
    etfs = _etf_frame(registry)
    etf_prices = pd.DataFrame({etf.symbol or etf.name: pd.Series(100*np.exp(np.cumsum(rng.normal(.0002,.01,len(dates)))), index=dates) for e in registry.all() for etf in e.etfs})
    health = {"total_canonical_exposures":len(registry.all()),"valid_canonical_series":len(registry.all()),"skipped_canonical_series":0,"canonical_coverage_ratio":1.0,"fallback_canonical_exposures":[],"skipped_canonical_exposures":[],"missing_yfinance_symbols":[],"source_counts":{"nse":len(registry.all()),"niftyindices_tri":0,"niftyindices_pr":0,"yahoo":0,"mfapi":int(etf_prices.shape[1]),"amfi":0},"etf_total":int(etf_prices.shape[1]),"etf_valid_series":int(etf_prices.shape[1]),"etf_coverage_ratio":1.0,"etf_skipped_symbols":[],"resolved_official_index_names":{e.id:e.benchmark for e in registry.all()}}
    return pd.DataFrame(columns), benchmark, etfs, etf_prices, health


def _etf_frame(registry):
    rows=[]
    for e in registry.all():
        for etf in e.etfs:
            rows.append({"exposure_id":e.id,"exposure":e.name,"category":e.category.value,"symbol":etf.symbol,"name":etf.name,"scheme_code":etf.scheme_code,"yfinance_symbol":etf.yfinance_symbol,"aliases":",".join(etf.aliases),"aum_crore":etf.tracking.aum_crore,"expense_ratio":etf.tracking.expense_ratio,"liquidity_score":etf.tracking.liquidity_score,"tracking_error":etf.tracking.tracking_error})
    return pd.DataFrame(rows)


def build_live(registry):
    exposure_names={e.id:e.benchmark for e in registry.all()}; etf_objects=[etf for e in registry.all() for etf in e.etfs]
    etf_history, etf_sources, resolved_codes = fetch_etf_histories(etf_objects, years=5)
    prices=download_canonical_indices(exposure_names,{e.id:e.yfinance_symbol for e in registry.all()},years=5,etf_histories=etf_history)
    benchmark_frame=download_history([registry.benchmark_symbol],years=5)
    if benchmark_frame.empty: raise RuntimeError("Unable to download Nifty 50 benchmark history")
    benchmark=benchmark_frame.iloc[:,0]
    valid=[e.id for e in registry.all() if e.id in prices and prices[e.id].dropna().size>=60]; skipped=[e.id for e in registry.all() if e.id not in valid]
    source_by_exposure=dict(prices.attrs.get("source_by_exposure",{})); resolved_names=dict(prices.attrs.get("resolved_name_by_exposure",{}))
    source_counts={k:sum(v==k for v in source_by_exposure.values()) for k in ("niftyindices_tri","niftyindices_pr","nse_api","nse_archive","yahoo","etf_proxy","seed_cache")}
    source_counts["mfapi"]=sum(v=="mfapi" for v in etf_sources.values()); source_counts["amfi"]=sum(v=="amfi" for v in etf_sources.values()); source_counts["nse"]=source_counts["niftyindices_tri"]+source_counts["niftyindices_pr"]+source_counts["nse_api"]+source_counts["nse_archive"]
    etf_keys=[etf.symbol or etf.name for etf in etf_objects]; etf_valid=sum(k in etf_history and etf_history[k].dropna().size>=20 for k in etf_keys)
    health={"total_canonical_exposures":len(registry.all()),"valid_canonical_series":len(valid),"skipped_canonical_series":len(skipped),"canonical_coverage_ratio":len(valid)/max(len(registry.all()),1),"fallback_canonical_exposures":[eid for eid in valid if source_by_exposure.get(eid) not in {"niftyindices_tri","niftyindices_pr"}],"skipped_canonical_exposures":skipped,"missing_yfinance_symbols":[e.id for e in registry.all() if not e.yfinance_symbol],"source_counts":source_counts,"source_by_canonical_exposure":source_by_exposure,"resolved_official_index_names":resolved_names,"etf_total":len(etf_objects),"etf_valid_series":etf_valid,"etf_coverage_ratio":etf_valid/max(len(etf_objects),1),"etf_skipped_symbols":[k for k in etf_keys if k not in etf_history or etf_history[k].dropna().size<20],"etf_source_by_symbol":etf_sources,"resolved_mfapi_scheme_codes":resolved_codes}
    return prices,benchmark,_etf_frame(registry),etf_history,health


def run(mode):
    registry=UniverseRegistry.from_json(UNIVERSE_PATH); report=validate_universe(registry.all())
    if not report.valid: raise ValueError("Invalid universe: "+"; ".join(report.errors))
    if mode=="fixture": prices,benchmark,etfs,etf_history,health=build_fixture(registry)
    elif mode=="live": prices,benchmark,etfs,etf_history,health=build_live(registry)
    else: raise ValueError("mode must be fixture or live")
    common=prices.index.intersection(benchmark.dropna().index); prices=prices.loc[common].sort_index(); benchmark=benchmark.loc[common].sort_index()
    if prices.empty: raise RuntimeError("No overlapping benchmark/exposure history was downloaded")
    rankings=rank_exposures(prices,benchmark); summary_rows=[]; rs_series={}
    for e in registry.all():
        if e.id not in prices: continue
        asset=prices[e.id]; mrs=mansfield_relative_strength(asset,benchmark); ratio=rs_ratio(asset,benchmark); momentum=rs_momentum(mrs); rs_series[e.id]=mrs
        latest_ratio=ratio.dropna().iloc[-1] if not ratio.dropna().empty else np.nan; latest_momentum=momentum.dropna().iloc[-1] if not momentum.dropna().empty else np.nan; rank_row=rankings.loc[e.id]
        summary_rows.append({"exposure_id":e.id,"exposure":e.name,"category":e.category.value,"benchmark":e.benchmark,"resolved_official_index_name":health.get("resolved_official_index_names",{}).get(e.id,e.benchmark),"data_source":health.get("source_by_canonical_exposure",{}).get(e.id,"unknown"),"rs_ratio":latest_ratio,"rs_momentum":latest_momentum,"stage":rs_stage(latest_ratio,latest_momentum),"momentum_z":rank_row["momentum_z"],"rank":rank_row["rank"],**{f"return_{label}":rank_row[f"return_{label}"] for label in ("1M","3M","6M","12M")}})
    summary=pd.DataFrame(summary_rows).sort_values("rank"); OUTPUT.mkdir(parents=True,exist_ok=True)
    write_parquet(summary,OUTPUT/"summary_rankings.parquet"); write_parquet(pd.DataFrame(rs_series).sort_index(),OUTPUT/"rs_matrix.parquet"); write_parquet(etfs,OUTPUT/"etf_universe.parquet"); write_parquet(etf_history,OUTPUT/"etf_prices.parquet")
    metadata={"mode":mode,"benchmark":registry.benchmark_name,"last_updated_utc":pd.Timestamp.now(tz="UTC").isoformat(),"observations":int(len(prices)),"valid_series":int(prices.shape[1]),"etf_series":int(etf_history.shape[1]),"coverage_ratio":float(prices.shape[1]/max(len(registry.all()),1)),"validation_warnings":list(report.warnings),**health}; (OUTPUT/"metadata.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8")
    if mode=="live" and float(health["canonical_coverage_ratio"])<1.0: raise RuntimeError(f"Canonical index coverage below 100%: {health['skipped_canonical_exposures']}")
    print(json.dumps(metadata))

if __name__=="__main__":
    parser=argparse.ArgumentParser(description="Build the Sector-Rotation prepared dataset"); parser.add_argument("--mode",choices=("fixture","live"),default="fixture"); run(parser.parse_args().mode)
