# India Sector Rotation

Exposure-first quantitative sector and thematic rotation research for Indian equities. The
repository separates the canonical **Exposure** (sector/theme + benchmark) from its ETF
implementations, index ingestion, quantitative calculations, and Streamlit presentation.

Live app: <https://dualmomentum.streamlit.app>

## Architecture

```text
NSE / NiftyIndices (jugaad-data) + BSE Index Services   NSE / MFAPI / AMFI / Yahoo
          |                                                   |
          v                                                   v
Universe Registry -> Exposure -> canonical Nifty benchmark   ETF price + NAV
          |                                                   |
          +--> explicit ETF/NAV promotion (mapped exposures only)
          |
          v
data/raw/{index,vehicle}/{id}/{yyyy}.parquet   append-only archive, extended incrementally
          |
          v
Prepared Parquet + metadata.json  (each file checked against src/data/contracts.py)
          |
          v
src/config/strategy.json  (strategy v1.1: N, buffer M, score, cash hurdle, fill, cost)
          |
          v
src/portfolio  — pure, no I/O, no Streamlit
  - score.py      non-overlapping segment composite (1M, 3M-1M, 6M-3M, 12M-6M)
  - universe.py   point-in-time investability from vehicle price history
  - construct.py  construct_target_portfolio + decision_chain
          |
          +--> live.py          current target  -> Streamlit dashboard, tools/detect_alerts.py
          +--> backtest.py      same chain + t+1 fills, costs, cash accrual
          |
Display only: Mansfield RS, RRG stage, durability analytics (src/quantitative)
```

## Application map

The look is the owner's other app, Paresh (<https://paresh.streamlit.app>): its own UI code is
ported into `app/kit/` (stylesheet, header, page kit, sortable tables, TradingView Lightweight
Charts and Highcharts, vendored in `app/kit/vendor`). Light theme only. Missing values show "—".

| Page | Question it answers |
| --- | --- |
| **Screener** (home) | Where does every sector and theme stand on the strategy's score today? Paresh's screener table: rank, 1M Δ / 3M Δ rank change, classification (sector/theme, index, fund count), 1M–12M returns, 12M vs cash, score, portfolio status, quadrant (display only), 12-month path. Opens on **tradeable** exposures; search, preset pills, filters, export; risers and fallers. |
| **Portfolio** | The ₹20 lakh **model book** (`src/portfolio/book.py`): the live rules' decision chain bought and held in the chosen funds at NAV, from Nov 2022 (every month backfilled; the running month MTD). Readings, current book, sector exposure and correlation, equity & drawdown, calendar returns, trades, rebalances, export. |
| **Actions** | What the next rebalance would do if prices hold: Sell / Buy / Hold with cushions (room inside the retention buffer, 12M return above the cash hurdle), "My holdings" mode, a Kite basket CSV. Computed with the strategy's own `construct_target_portfolio`. |
| **Exposure** | One exposure: decision, index level and drawdown, RS line vs Nifty 50, volatility, durability, every fund (ETF vs index fund) and position sizing. `?exposure=<id>` opens one directly. |
| **Evidence** | Would the live rules have beaten Nifty 50 TRI after costs, and is that evidence? Net CAGR, total return, excess, drawdown, **Deflated Sharpe**; with/without back-calculated history; rolling 12-month windows; early vs recent; the parameter grid in a collapsed "Parameter Sensitivity (Unvalidated)" expander. |
| **Data Health** | Where every series came from and what it is (TRI or price index), what is missing, launch dates and back-calculated history, the liquid fund, the NSE ETF snapshot status. |
| **Method** | The theory: score, portfolio rule, worked example reproducing the live score, rotation (display only), backtest, data sources. |

Every page is read-only. The app performs no downloads at page load; it reads prepared files
from `data/processed/` and builds the target portfolio from them with `src/portfolio`, the same
code the backtest runs.

**Model book vs backtest.** The backtest accounts in index returns; the model book buys the
funds. Over Nov 2022 – Oct 2026 the book made about +135% against +169% in index terms, mostly
because the only PSE fund before mid-2025 was Bharat 22 ETF, which tracks a different index.

## Data hierarchy

