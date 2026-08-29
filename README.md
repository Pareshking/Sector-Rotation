# India Sector Rotation

Exposure-first quantitative sector and thematic rotation research for Indian equities. The repository separates the canonical **Exposure** (sector/theme + benchmark) from its ETF implementations, historical data extraction, quantitative calculations, and Streamlit presentation.

## Scope

The universe covers major NSE/Nifty sectoral and thematic exposures. NSE Indices currently maintains separate sectoral and thematic index families; the registry is intentionally exposure-first so multiple ETFs tracking one benchmark do not become duplicate sector observations. citeturn0search0turn0search1

## Architecture

```text
NSE/Nifty + ETF data
        |
        v
Universe Registry -> Exposure -> canonical benchmark
        |
        +--> historical prices
        +--> AMFI NAV validation
        |
        v
Quantitative engine
  - 1M / 3M / 6M / 12M relative returns
  - Mansfield Relative Strength
  - cross-sectional Z-scores
  - percentile ranks
  - RS ratio + RS momentum stage
        |
        v
Prepared Parquet datasets
        |
        v
Streamlit UI
```

## Domain model

`Exposure` is the primary object. Each exposure contains:

- canonical sector/thematic category
- canonical Nifty benchmark
- optional Yahoo Finance benchmark symbol
- zero, one, or multiple ETF implementations
- optional AUM, expense ratio, liquidity and tracking-error metadata

This prevents an ETF-specific liquidity or tracking characteristic from being interpreted as sector strength.

## Data policy

The live pipeline uses Yahoo Finance for the initial historical implementation and keeps the data adapter isolated so NSE historical APIs can be substituted or added without changing the quantitative layer. AMFI NAV is a secondary validation source.

The Streamlit application never performs bulk historical downloads. It reads prepared files from `data/processed/` only.

Generated datasets:

- `summary_rankings.parquet` — latest exposure ranking and metrics
- `rs_matrix.parquet` — historical Mansfield RS matrix
- `etf_universe.parquet` — ETF implementation metadata
- `metadata.json` — pipeline provenance

## Quantitative definitions

### Relative return

For lookback \(L\):

`R_L = P_t / P_{t-L} - 1`

Relative momentum against Nifty 50 is:

`DM_L = R_exposure,L - R_benchmark,L`

### Mansfield Relative Strength

First calculate the price-relative series:

`RS_t = P_exposure,t / P_benchmark,t`

Then use the rolling mean baseline:

`MRS_t = 100 * (RS_t / SMA(RS_t, 52) - 1)`

The 52-period default is a weekly-style Mansfield window. The implementation uses the available daily series; this is explicitly documented because daily-vs-weekly convention changes the numerical output.

### Stage

The RRG-style stage uses:

- **Leading:** RS ratio >= 1 and momentum >= 0
- **Weakening:** RS ratio >= 1 and momentum < 0
- **Lagging:** RS ratio < 1 and momentum < 0
- **Improving:** RS ratio < 1 and momentum >= 0

This is a transparent classification, not a claim that these labels are predictive by themselves.

## Local setup

Python 3.12 is recommended.

```bash
git clone https://github.com/Pareshking/Sector-Rotation.git
cd Sector-Rotation
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell activation:

```powershell
.venv\\Scripts\\Activate.ps1
```

## Generate a deterministic fixture dataset

The fixture mode is offline and reproducible:

```bash
python -m pipeline.run_pipeline --mode fixture
```

Then run tests:

```bash
pytest -q
```

Run Streamlit:

```bash
streamlit run app/streamlit_app.py
```

## Generate live data

```bash
python -m pipeline.run_pipeline --mode live
```

The live run requests approximately five years of adjusted historical prices for the benchmark and those canonical exposures that have a configured Yahoo Finance symbol. Newer or unsupported Nifty indices remain present in the registry but are not silently fabricated.

## GitHub Actions

`.github/workflows/data_pipeline.yml` provides manual and weekday scheduled execution. The workflow installs the pinned dependency ranges, runs the live pipeline, and commits changed prepared datasets.

For a public Streamlit Community Cloud deployment, point the app entrypoint at `app/streamlit_app.py`. The app is intentionally lightweight and does not require secrets for the fixture dataset.

## Data limitations

1. ETF trading history is not the same thing as index history or ETF NAV.
2. A newly launched ETF cannot legitimately provide five years of traded history.
3. Some newer Nifty thematic/sectoral indices do not have stable Yahoo Finance symbols; those exposures remain in the registry but are excluded from live calculations until an authoritative index adapter is added.
4. The current ETF metadata registry only contains mappings whose symbols are explicitly configured; missing AUM/expense/tracking fields are represented as null rather than invented.
5. Survivorship and index-reconstitution effects must be considered before using historical rankings for backtests.

## Development principles

- No live downloads from Streamlit pages.
- No ETF treated as the canonical sector/theme.
- No fabricated historical data.
- Missing data is explicit and testable.
- Quantitative calculations remain independent of the UI.
- All production datasets are generated by the pipeline and stored as compressed Parquet.
