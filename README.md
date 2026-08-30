# India Sector Rotation

Exposure-first quantitative sector and thematic rotation research for Indian equities. The
repository separates the canonical **Exposure** (sector/theme + benchmark) from its ETF
implementations, index ingestion, quantitative calculations, and Streamlit presentation.

Live app: <https://dualmomentum.streamlit.app>

## Architecture

```text
NSE / NiftyIndices  (via jugaad-data adapter)        AMFI / MFAPI / Yahoo
          |                                                   |
          v                                                   v
Universe Registry -> Exposure -> canonical Nifty benchmark   ETF price + NAV
          |                                                   |
          +--> explicit ETF/NAV promotion (mapped exposures only)
          |
          v
Quantitative engine
  - 1M / 3M / 6M / 12M relative returns
  - weekly Mansfield Relative Strength
  - cross-sectional Z-scores and percentile ranks
  - RS ratio + RS momentum stage
  - monthly top-N rotation backtest
          |
          v
Prepared Parquet + metadata.json
          |
          v
Streamlit UI (read-only)
```

## Application map

| Page | Question it answers |
| --- | --- |
| **Dashboard** | What does the model say to do today, and how much of the universe is leading? |
| **Sectors** | Which sectors lead, which are rolling over, and what do their returns look like across horizons? |
| **Themes** | The same, for thematic exposures. |
| **Screener** | Filter and sort the whole universe on any column and any lookback. |
| **Backtest** | Would following this ranking have beaten Nifty 50 over the last 1–5 years? |
| **Exposure** | For one exposure: the decision, the relative-strength path, and the funds that implement it. |
| **Data Health** | Where every series came from, what it actually is, and what is missing. |

Every page is read-only. The app performs no downloads at page load; it reads prepared files
from `data/processed/`.

## Data hierarchy