**Canonical index benchmarks.** Every canonical Nifty index history is NSE / NiftyIndices data retrieved
through the [`jugaad-data`](https://pypi.org/project/jugaad-data/) adapter. jugaad-data is a
*retrieval client*, not a data authority — it returns whichever series NSE serves.

The adapter asks for the total-return series first and falls back to the price index. Which one
was actually served is recorded per exposure in
`metadata.json → value_type_by_canonical_exposure` and shown in the **Value** column on the Data
Health page:

- `TRI` — total return index, dividends reinvested.
- `CLOSE` — price index, no dividend component.
- `NAV` — an explicitly mapped ETF/fund NAV standing in for an index NSE cannot serve.

**BSE indices.** An exposure marked `"index_provider": "bse"` in `universe.json` (BSE Insurance,
BSE Hospitals) is fetched from **BSE Index Services** (`bseindices.com`, BSE's own index arm) by
its numeric id and BSE index code (`src/data/bse_indices.py`), and must pass the same
completeness check against the Nifty 50 calendar. BSE publishes only the *price* index without
registration, so these series are `CLOSE`, never `TRI`: against the Nifty 50 TRI benchmark their
relative strength is understated by roughly their dividend yield (BSE reports 0.38% for
Insurance and 0.18% for Hospitals as of Sep 2026).

Nothing is described as a total-return series unless NSE served one. The Nifty 50 benchmark is
fetched from the same adapter, so both sides of every relative number share one calendar and one
dividend treatment. Comparing a TRI exposure against a price-index benchmark would overstate
relative strength by roughly the benchmark's dividend yield.

**ETF and fund histories.** Configured NSE trading symbols are the canonical ETF identifiers.
Each vehicle is resolved in a fixed order, and the first source that answers wins
(`src/data/etf_data.py`):

1. **NSE** traded history, for anything with a trading symbol.
2. **MFAPI** scheme NAV, for anything with an AMFI scheme code that NSE did not serve.
3. **AMFI**'s historical NAV endpoint, in one shared download for whatever is left.
4. **Yahoo Finance**, last, only for instruments no authoritative source could serve.

Yahoo `.NS` symbols are adapters, not authoritative ticker definitions, and Yahoo is never used
for a canonical index history. The source that served each vehicle is recorded in
`metadata.json → etf_source_by_symbol`.

**Authoritative dates.** `data/universe/universe.json` records, for every index, its NSE
`launch_date` and `base_date` (from the index's NSE Indices factsheet) and, for every ETF and
index fund, its `inception_date` (its first published NAV in AMFI's record, via MFAPI), each
with its source (a BSE index's dates come from BSE Index Services' index description, its
"Launch Date" and "First Value Date", and are recorded by hand). `tools/refresh_universe_dates.py`
fills the rest; it is run by hand and its diff
reviewed like code. A date the source does not state is left empty and reported, never guessed:
NSE's factsheets for Nifty IT, MNC, PSE and Services give no launch date, and SBI Nifty IT ETF
has no NAV history in AMFI's record.

**Cash.** The cash return is the NAV of the liquid fund named in `strategy.json → cash_proxy`
(Nippon India Liquid Fund – Direct Plan – Growth Option, AMFI scheme 118701), ingested with the
other histories into `cash_nav.parquet`. Ingestion refuses the series unless AMFI's scheme name
matches the configured name exactly, so a wrong scheme code cannot become the cash return.

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

`.github/workflows/data_pipeline.yml` runs on a schedule only: every day at **04:00 IST**
(`22:30 UTC` the previous calendar day), with a retry at **08:30 IST** (`03:00 UTC`) because NSE,
MFAPI and AMFI are occasionally unreachable from GitHub's runners at the primary hour. If the
primary run succeeded, the retry finds no data changes and commits nothing. It can also be run
manually (`workflow_dispatch`), which is how to refresh after a pipeline change. It does not run
on pushes: a full run takes about 18 minutes for data that changes once a day, and a quick
sequence of pushes used to cancel its own refresh.

It runs the live pipeline with `--strict`, so an error-level quality alert stops the run before
anything is committed, and commits changed `data/processed/` artifacts and the `data/raw/`
archive back to `main`. The
pipeline uses the latest available market observation, so weekends and NSE holidays naturally
reuse the most recent working-day observation. The workflow is concurrency-protected (a new run
cancels one in progress). Because there is no push trigger, a generated-data commit cannot launch
another run. Generated data is the only automatic output; source changes are reviewed separately.

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

### Stage (display only)

- **Leading:** RS ratio >= 1 and momentum >= 0
- **Weakening:** RS ratio >= 1 and momentum < 0
- **Lagging:** RS ratio < 1 and momentum < 0
- **Improving:** RS ratio < 1 and momentum >= 0

The stage describes where an exposure's RS line sits against its own 52-week average. Since
strategy v1.0 it decides nothing; it is shown for context.

### Strategy score (v1.0)

Every exposure with a full 12-month history is scored at the rebalance close on four
**non-overlapping** segments of its log return, in sessions back from that close:

| Segment | Sessions | Weight |
| --- | --- | --- |
| `1M` | 0–21 | 25% |
| `3M-1M` | 21–63 | 25% |
| `6M-3M` | 63–126 | 25% |
| `12M-6M` | 126–252 | 25% |

Each segment is z-scored across the universe on that date, and the score is the weighted sum.
Lookbacks are positions on one shared session calendar, so every exposure is measured over the
same sessions. The segments tile the year exactly once; the overlapping 1M/3M/6M/12M composite
this replaced weighted the latest month about 7.9× the oldest six through overlap alone.

**The latest month is never skipped.** In single stocks one-month returns reverse (Jegadeesh
1990), which is why stock momentum uses 12-1. Industry portfolios behave differently
(Moskowitz & Grinblatt 1999): their one-month momentum continues, and in this universe the
one-month segment predicts positively. A 12-1 lookback is deliberately not used.

An alternative score, `vol_adjusted_12m` (12-month log return over 126-session EWMA volatility),
is implemented and selectable in `strategy.json`. v1.0 does not use it.

### Portfolio rule (v1.0)

`construct_target_portfolio` in `src/portfolio/construct.py` is the only place a holding is
decided. The dashboard, the alert tool and every rebalance of the backtest call it:

1. **Eligible** — scorable and, with `require_investable`, buyable on the date: a mapped ETF or
   index fund had incepted by it, by its recorded `inception_date`. Buyability is never inferred
   from the nightly price download, so a fetch that fails one night cannot make a fund that
   launched years ago unbuyable and sell it. Eligible exposures are ranked by score.
2. **Retention buffer** — a holding is kept while its rank is ≤ `retention_buffer_m` (4).
3. **Entry** — a vacant slot is filled only from ranks ≤ `target_holdings_n` (2), best first.
4. **Cash hurdle** (`dual_momentum_cash_hurdle`) — an exposure is held only while its own
   12-month return beats what the liquid fund returned over the same 12 months (the constant 6.5%
   only before the fund's NAV history). A top-ranked name that fails leaves its slot in cash; it is
   never handed to a weaker name.
5. **Weights** — each slot is 1/N of the book; unfilled slots are cash.
6. **Back-calculated history** (`backfill_policy`) — before an index's NSE launch date its values
   were computed after the fact. v1.1 keeps them (`include`); `exclude_prelaunch` makes an index
   ineligible before its launch. 24 of the 47 indices launched inside the five-year panel —
   Telecom, Capital Goods, Power, Consumer Services and Sugar & Ethanol only in June 2026 — so the
   Evidence page shows the strategy both ways.

| Action | Meaning |
| --- | --- |
| `BUY` | Enters the target, or its weight rises |
| `HOLD` | Stays at the same weight |
| `TRIM` | Stays, at a lower weight |
| `SELL` | Leaves the target |
| `NOT HELD` | Scored but not in the target; `decision_status` says why |
| `DATA UNAVAILABLE` | No authoritative 12-month history, or a proxy source |

The buffer makes the strategy path-dependent: whether a rank-3 name is held depends on whether it
was held last month. The live target is therefore the end of `decision_chain` over every completed
month in the data — the same chain the backtest replays. `tests/test_live_equals_backtest.py`
asserts the two are identical byte for byte, and that a decision never reads a price after its
own date.

Two exposures may not resolve to the same underlying index. `validate_universe` rejects it, and
the pipeline fails closed, because one index behind two exposures occupies two ranks while
representing a single bet. `NBFC` and `Financial Services ex Bank` both pointed at
`NIFTY FINANCIAL SERVICES EX-BANK`; NSE publishes no NBFC index, so the former was remapped to
`NIFTY MIDSMALL FINANCIAL SERVICES` and renamed **Mid & Small Financials** to describe what that
index actually is. The UI still carries a `shares_index_with` flag as a backstop for any dataset
generated before the rule existed.

### Tradeability

An exposure with no instrument is research, not a position, so the strategy never holds one:
with `require_investable` on, only exposures whose mapped ETF or index fund had incepted by the
decision date (by its recorded `inception_date`) are eligible. Elsewhere in the app, exposures without one carry a `no fund` badge,
and a **Buyable only** filter on the Rankings page keeps just the ones you can act on.

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

`src/quantitative/backtest.py` has no selection rules of its own. It calls `decision_chain` at
every month-end close — the same chain as the dashboard — and does the accounting:

- **Signal at t, fill at t+1.** A decision formed at the month-end close executes at the next
  session's close (`execution_fill: t_plus_1_close`). The old portfolio earns the session in
  between; each period runs from one fill to the next.
- **Costs are charged.** `cost_bps_per_side` (25) on every unit of weight bought or sold, cash
  legs excluded: `cost = bps × Σ|w − w_prior|`, deducted at the fill. The Evidence page reports
  gross, costs and net.
- **Cash earns what the liquid fund earned** between the two fills — the same NAV series as the
  hurdle. The constant (`risk_free_rate_annual`, 6.5%) is used only for periods that start before
  the fund's NAV history; Sharpe still uses the constant.
- **Only completed months count.** The current, unfinished month is not a rebalance date, and
  CAGR is annualised by the trading sessions actually covered.
- **Turnover** is `0.5 × Σ|wₜ − wₜ₋₁|` over every holding and cash. The book starts in cash.
- **Sharpe** is `(CAGR − rf) / annualised volatility`, the same definition as the exposure
  analytics.

**Two universes.** *Strategy (buyable)* is the portfolio the dashboard shows: a pick must have had
a fund with a price on that date, judged from the vehicle's own history rather than today's
lineup. *All indices* applies the same rules to every index whether or not a fund existed; it
measures the signal, not a portfolio anyone could have held.

**Rolling windows and the early/recent split** are on the Evidence page. A single headline number
depends on when the test started; the distribution of every 12-month window does not.

**No figures are quoted here.** Earlier versions of this README carried hand-typed backtest
numbers that went stale with every nightly refresh and every rule change. The Evidence page
computes them from the current data and the current `strategy.json`.

**What-if settings are not the strategy.** The Evidence page's "Parameter Sensitivity
(Unvalidated)" expander reaches 768 strategy configurations (N × buffer × holding period × hurdle ×
back-calculated history × score specification) across 96 evaluation settings (universe × window ×
exposures × cost). Picking the best-looking one is fitting this sample.

**Deflated Sharpe ratio.** The headline is deflated for those 768 trials (Bailey & López de Prado
2014): the probability that the true monthly Sharpe ratio is above zero after allowing for the best
result that many zero-edge configurations would produce by luck. The variance of Sharpe estimates
across trials is not observed, so it is set to `1 / (T − 1)`, the sampling variance of a Sharpe
ratio under no edge. Below 95% is not evidence of an edge; on the current five years it is well
below.

**Limits, stated plainly.** The rules were specified after studying these same four years, so the
backtest is point-in-time but not out-of-sample. 25 bps per side covers brokerage and spread only
roughly; tax, ETF premium to NAV and impact on thin funds are not modelled. These are index
levels, and an index cannot be bought directly; a fund lags by its tracking difference. Index
reconstitution is embedded in the published series, and funds that launched and later closed are
absent. Several thematic indices were launched with back-calculated history, and the universe was
chosen in 2026. Treat the record as a check on the rules, not as evidence of an edge.

## Prepared data contract

`data/processed/` holds the only files the app reads:

| File | Contents |
| --- | --- |
| `summary_rankings.parquet` | One row per exposure: stage, RS ratio/momentum, returns, `data_source`, `value_type`, and `momentum_z` / `rank` — the strategy score and its rank across the universe as of the latest session |
| `rs_matrix.parquet` | Weekly Mansfield RS per exposure |
| `index_prices.parquet` | Daily canonical index levels per exposure plus the Nifty 50 benchmark in `__benchmark__` — required by the Evidence page |
| `etf_universe.parquet` | ETF metadata per exposure |
| `etf_prices.parquet` | Daily ETF price/NAV history |
| `cash_nav.parquet` | Daily NAV of the cash proxy (the liquid fund) |
| `portfolio_target.parquet` | The latest decision: one row per order (BUY / HOLD / TRIM / SELL) plus a `CASH` row; weights sum to 1 |
| `metadata.json` | Coverage, provenance, value types (including `benchmark_value_type`), ingestion report, restatements, fetch errors, validation warnings, quality alerts, the cash proxy, the target portfolio summary, and the `strategy` config with its `strategy_version` and `strategy_hash` |

**Every file has a contract** (`src/data/contracts.py`): required columns, types, ranges, a
sorted unique date index, the benchmark complete, target weights summing to 1, a timezone-aware
timestamp. The pipeline checks all of them before writing anything and stops, listing every
breach, if one fails — a malformed dataset is never published.

`portfolio_target.parquet` is a published record, not an input: the app and the alert tool
rebuild the target from the price files with `src/portfolio`, so it can never disagree with the
code that tested it.

## Raw archive

`data/raw/` is an append-only store, one Parquet file per series per calendar year:
`data/raw/index/{exposure_id}/{yyyy}.parquet` for NSE index levels (the benchmark is
`nifty-50`), `data/raw/vehicle/{scheme_code}/{yyyy}.parquet` for funds and the cash proxy. Rows
carry the value, its type (TRI / CLOSE / NAV), its source and when it was fetched.

- **Incremental.** An index series is fetched only from 10 stored sessions before its last
  stored session (`--overlap`). An empty store is seeded once with `--seed-years` (5) of
  history; after that the archive only grows — nothing falls off the start.
- **Restatements are kept, not overwritten.** The overlap is re-fetched on purpose. A value that
  changed is appended as a new version with a later `fetched_at`; reads use the latest. Each one
  is listed in `metadata.json → restatements` and raised as a warning in `quality_alerts`.
- **No splicing.** A series stored as TRI is only ever extended with TRI. A fetch whose overlap
  mostly disagrees by more than 2% is a different series and is refused.
- **Failures fall back to the store.** A series whose fetch fails keeps its stored history and
  is reported in `metadata.json → ingest`. Fund histories are merged on every run (MFAPI returns a
  fund's whole history in one request), so a fund that fails one night keeps its history too.

If `index_prices.parquet` is absent the Evidence page explains what is missing and the rest of
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

**Freshness is checked outside the pipeline.** A GitHub Actions timeout reports as "cancelled",
which looks identical to a run superseded by concurrency, so two nights of failed publishing
once passed unnoticed. The pipeline cannot catch this itself: if it does not run, nothing checks,
and a run that does finish stamps `last_updated_utc` with the current time just before checking
it. `.github/workflows/data_freshness_watchdog.yml` therefore runs every 6 hours on its own
schedule, and `tools/check_freshness.py` (stdlib only, so it still works if the pipeline's
dependencies break) fails when the committed dataset is **more than 36 hours old**. A failure
opens one `data-quality` issue per stale episode, not one every 6 hours. Checking the symptom —
how old the data is — catches the failure regardless of the cause.

`source_counts` is derived from the sources that actually resolved. It previously used a
hard-coded key list that omitted the adapter serving every exposure, so Data Health reported
zero canonical sources while 43 were present.

ETF coverage moves run to run as Yahoo and MFAPI availability changes; INFRABEES, previously the
standing gap, now resolves via MFAPI. The Data Health page lists whatever is currently skipped.

Fund price gaps do not affect decisions: buyability comes from recorded inception dates. The
nightly prices are used only as evidence against those dates — a vehicle whose prices start more
than 10 days before its recorded inception raises an `inception_conflict` warning, because the
date then needs a reviewed correction.

## Alerts

A rotation model only asks for action when its target changes, and the v1.0 target only changes
at a month-end rebalance. After each pipeline run `tools/detect_alerts.py` builds the target
portfolio from tonight's data and from the last committed data — with `src/portfolio`, the same
code as the dashboard — and reports the orders between them: buys, sells and resizes, with
weights, ranks and reasons. The workflow opens a GitHub issue when anything changed, which reaches
watchers by email and on mobile without needing any additional secret. Between rebalances both
nights produce the same decision and nothing is raised. The tool imports nothing from the
Streamlit app.

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
python -m pipeline.run_pipeline --mode live      # real ingestion into data/raw, then data/processed
python tools/refresh_universe_dates.py           # refresh launch/base/inception dates; review the diff
pip install -r requirements-dev.txt              # pytest and ruff, not needed by the app
pytest -q
```

Live mode does not require 100% canonical coverage, and it never fills a gap with a synthetic
or nearest-category proxy. An exposure without at least 250 authoritative observations is listed
in `metadata.json → skipped_canonical_exposures`, shown on the Data Health page, and is not
decision-grade. What stops a run is a missing Nifty 50 benchmark, an invalid universe, or, under
`--strict`, an error-level quality alert such as canonical coverage falling below the previous
run's, or any artifact failing its contract. A series the archive has never seen is seeded with
five years of history where the source has it; from then on the archive only grows — "100%
coverage" means every configured canonical index has a valid authoritative series, not that a
newly launched index is backfilled before its inception date.

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
