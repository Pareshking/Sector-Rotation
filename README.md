# India Sector Rotation

Exposure-first quantitative sector and thematic rotation research for Indian equities. The repository separates the canonical **Exposure** (sector/theme + benchmark) from its ETF implementations, authoritative index ingestion, quantitative calculations, and Streamlit presentation.

## Architecture

```text
NSE Indices / Yahoo / AMFI
          |
          v
Universe Registry -> Exposure -> canonical Nifty benchmark
          |
          +--> authoritative NiftyIndices fallback
          +--> ETF NSE symbol aliases
          +--> AMFI historical NAV fallback
          |
          v
Quantitative engine
  - 1M / 3M / 6M / 12M relative returns
  - weekly Mansfield Relative Strength
  - cross-sectional Z-scores
  - percentile ranks
  - RS ratio + RS momentum stage
          |
          v
Prepared Parquet + metadata.json
          |
          v
Streamlit UI (read-only)
```

## Data hierarchy

**Canonical index benchmarks:** Yahoo Finance is the fast path; the official NSE Indices historical-data service at `niftyindices.com` is the authoritative fallback when Yahoo is missing or invalid. The official site exposes historical index data and identifies NSE Indices Limited as the publisher. 

**ETF market prices:** configured NSE trading symbols are used as the canonical ETF identifiers. Yahoo Finance `.NS` symbols are adapters, not authoritative ticker definitions. Legacy NSE ticker changes are retained as aliases where verified.

**ETF NAV fallback:** AMFI's official historical NAV endpoint is available for bounded date-range backfills. The adapter chunks requests so illiquid or unsupported Yahoo ETF series can be recovered without fabricating prices.

The Streamlit application never performs bulk historical downloads. It reads prepared files from `data/processed/` only.

## Domain model

`Exposure` is the primary object. Each exposure contains:

- canonical sector/thematic category
- canonical Nifty benchmark
- optional Yahoo Finance benchmark symbol
- zero, one, or multiple ETF implementations
- verified NSE symbol
- optional legacy ticker aliases
- optional AUM, expense ratio, liquidity and tracking-error metadata

This prevents an ETF-specific liquidity or tracking characteristic from being interpreted as sector strength.

## Quantitative definitions

### Relative return

For lookback `L`:

`R_L = P_t / P_{t-L} - 1`

Relative momentum against Nifty 50 is:

`DM_L = R_exposure,L - R_benchmark,L`

### Mansfield Relative Strength

First calculate the price-relative series and resample to Friday observations:

`RS_t = P_exposure,t / P_benchmark,t`

Then use the 52-week rolling mean baseline:

`MRS_t = 100 * (RS_t / SMA(RS_t, 52) - 1)`

RS momentum is the 13-week change in MRS.

### Stage

The RRG-style stage uses:

- **Leading:** RS ratio >= 1 and momentum >= 0
- **Weakening:** RS ratio >= 1 and momentum < 0
- **Lagging:** RS ratio < 1 and momentum < 0
- **Improving:** RS ratio < 1 and momentum >= 0

## Data health telemetry

Every live pipeline run writes `data/processed/metadata.json` with:

- UTC update timestamp
- total canonical exposures
- valid canonical series
- skipped canonical series
- canonical coverage ratio
- fallback exposures using Nifty Indices
- exposures missing Yahoo symbols
- ETF series count
- ETF symbols still skipped after AMFI fallback

The Streamlit overview displays this health state before the analytical content.

## Local setup

Python 3.12 is recommended.

```bash
git clone https://github.com/Pareshking/Sector-Rotation.git
cd Sector-Rotation
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
.venv\\Scripts\\Activate.ps1
```

## Fixture mode

Generate a deterministic offline dataset:

```bash
python -m pipeline.run_pipeline --mode fixture
pytest -q
```

## Live mode

```bash
python -m pipeline.run_pipeline --mode live
```

Live mode fails closed if canonical coverage is below 100%. It does not silently publish an incomplete canonical universe.

A five-year window is requested where the authoritative source has sufficient history. For newly created indices, "100% coverage" means every configured canonical index has a valid authoritative series, not that a newly launched index is incorrectly backfilled before its actual inception date.

## GitHub Actions

`.github/workflows/data_pipeline.yml` runs on main updates, manually, and on weekdays. It builds the live dataset and commits changed `data/processed/` artifacts. The `paths-ignore` rule prevents generated-data commits from recursively launching another pipeline run.

## Streamlit Community Cloud

Use `app/streamlit_app.py` as the application entrypoint and the root `requirements.txt` for dependencies. The app does not require API secrets for the public prepared dataset and performs no historical bulk downloads at page load.

## Data limitations

1. ETF traded-price history is not identical to ETF NAV history.
2. A newly launched ETF cannot legitimately provide five years of traded history.
3. Newly launched Nifty indices may have shorter authoritative histories.
4. Missing AUM, expense ratio, liquidity and tracking-error values remain null rather than being invented.
5. Survivorship and index-reconstitution effects must be considered before using historical rankings for backtests.

## Development principles

- No live downloads from Streamlit pages.
- No ETF treated as the canonical sector/theme.
- No fabricated historical observations.
- Missing data is explicit and testable.
- Official Nifty index data is the fallback authority for canonical benchmarks.
- Quantitative calculations remain independent of the UI.
- Production datasets are generated by the pipeline and stored as compressed Parquet.