**Canonical index benchmarks.** Every canonical history is NSE / NiftyIndices data retrieved
through the [`jugaad-data`](https://pypi.org/project/jugaad-data/) adapter. jugaad-data is a
*retrieval client*, not a data authority — it returns whichever series NSE serves.

The adapter asks for the total-return series first and falls back to the price index. Which one
was actually served is recorded per exposure in
`metadata.json → value_type_by_canonical_exposure` and shown in the **Value** column on the Data
Health page:

- `TRI` — total return index, dividends reinvested.
- `CLOSE` — price index, no dividend component.
- `NAV` — an explicitly mapped ETF/fund NAV standing in for an index NSE cannot serve.

Nothing is described as a total-return series unless NSE served one. The Nifty 50 benchmark is
fetched from the same adapter, so both sides of every relative number share one calendar and one
dividend treatment. Comparing a TRI exposure against a price-index benchmark would overstate
relative strength by roughly the benchmark's dividend yield.

**ETF market prices.** Configured NSE trading symbols are the canonical ETF identifiers. Yahoo
Finance `.NS` symbols are adapters, not authoritative ticker definitions. Yahoo is never used
for a canonical index history.

**ETF NAV fallback.** AMFI's historical NAV endpoint backfills bounded date ranges so illiquid
or unsupported Yahoo series can be recovered without fabricating prices.

## Decision-grade principles

1. **No synthetic benchmark proxies.** A benchmark must represent the declared exposure.
2. **Source lineage is explicit.** Retrieval mechanism and financial instrument are not
   conflated. `niftyindices_jugaad` identifies a retrieval route; it is not synthetic data, not
   an ETF proxy, and not a separately calculated TRI series.
3. **250 observations is the decision boundary.** A history needs at least 250 observations to
   enter the decision-grade Mansfield 52-week and 12-month calculations. Nothing is padded,
   extrapolated, or NaN-filled to satisfy it.
4. **Exposure comes before ETF.** ETF liquidity, tracking characteristics, or ticker mechanics
   must not redefine sector strength.
5. **Catalogue membership is not universe membership.** NSE publishes many ESG, Shariah,
   corporate-group, factor, size, liquidity and strategy indices that are not automatically
   sector-rotation exposures. Overlapping variants — an equal-weight alternative, a closely
   related infrastructure/mobility cut — are not independent economic sectors.

Nearest-category substitution, broad-market substitution and synthetic benchmark construction
are prohibited.

## Daily production refresh

`.github/workflows/data_pipeline.yml` runs every day at **04:00 IST** (`22:30 UTC` the previous
calendar day), plus on main updates and manually. It runs the live pipeline and commits changed
`data/processed/` artifacts back to `main`. The pipeline uses the latest available market
observation, so weekends and NSE holidays naturally reuse the most recent working-day
observation. The workflow is concurrency-protected, and the `paths-ignore` rule prevents a
generated-data commit from recursively launching another run. Generated data is the only
automatic output; source changes are reviewed separately.

## Domain model

`Exposure` is the primary object. Each exposure contains a canonical sector/thematic category, a
canonical Nifty benchmark, an optional Yahoo symbol, zero or more ETF implementations with
verified NSE symbols and optional aliases, and optional AUM, expense-ratio, liquidity and
tracking-error metadata. This prevents an ETF-specific liquidity or tracking characteristic from
being read as sector strength.

## Quantitative definitions

### Relative return

For lookback `L`: `R_L = P_t / P_{t-L} - 1`, and relative momentum against Nifty 50 is
`DM_L = R_exposure,L - R_benchmark,L`.

Rankings default to the **relative** measure. In a rising market almost everything is up, so
ranking on absolute return largely re-ranks the market itself; `vs Nifty 50` is what the model
is actually about. Absolute stays one click away because it is what a holder earns.

### Mansfield Relative Strength

`RS_t = P_exposure,t / P_benchmark,t`, resampled to Friday observations, then
`MRS_t = 100 * (RS_t / SMA(RS_t, 52) - 1)`. RS momentum is the 13-week change in MRS.

Note that `rs_ratio = 1 + MRS/100` by construction, so `rs_matrix.parquet` carries the full
history of both RRG axes even though the summary stores only their latest values.

### Stage

- **Leading:** RS ratio >= 1 and momentum >= 0
- **Weakening:** RS ratio >= 1 and momentum < 0
- **Lagging:** RS ratio < 1 and momentum < 0
- **Improving:** RS ratio < 1 and momentum >= 0

### Decision boundary

| Action | Condition |
| --- | --- |
| `BUY` | Leading + RS ratio > 1 + RS velocity > 0 + momentum Z > 0 |
| `REDUCE / EXIT` | Weakening or Lagging + RS ratio < 1 + RS velocity < 0 |
| `WATCH / IMPROVING` | Improving stage with RS velocity > 0 — below the benchmark, no longer falling behind |
| `WATCH` | Decision-grade, but no full confirmation either way |
| `DATA UNAVAILABLE` | Proxy history, or a missing RS/momentum input |

Rank is a strength ordering. It is never a BUY or SELL gate.

`WATCH` additionally carries a presentation-only `watch_kind` (`Rolling over`, `Holding`,
`Early turn`) so a rank-1 leader whose velocity has turned negative does not look identical to a
flat neutral name. It does not change any action.

Two exposures may not resolve to the same underlying index. `validate_universe` rejects it, and
the pipeline fails closed, because one index behind two exposures occupies two ranks while
representing a single bet. `NBFC` and `Financial Services ex Bank` both pointed at
`NIFTY FINANCIAL SERVICES EX-BANK`; NSE publishes no NBFC index, so the former was remapped to
`NIFTY MIDSMALL FINANCIAL SERVICES` and renamed **Mid & Small Financials** to describe what that
index actually is. The UI still carries a `shares_index_with` flag as a backstop for any dataset
generated before the rule existed.

### Tradeability

An exposure with a BUY and no instrument is research, not a position. The dashboard says so:
signals with no listed ETF carry a `no ETF` badge, and a **Tradeable only** filter on the
Dashboard and Screener keeps just the ones you can act on.

Two vehicle types are tracked separately, because they are bought differently. An **ETF** trades
on exchange at a price that can sit above or below NAV. An **open-ended index fund** transacts
at NAV with no spread and no premium — often the better vehicle for a monthly rebalance, at the
cost of intraday execution. `vehicle` is `etf` or `index_fund`; an index fund carries an AMFI
scheme code and no ticker.

Mappings are built from two authoritative sources and nothing else. NSE's listed-ETF feed
supplies the trading symbol and the index each symbol tracks; AMFI's scheme master supplies the
fund name and scheme code. A fund is only mapped when, after stripping the AMC name, its index
tokens match the exposure's benchmark **exactly** — a subset match is how `Groww BSE Power ETF`
becomes Nifty Power, or `ICICI Nifty Financial Services Ex-Bank ETF` becomes Nifty Services
Sector. Anything without an authoritative fund name is left unmapped rather than given an
invented one. Fund-of-funds and IDCW plan variants are excluded; for an index fund the Direct
Plan Growth option is the one mapped.

Each pipeline run also takes a point-in-time NSE snapshot per symbol: turnover, last price, NAV
and the resulting premium or discount. AUM, expense ratio and tracking error are not published
on any endpoint this project reads and stay null. Turnover and premium are the two that most
often decide whether a signal is actionable — a thin sector ETF at a 2% premium hands back a
chunk of the index's edge on entry.

### Choosing a new exposure

NSE publishes 139 live indices; the rotation universe is 47. A candidate must clear three bars:

1. It is a sector or theme, not a factor, ESG, Shariah, corporate-group, size, liquidity or
   strategy construction.
2. It has at least 250 observations of authoritative history.
3. Its **daily-return correlation with every existing exposure is below 0.90**. This is the test
   that keeps the universe from filling with variants. `NIFTY TRANSPORTATION & LOGISTICS`
   (0.990 against Mobility), `NIFTY500 HEALTHCARE` (0.979 against Healthcare) and
   `NIFTY NON-CYCLICAL CONSUMER` (0.962 against Consumption) were all rejected on this bar.

## Backtest

`src/quantitative/backtest.py` runs a monthly rotation test against Nifty 50.

- On the last trading day of each month the universe is ranked by composite momentum Z-score
  using **only prices up to that day**, by calling the same `rank_exposures` the live dashboard
  uses. There is no separate research implementation to drift out of sync.
- The top *N* exposures (default 2) are held equally weighted until the next month end. A
  month's return is therefore earned entirely after the decision that selected it.
- An exposure is only selectable when every lookback it is scored on is fully populated at that
  date, so a newly launched index is never ranked on 1-month momentum against names scored on
  four horizons.
- With the absolute-momentum filter on (classic dual momentum), an exposure whose own trailing
  12-month return is negative is skipped and that slot earns 0% in cash. No T-bill yield is
  assumed, which understates the filtered variant rather than flattering it.
- Minimum window is 12 months; 24, 36 and 60 are also selectable.

**Limits, stated plainly.** These are index levels, not fund returns — no brokerage, spread,
STT, expense ratio, tracking error or tax is deducted, and an index cannot be bought directly.
The eligible universe grows over time as newer indices reach a full 12-month history. Index
reconstitution is embedded in the published series. A 12-month sample cannot distinguish skill
from luck; treat it as a sanity check on the signal, not as evidence of an edge.

## Prepared data contract

`data/processed/` holds the only files the app reads:

| File | Contents |
| --- | --- |
| `summary_rankings.parquet` | One row per exposure: stage, RS ratio/momentum, momentum Z, rank, returns, `data_source`, `value_type` |
| `rs_matrix.parquet` | Weekly Mansfield RS per exposure |
| `index_prices.parquet` | Daily canonical index levels per exposure plus the Nifty 50 benchmark in `__benchmark__` — required by the Backtest page |
| `etf_universe.parquet` | ETF metadata per exposure |
| `etf_prices.parquet` | Daily ETF price/NAV history |
| `metadata.json` | Coverage, provenance, value types, validation warnings, quality alerts |

If `index_prices.parquet` is absent the Backtest page explains what is missing and the rest of
the app is unaffected.

## Data health telemetry

`metadata.json` records the UTC update timestamp, canonical coverage, per-exposure source and
value type, resolved index names, ETF coverage and skipped symbols, and validation warnings.

Each run compares itself against the previous published `metadata.json` before overwriting it
and records `quality_alerts`: coverage regressions, dropped series, truncated histories, stale
data, and flatlined series. A run that is internally consistent can still be worse than the one
it replaces — ETF coverage moved 31 → 29 between two production runs and nothing said so. Pass
`--strict` to exit non-zero on any error-level alert; the Data Health page shows them either
way.

`source_counts` is derived from the sources that actually resolved. It previously used a
hard-coded key list that omitted the adapter serving every exposure, so Data Health reported
zero canonical sources while 43 were present.

ETF coverage moves run to run as Yahoo and MFAPI availability changes; INFRABEES, previously the
standing gap, now resolves via MFAPI. Any shortfall here is an ingestion gap in the
implementation layer only — the canonical index history behind every decision is unaffected, and
no signal depends on it. The Data Health page lists whatever is currently skipped.

## Local setup

Python 3.12 is recommended.

```bash
git clone https://github.com/Pareshking/Sector-Rotation.git
cd Sector-Rotation
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

## Pipeline

```bash
python -m pipeline.run_pipeline --mode fixture   # deterministic offline dataset
python -m pipeline.run_pipeline --mode live      # real ingestion
pytest -q
```

Live mode fails closed if canonical coverage is below 100%; it does not silently publish an
incomplete canonical universe. A five-year window is requested where the source has sufficient
history — "100% coverage" means every configured canonical index has a valid authoritative
series, not that a newly launched index is backfilled before its inception date.

Index and ETF ingestion fail independently. To refresh index history alone, reusing the ETF
artifacts already in `data/processed/` rather than overwriting them with a degraded fetch:

```bash
python -m pipeline.run_pipeline --mode live --skip-etf
```

`metadata.json` records which path ran as `etf_ingestion: refreshed | reused`.

## Verification

A successful process exit is not a validation. After a live run, inspect the generated Parquet
files and `metadata.json` directly: observation counts, date ranges, source lineage, value
types, missing or short histories, and decision-grade eligibility.

## Streamlit Community Cloud

Entry point `app/streamlit_app.py`, dependencies from the root `requirements.txt`. No API
secrets are required and no bulk history is downloaded at page load.

## Data limitations

1. ETF traded-price history is not identical to ETF NAV history.
2. A newly launched ETF cannot legitimately provide five years of traded history.
3. Newly launched Nifty indices may have shorter authoritative histories.
4. Missing AUM, expense ratio, liquidity and tracking-error values remain null rather than
   invented.
5. Survivorship and index-reconstitution effects must be considered before using historical
   rankings for backtests.

## Development principles

- No live downloads from Streamlit pages.
- No ETF treated as the canonical sector/theme unless explicitly mapped.
- No fabricated historical observations.
- Missing data is explicit and testable.
- A series is never labelled total-return unless the source served one.
- Quantitative calculations remain independent of the UI, and the backtest reuses the live
  ranking code rather than reimplementing it.
- Production datasets are generated by the pipeline and stored as compressed Parquet.
