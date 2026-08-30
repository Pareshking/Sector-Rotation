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
| **Method** | The complete theory in one page: ranking, stages, decision rule, backtest, provenance. |

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

### Analytics

Point-to-point returns depend entirely on two dates. Every judgement the app makes about
durability is either distributional or risk-adjusted, computed in
`src/quantitative/analytics.py` from our own series:

| Metric | What it answers |
| --- | --- |
| Rolling CAGR — current / median / min / max / % positive | Has this held up, or is the headline one lucky window? |
| Outperformance consistency, split up-market vs down-market | Real sector strength, or leveraged beta? A sector that only wins when the market rises is the market. |
| Alpha, Beta, R² vs Nifty 50 | Does the excess return survive its beta? |
| Sharpe, Sortino, annualised volatility (1Y/3Y/5Y) | Return per unit of risk, and of *downside* risk |
| Max drawdown with peak, trough, duration, distance from high | What holding it actually felt like |
| Tracking difference and tracking error per vehicle | Which fund to buy for a given index |

A **Z-score is standardised to a mean of exactly zero**, so roughly half the universe sits below
the line by construction. A negative momentum Z means *below the universe average*, not a loss —
Banking currently sits at −0.32 with a +7.7% three-month return. Charts and axes say so
explicitly, because a bar pointing left reads as a loss otherwise.

Every table in the app draws its labels and number formats from one registry
(`app/components/tables.COLUMNS`), including the raw audit dumps, so a column reads the same
everywhere instead of falling back to `return_3M` and bare decimals.

Sharpe and Sortino assume a **6.5%** risk-free rate. That is an assumption, not data, and is
stated wherever the ratios appear.

**Tracking difference is the one that decides an implementation.** It is the annualised return a
vehicle gave up against its own index — expense ratio plus everything else, which is what the
holder actually lost. Tracking *error* only says how erratically it was given up: a fund can
have a low error and still bleed a steady 80bps. Splits are repaired before any of this is
computed; an unadjusted 10:1 unit change otherwise reads as a -40%/yr tracking difference.

### Position sizing

Turnover in rupees is the wrong lens for a retail book. The Exposure page converts it into
**days to build a position** at a 10% participation cap, against a book size you set (default
₹30 lakh). At that size most sector ETFs clear in a single day, so liquidity is rarely the
binding constraint — tracking difference and premium to NAV are. Where a vehicle *is* thin, the
page says how many days it would take and points at the index-fund route, which transacts at NAV
regardless of volume.

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

**Rolling windows.** A single headline number depends entirely on when the test started and
stopped. Every overlapping 12-month window inside the record is compounded separately, and the
distribution is the honest answer — the same treatment the Durability panel gives an exposure,
applied to the strategy itself. Over 37 windows:

| | Beat Nifty 50 | Median excess | Worst window |
| --- | --- | --- | --- |
| All indices | 100% | +34.4% | +3.0% |
| Buyable + entry rule | **35%** | **−4.7%** | −20.1% |

How often it worked matters more than how much it made in the one window that happens to end
today.

**Universe modes.** The backtest can run three ways, each stricter than the last:

| Mode | What it measures | 60-month excess |
| --- | --- | --- |
| **All indices** | The signal — does momentum pick strong sectors? | **+237.3%** |
| **Buyable only** | The portfolio — could you have owned it? | +26.2% |
| **Buyable + entry rule** | What the app would have told you to do | **+1.1%** |

Full universe ranks all 47 indices including ones with no buyable vehicle: it measures the
*signal*, not a portfolio anyone could have held. Investable restricts each pick to exposures
that had a fund you could actually have bought **on that date**, judged from the vehicle's own
price history rather than the fact that it exists today — most of these ETFs and index funds
launched in 2024–25, so treating them as available in 2021 would be look-ahead of the worst
kind. Adding the BUY gate also demands the live entry rule. Where the top-ranked name fails a
test the next is taken, down to a configurable rank (default 3); past that the slot goes to cash.

