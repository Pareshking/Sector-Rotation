# India Sector Rotation

Exposure-first quantitative sector and thematic rotation research for Indian equities. The repository separates the canonical **Exposure** (sector/theme + benchmark) from its ETF implementations, authoritative index ingestion, quantitative calculations, and Streamlit presentation.

## Production data flow

```text
NSE Indices / Jugaad NSE adapter / AMFI / explicitly matched ETF sources
          |
          v
Universe Registry -> Exposure -> canonical Nifty benchmark
          |
          v
Quantitative engine -> Prepared Parquet + metadata.json -> Streamlit
```

The Streamlit application is presentation-only for historical data: it reads prepared files from `data/processed/` and does not perform bulk historical downloads.

## Data provenance and hierarchy

**Canonical index histories:** the pipeline attempts the named Nifty/NSE history first. When the direct endpoint is unavailable, `jugaad-data` is used as an NSE/NiftyIndices retrieval adapter for the same named index. `niftyindices_jugaad` identifies this retrieval route; it must not be described as synthetic data, an ETF proxy, or a separately calculated TRI series.

If an explicitly exposure-matched ETF/NAV series is used, its lineage remains ETF/NAV and the mapping must be exact. Nearest-category substitution, broad-market substitution, and synthetic benchmark construction are prohibited.

**Decision gate:** a history requires at least **250 observations** to enter the decision-grade Mansfield 52-week and 12-month calculations. Short histories remain visible where supported by the application, but are not padded, extrapolated, or converted into decision signals.

**ETF market data:** configured NSE trading symbols are the canonical ETF identifiers. Yahoo Finance `.NS` symbols, where used, are retrieval adapters rather than authoritative ticker definitions. Verified legacy ticker aliases may be retained.

**ETF NAV:** AMFI historical NAV can recover explicitly mapped ETF/fund histories when market-price retrieval is unavailable. An ETF/NAV series is never accepted merely because it is in the same broad sector.

## Daily production refresh

The GitHub Actions data workflow runs every day at **04:00 IST** (`22:30 UTC` on the previous calendar day). It runs the live pipeline and commits changes under `data/processed/` back to `main`. The pipeline uses the latest available market observation, so weekends and NSE holidays naturally use the most recent working-day observation.

The workflow is concurrency-protected so overlapping production runs do not intentionally compete. Generated data is the only workflow output committed automatically; source code changes are reviewed and committed separately.

## Decision-grade principles

1. **No synthetic benchmark proxies.** A benchmark must represent the declared exposure.
2. **Source lineage is explicit.** Retrieval mechanism and financial instrument are not conflated.
3. **250 observations is the decision boundary.** No NaN padding or artificial history is used to satisfy it.
4. **Exposure comes before ETF.** ETF liquidity, tracking characteristics, or ticker mechanics must not redefine sector strength.
5. **Catalogue membership is not universe membership.** NSE publishes many ESG, Shariah, corporate-group, factor, size, liquidity, and strategy indices that are not automatically sector-rotation exposures.

## Domain model

`Exposure` is the primary object. Each exposure contains its canonical sector/thematic category, canonical Nifty benchmark, optional retrieval symbols, and ETF implementations where available.

This separation prevents an ETF-specific liquidity or tracking characteristic from being interpreted as sector strength.

## Quantitative definitions

For lookback `L`:

`R_L = P_t / P_{t-L} - 1`

Relative momentum against Nifty 50:

`DM_L = R_exposure,L - R_benchmark,L`

For Mansfield Relative Strength, calculate the price-relative series and use Friday observations:

`RS_t = P_exposure,t / P_benchmark,t`

`MRS_t = 100 * (RS_t / SMA(RS_t, 52) - 1)`

RS momentum is the 13-week change in MRS.

## Development and verification

Run the test suite before production changes. For a live data validation run:

```bash
pytest -q
python -m pipeline.run_pipeline --mode live
```

Inspect both generated Parquet data and `metadata.json`. Confirm observation counts, dates, source lineage, missing/short histories, and decision-grade eligibility rather than relying only on a successful process exit.

## Current catalogue versus rotation universe

The NSE catalogue is broader than the curated rotation universe. Sectoral and thematic indices can be evaluated as candidate exposures, while ESG, Shariah, corporate-group, factor/strategy, size/liquidity, IPO and similar indices require separate justification before entering the rotation model. Overlapping variants (for example equal-weight alternatives or closely related infrastructure/mobility variants) should not automatically be counted as independent economic sectors.
