# India Sector Rotation

Exposure-first quantitative sector and thematic rotation research for Indian equities. The repository separates the canonical **Exposure** (sector/theme + benchmark) from its ETF implementations, authoritative index ingestion, quantitative calculations, and Streamlit presentation.

## Architecture

```text
NSE Indices / Jugaad NSE adapter / AMFI / ETF sources
          |
          v
Universe Registry -> Exposure -> canonical Nifty benchmark
          |
          +--> direct NiftyIndices/NSE history
          +--> Jugaad-data NSE/NiftyIndices retrieval adapter
          +--> explicitly matched ETF/NAV fallback
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

**Canonical index benchmarks:** the pipeline first attempts direct NiftyIndices/NSE historical data. If the direct endpoint is unavailable, the Jugaad-data NSE/NiftyIndices adapter is used to retrieve the same named NSE index history. This is a retrieval adapter, **not a synthetic or category proxy**. If those routes do not provide a decision-grade series, the resolver may use an explicitly matched ETF/NAV series for the same exposure. Generic Yahoo index symbols are deliberately not used as canonical sector/thematic proxies.

**Decision gate:** a canonical history needs at least **250 observations** before it is eligible for the Mansfield 52-week and 12-month decision calculations. Histories below that threshold are excluded from decision signals rather than padded or substituted.

**ETF market prices:** configured NSE trading symbols are used as the canonical ETF identifiers. Yahoo Finance `.NS` symbols are adapters, not authoritative ticker definitions. Legacy NSE ticker changes are retained as aliases where verified.

**ETF NAV fallback:** AMFI historical NAV data can recover explicitly mapped ETF/fund histories when market-price retrieval is unavailable. ETF/NAV data may be promoted to canonical decision input only when the mapping is explicitly exposure-matched; nearest-category substitution is prohibited.

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