Nearly all the apparent edge is in the gap between those rows. Read the last one.

The universe can also be restricted to **sectors** or **themes** alone. They rotate on different
cycles, and the combined universe is not the average of the two — over 60 months sectors alone
returned −21.0% excess and themes −4.1%, against +1.1% for both together. Breadth itself helps.

**Holding period** is selectable (1, 2, 3 or 6 months) and is separate from the history window.

**Early versus recent.** The blended figure hides which half it came from, and here the halves
disagree completely:

| | Strategy | Nifty 50 | Excess | Periods with cash |
| --- | --- | --- | --- | --- |
| Sep 2022 – Dec 2024 | +19.2% | +36.3% | **−17.1%** | 86% |
| Jan 2025 – Aug 2026 | +20.4% | +4.5% | **+15.9%** | 15% |

Only 12 of 47 exposures had a fund in Aug 2021, against 34 today, so the early stretch mostly
measures a market where sector funds barely existed rather than a failing signal. The recent
stretch is 20 periods — far too few to call an edge. The page shows both.

**Composite weights are configurable** in `data/universe/universe.json → momentum_weights`, and
the pipeline applies them to the board and the backtest identically, so the two can never
disagree about what "rank 1" means. The default is equal weight across 1M/3M/6M/12M: a neutral
prior that assumes nothing about which horizon predicts best, which is the honest default when
the record is this short.

**Do not tune them on this sample.** Running the same 48 months under six reasonable weightings
moves the excess return by roughly 30 percentage points — a swing that comes from the parameter,
not the strategy. Picking the best row is fitting noise. The Backtest page runs that grid on
demand so the fragility is visible rather than hidden.

**The history window is not the return window.** The ranking needs a full 12-month history
before it can pick anything, so a 60-month window yields 48 months of returns; the opening year
is warm-up. The page states both, and every statistic is measured over the months that actually
produced a holding.

**Ranking versus the absolute filter.** The rank is a composite Z across 1M/3M/6M/12M; the
absolute-momentum filter uses 12M alone. That difference is what lets the filter bite — ranking
on *relative* return and filtering on *absolute* over the same window can never disagree, since
both subtract the same benchmark. `test_absolute_filter_rejects_a_composite_winner_with_negative_12m`
pins the case where the composite leader is down over 12 months and is correctly passed over.

**Limits, stated plainly.** Transaction costs are deliberately zero — no brokerage, spread,
STT, expense ratio, tracking error or tax — so a real book earns less, and more so at higher
turnover. These are index levels, and an index cannot be bought directly.
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

A run also fails the check when the **published dataset is more than 36 hours old**. A GitHub
Actions timeout reports as "cancelled", which looks identical to a run superseded by concurrency,
so two nights of failed publishing once passed unnoticed. Checking the symptom — how old the data
is — catches that regardless of the cause.

`source_counts` is derived from the sources that actually resolved. It previously used a
hard-coded key list that omitted the adapter serving every exposure, so Data Health reported
zero canonical sources while 43 were present.

ETF coverage moves run to run as Yahoo and MFAPI availability changes; INFRABEES, previously the
standing gap, now resolves via MFAPI. Any shortfall here is an ingestion gap in the
implementation layer only — the canonical index history behind every decision is unaffected, and
no signal depends on it. The Data Health page lists whatever is currently skipped.

## Alerts

A rotation model only asks for action when something changes, so watching the board daily is the
wrong use of a person. After each pipeline run `tools/detect_alerts.py` compares the new decision
set against the last committed one and reports exposures entering or leaving BUY / REDUCE. The
workflow opens a GitHub issue when anything changed, which reaches watchers by email and on
mobile without needing any additional secret. Drift between two WATCH states is recorded but
never raised — only entering or leaving an actionable state interrupts anyone.

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
