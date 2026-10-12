# Sector-Rotation: 360° audit

Audit date 12 Oct 2026. Data: the committed `data/processed/` (1,245 sessions, 4 Oct 2021 – 9 Oct 2026,
47 exposures, all `TRI`, all `niftyindices_jugaad`). Every number below was measured on that data with
the repo's own functions (`run_backtest`, `rank_exposures`, `signal_panel`, `decision_frame`) unless
stated otherwise. The live site was inspected at `dualmomentum.streamlit.app` on the same date.

**Where the brief's premises are wrong.** The math is *not* tangled into Streamlit callbacks. Ranking,
RS and the backtest live in `src/quantitative/`, and the backtest reuses the live ranking function. The
data is total-return, not unadjusted close. The textbook fixes the brief suggests (skip the last month,
use a 12-1 lookback) are contradicted by this repo's own data (see 2c). The real problems are
different, and worse.

---

## 1. Executive verdict and the five critical failures

**Verdict.** This is a well-instrumented *research* tool sitting on top of a decision layer that is not
the strategy it backtests. The dashboard does not tell you what to hold. The backtest of what it would
have told you loses to Nifty 50 after any realistic cost. And the impressive headline result is mostly
backfill-prone thematic indices that could not have been bought. The data plumbing is better than most
proofs of concept, but it has two silent holes on the benchmark, the one series every number depends on.

### F1. Two different models: the board you see is not the strategy that was tested

| | Live board (`app/components/metrics.py:239`) | Backtest (`src/quantitative/backtest.py:194-238`) |
|---|---|---|
| Selection | Every exposure that is `Leading ∧ momentum_z > 0` | Top N=2 by `momentum_z` |
| Absolute filter | **None** | Own 12M return > 0 (`backtest.py:229-236`) |
| Cadence | Daily data, weekly RS, signal flips any day | Month-end |
| Output | A list of BUY labels | Equal-weight holdings |
| `momentum_z > 0` | Required | **Omitted** in `require_buy` (`backtest.py:225`) |

What this produces today: **12 BUYs**. The header chip says **BEARISH** at the same time: Nifty 50 TRI
is −8.3% over 12M and −6.7% vs its 200-day average (`market_state`, `metrics.py:295-323`, used for display
only). 4 of the 12 BUYs have a *negative* 12-month absolute return, and 6 return less than a 6.5% cash
yield. *Consumer Services* is a BUY at −12.1% absolute and −3.8% vs Nifty over 12M. On the live site,
the top two BUYs (Telecommunications, Media) carry "NO FUND". The page itself reports "6 of 12 BUY signals
have no ETF or index fund."

### F2. The decision rule is a relabelled RRG quadrant, and its labels describe something it does not compute

- **BUY ≡ Leading ∧ z > 0.** `Leading` already means `ratio ≥ 1 ∧ velocity ≥ 0`
  (`relative_strength.py:32`). The extra `ratio > 1 ∧ velocity > 0` at `metrics.py:239` only excludes
  exact equality.
- **REDUCE ≡ Lagging.** `Weakening` has `ratio ≥ 1` by definition, so `Weakening ∧ ratio < 1`
  (`metrics.py:240`) can never be true. Measured: all 6 REDUCE are Lagging. All 23 Weakening are
  WATCH. "Weakening or Lagging" is decorative.
- **"RS ratio above/below the benchmark" is false.** `rs_ratio = RS / SMA₅₂(RS)` (`relative_strength.py:19-22`)
  measures the relative line against *its own 52-week mean*, not against Nifty 50. The wrong reading
  appears in `metrics.py:184` and `:194`, in `1_Overview.py:114-116` and `:154`, and in the README
  decision table. Counter-example in today's data: Consumer Services has `rs_ratio` 1.096 ("above the
  benchmark" per the UI) while it trailed Nifty by 3.8% over 12M.
- **Whipsaw.** There is no noise band and no hysteresis on zero thresholds. Measured on weekly signals:
  a median **2.6 entries into Leading per exposure-year**, median Leading spell **3 weeks**, and **59% of
  spells last ≤ 4 weeks**. A BUY label lasts about as long as one monthly rebalance.

### F3. The investable result is negative after costs, and its sign is set by an assumption

48 monthly periods, top-2, 60-month window, absolute filter on (the page defaults):

| Mode | Excess vs Nifty (gross) | @10 bps/side | @25 bps/side | @50 bps/side | One-way turnover / month | Reported Sharpe | Sharpe with 6.5% rf |
|---|---|---|---|---|---|---|---|
| All indices | +201.0% | +184.9% | +162.3% | +128.1% | 53.1% | 1.38 | 1.13 |
| Buyable only | +15.1% | +10.1% | +2.8% | −8.5% | 37.0% | 0.46 | 0.16 |
| **Buyable + entry rule** | **−4.1%** | −7.9% | **−13.3%** | −21.9% | 31.8% | 0.33 | **−0.02** |

- **Cash earns 0% and the absolute hurdle is 0%** (`backtest.py:233-234`, `:248-249`). The docstring calls
  this conservative. It is the dominant term. The entry-rule variant has 40% of its slot-months in cash.
  Crediting cash at 6.5%/yr moves its excess from **−4.1% to +9.2%**. Indian liquid funds and ETFs pay
  that rate, and a 0% hurdle lets the model hold a sector returning less than cash.
- **Sharpe omits the risk-free rate** (`backtest.py:328`: `cagr / vol`), while `analytics.py:126-130`
  subtracts 6.5%. The same app shows two incompatible Sharpe definitions.
- **The final "month" is 7 sessions.** It runs 30 Sep → 9 Oct 2026. `rebalance_dates`
  (`backtest.py:61-63`) treats the current partial month as a month end, and `_stats` annualises it as
  a full period.
- **The README's figures are stale and hand-typed:** +237.3% / +26.2% / +1.1%, against +201.0% / +15.1% /
  −4.1% today.

### F4. The headline signal number is built on backfill and hindsight selection

- The +201% "All indices" result comes from a narrow set of high-volatility thematic and PSU indices.
  Of 96 slot-months: Defence 15, PSU Bank 13, Capital Markets 11, Railways 8, Metal 6, Internet 6.
  NSE back-calculates history for a newly launched index to before its launch date, and the model cannot
  tell launched from back-calculated history: `Exposure` has no `launch_date`
  (`src/models/exposure.py:57-64`). Before 2024, Defence and Railways were 12 of the 28 slot-months held.
- The 47-index universe was chosen in 2026 with a full-sample correlation screen (README, "Choosing a new
  exposure"). That is look-ahead in universe construction.
- **Volatility tilt.** The top-2 picks' trailing volatility averaged **1.26× the universe median**, and was
  above the median in **87% of months**. Nothing in `rank_exposures` (`ranking.py:39-78`) adjusts for
  risk.
- **Forking paths.** The Backtest page exposes 3 × 4 × 4 × 4 × 3 × 3 × 2 = **3,456 configurations**, plus
  6 weightings (`app/data.py:214-221`). The best signal's rank IC has t ≈ 2.3 (section 2) over 47 months.
  None of it clears a t > 3 multiple-testing hurdle (Harvey, Liu & Zhu 2016).

### F5. Silent integrity holes on the benchmark and in ingestion

- **The benchmark's value type is never recorded.** `fetch_benchmark` sets `attrs["value_type"]`
  (`jugaad_indices.py:106/113`), but `run_pipeline.py:363` hardcodes `"benchmark_source"` and drops the
  type. `1_Overview.py:45` hardcodes the label "NIFTY 50 TRI". If NSE serves the price index for the
  benchmark one night, every one of the 47 relative numbers is overstated by about Nifty's dividend
  yield, and nothing alerts. The level (34,220) is consistent with TRI today, but nothing proves it.
- **No value-type regression check.** `quality.py` checks counts and keys, never `value_type`, so a TRI → CLOSE
  flip on any exposure passes `--strict`.
- **Errors are swallowed.** `jugaad_indices.py:103-117` uses `except Exception: pass` twice and accepts any series ≥ 60
  observations (`:24`). Nothing checks chunk completeness. One missing 90-day chunk is about 62 of
  1,245 sessions, a 5.0% drop. That sits exactly on the `after < before * 0.95` line
  (`quality.py:127`).
- **The history never grows.** Every night re-downloads a rolling 5-year window from scratch
  (`run_pipeline.py:173,177,193`; `jugaad_indices.py:126`), with single-attempt requests: roughly 47
  indices × 21 ninety-day chunks × up to 2 endpoints. The oldest day falls off every night, so the
  "60-month" backtest can never become longer, and it changes daily even when nothing new is learned.
  Nothing is stored append-only, so an NSE restatement is undetectable.
- **Price validation is dead code.** `validate_price_matrix` and `validate_returns`
  (`src/quantitative/validation.py`) are never called outside tests.

---

## 2. Mathematical and logic correction sheet

### 2a. What the data says about the literature's prescriptions

Spearman rank IC of each signal against the next month's log return relative to Nifty, over 47 monthly
cross-sections (partial October excluded):

| Signal | Mean IC | t | Hit rate |
|---|---|---|---|
| Live composite (equal z of 1/3/6/12M) | 0.094 | 2.30 | 62% |
| 12M / σ(126d) | 0.078 | 2.29 | 60% |
| 1M | 0.077 | 2.25 | 62% |
| 12M | 0.072 | 2.01 | 60% |
| 6M | 0.067 | 1.60 | 55% |
| 3M | 0.066 | 1.57 | 60% |
| 12-1M (skip month) | 0.057 | 1.59 | 55% |
| 6-1M | 0.038 | 0.92 | 55% |

- **Do not skip the last month.** Jegadeesh (1990) found 1-month reversal in *individual stocks*.
  Moskowitz & Grinblatt (1999) found industry momentum strongest at the 1-month horizon, with no
  reversal. These sector indices behave like industries: 1M IC is +0.077, and skipping it lowers the
  12M IC from 0.072 to 0.057. Applying 12-1 (Jegadeesh & Titman 1993; Asness, Moskowitz & Pedersen 2013)
  here is cargo-culting.
- **Volatility-adjusting 12M costs no IC** (0.078 vs 0.072). It removes the high-beta tilt
  (Moskowitz, Ooi & Pedersen 2012; Barroso & Santa-Clara 2015; Daniel & Moskowitz 2016 on momentum
  crashes). Adopt it for risk reasons, not because it "wins".
- **Nothing here is evidence of an edge.** Eight signals were tried on 47 months, with best t ≈ 2.3.
  Treat every row as a prior, not a finding.

### 2b. Equation sheet

| # | Component | Current (file:line) | Defect | Replace with |
|---|---|---|---|---|
| 1 | Lookback return | `P[-1]/P[-L-1] − 1` by *position* after `dropna()` (`returns.py:8-12`, duplicated in `ranking.py:81-84`) | An exposure with gaps gets a longer calendar window than the benchmark. Latent (1 gap today), not a live error | `r_L = ln P(t) − ln P(τ)`, where `τ` is the last common session ≤ `t − L` calendar months on one shared calendar |
| 2 | Relative return | `R_a − R_b` (`returns.py:20-25`) | Arithmetic difference is not a return; it distorts at long horizons and high volatility | `ln(1+R_a) − ln(1+R_b)` |
| 3 | Composite | Equal-weight mean of `z_L` for L ∈ {1,3,6,12}M (`ranking.py:61-69`) | Lookbacks overlap, so with `z_L ∝ r_L/√L` the effective weights are **7.9 : 4.4 : 2.4 : 1.0** for month 1 : months 2–3 : 4–6 : 7–12. "Equal weight" is really a short-horizon signal, which drives the 53% monthly turnover | Score non-overlapping segments, `s = Σ_k w_k · z(r_{[a_k,b_k]})` with segments [0,1], [1,3], [3,6], [6,12] months, so the weights mean what the config says. Or declare the short-horizon tilt explicitly |
| 4 | Risk adjustment | None | Picks run 1.26× median volatility, 87% of months | `s_i = r_{i,12M} / σ_i`, with `σ_i` the 126-day EWMA of daily log returns × √252. Size positions by `w_i ∝ 1/σ_i`, normalised |
| 5 | Cross-sectional z | Mean/std with ddof=0, no winsorising (`ranking.py:26-32`) | One outlier (Telecom z = 2.58 today) dominates a 47-name cross-section | Winsorise at ±3σ, or use rank-normal scores `Φ⁻¹((rank − 0.5)/n)` |
| 6 | "RS ratio" | `RS / SMA₅₂(RS)` (`relative_strength.py:19-22`) | Labelled "vs benchmark" everywhere; it is vs the line's own trend | Rename to "RS vs its 52-week trend". If "beats benchmark" is what's meant, use `r_{rel,12M} > 0` |
| 7 | RS velocity | `ΔMRS` over 13 weeks, zero threshold (`relative_strength.py:25-26`) | 3-week median Leading spells | Bands: enter Leading at `ratio ≥ 1 + ε` and `velocity ≥ δ`; leave only at `ratio < 1 − ε`. Or keep RRG out of decisions entirely (recommended) |
| 8 | Decision rule | BUY/REDUCE/WATCH labels (`metrics.py:239-252`) | BUY ≡ Leading ∧ z>0, REDUCE ≡ Lagging. Not a portfolio | One rule: target weights = top-N by score, passing the absolute hurdle, with a buffer (rows 9 and 12). RRG becomes a display layer |
| 9 | Absolute filter | Own `R_12M > 0`, backtest only (`backtest.py:229-236`); none live | Hurdle is 0, not cash; absent live | Antonacci (2014): hold only if `R_{i,12M} − R_{f,12M} > 0`, with `R_f` from a liquid or overnight fund NAV via the existing MFAPI route. Market switch: risk-on iff Nifty 50 TRI `R_12M − R_f,12M > 0` (optionally also `P > SMA₁₀ₘ`, Faber 2007). Apply identically live and in backtest |
| 10 | Cash | 0% (`backtest.py:248-249`) | Flips the entry-rule result from +9.2% to −4.1% | Accrue `R_f` per period on the cash weight |
| 11 | Execution | Rank at close t, buy at close t (`backtest.py:240-246`) | Same-close fill (the Method page admits it) | Signal at close t, fill at close t+1: `r = P(t₁+1)/P(t+1) − 1` |
| 12 | Hysteresis | None | 53% one-way monthly turnover in All-indices mode | Buy at rank ≤ N, hold while rank ≤ M. A pre-specified M = 2N = 4 (one run, not tuned) cut turnover 53% → 33% with gross 201% → 198% and net at 25 bps 162% → 173% (Novy-Marx & Velikov 2016 on banding) |
| 13 | Costs | Zero | See F3 | `cost_t = c · Σ_i |Δw_i|`, with `c` = brokerage + STT + half-spread + premium/discount to NAV for ETFs (the snapshot already holds it). Report net figures first |
| 14 | Turnover | `|current △ previous| / 2N` (`backtest.py:265`) | Counts a move to cash at half its size ({A,B} → {A, cash} reads 0.25, truly 0.5) | `τ_t = ½ Σ_i |w_{i,t} − w_{i,t⁻}|`, with cash as an asset |
| 15 | Partial period | Current month counted as a full period (`backtest.py:61-63`) | Annualisation error; last row is 7 sessions | Drop an incomplete final month, or annualise by actual days |
| 16 | Backtest Sharpe | `CAGR / σ` (`backtest.py:328`) | No risk-free rate; mixes geometric and arithmetic | `SR = mean(r − r_f) / std(r − r_f) · √12` from monthly excess returns. Also report the Deflated Sharpe (Bailey & López de Prado 2014) with the 3,456-configuration trial count |
| 17 | Exposure Sharpe | `(CAGR − rf) / σ` (`analytics.py:126-130`) | Geometric numerator over arithmetic denominator | Same formula as row 16, on daily data × √252 |
| 18 | Alpha | `CAGR_a − [rf + β(CAGR_b − rf)]` (`analytics.py:189-191`) | β from daily OLS, α from CAGRs: inconsistent | OLS `r_a − r_f = α + β(r_b − r_f) + ε` on monthly returns, annualised α, Newey-West t |
| 19 | Consistency | Share of daily-stepped overlapping rolling windows (`analytics.py:226-248`) | n of about 1,000 overlapping windows reads as precision; effective n ≈ 4 | Non-overlapping windows, or report effective n = span / window |
| 20 | `tracking_error` column | Exposure-vs-Nifty active risk (`run_pipeline.py`, `_analytics_columns`) | Same name as the vehicle tracking error the README says is null | Rename to `active_risk` |

---

## 3. Proposed modular system architecture

**The single rule.** One function produces target weights. The live board shows its output for the last
rebalance date, and the backtest calls it at every rebalance date. Nothing else may decide.

```text
src/
  config/
    strategy.json          # N, M (buffer), lookbacks, weights, hurdle source, cost model, cadence (versioned; hash written to metadata)
    universe.json          # moved from data/universe; adds launch_date, base_date per exposure
  data/                    # I/O only; no math
    sources/jugaad.py      # retries + backoff + chunk-completeness check; returns (series, value_type)
    sources/mfapi.py, amfi.py, nse_etf.py, yahoo.py
    calendar.py            # NSE session calendar derived from the benchmark; expected-session checks
    store.py               # append-only raw store: data/raw/{kind}/{id}/{yyyy}.parquet; incremental fetch; restatement diff
    contracts.py           # pandera/pydantic schemas for every parquet the app reads
  quant/                   # pure functions, numpy/pandas only, no I/O, no streamlit
    returns.py             # calendar-anchored log returns (fixes rows 1-2)
    score.py               # segment composite, vol-adjusted score, winsorised z (rows 3-5)
    rs.py                  # Mansfield RS, RRG quadrants — display only (rows 6-7)
    risk.py                # Sharpe/Sortino/alpha/drawdown with one rf convention (rows 16-19)
  portfolio/
    construct.py           # target_weights(scores, eligibility, hurdle, prior_weights, config) -> TargetPortfolio
    trades.py              # diff(prior, target) -> orders (exposure, vehicle, Δweight, action)
    vehicles.py            # choose vehicle per exposure: index fund vs ETF by tracking difference, premium, days-to-build
  backtest/
    engine.py              # loops rebalance dates, calls portfolio.construct, t+1 fills, costs, cash accrual
    stats.py               # net-first stats, deflated Sharpe, rolling windows, period split
  pipeline/
    run.py                 # ingest -> validate -> score -> construct -> backtest(default config) -> write artifacts
    quality.py             # + value_type flip, benchmark value_type, chunk gaps, calendar completeness
app/                       # rendering only: reads artifacts, formats, no decisions
  streamlit_app.py
  views/1_Portfolio.py  2_Rankings.py  3_Evidence.py  4_Exposure.py  5_Data_Health.py  6_Method.py
  components/{theme,tables,charts}.py
tools/                     # depends on src/ only, never on app/
tests/
  quant/  portfolio/  backtest/  data/  pipeline/
  test_live_equals_backtest.py   # last rebalance: live target weights == backtest's final holdings
```

**Artifacts the app reads** (all written by `pipeline/run.py`; new ones in bold):

| File | Contents |
|---|---|
| **`portfolio_target.parquet`** | `asof, next_rebalance, regime, exposure_id, vehicle, target_weight, prior_weight, action, reason` |
| **`orders.parquet`** | `exposure_id, vehicle, delta_weight, est_cost_bps` |
| **`backtest_default.parquet` + `backtest_stats.json`** | Default config only, net of costs; replaces hand-typed README numbers |
| `summary_rankings.parquet` | Scores, stages, analytics, with RRG fields marked display-only |
| `index_prices.parquet`, `etf_prices.parquet`, `rs_matrix.parquet` | As today |
| `metadata.json` | + `benchmark_value_type`, `strategy_config_hash`, `history_start` (growing, not rolling) |

**Boundaries enforced in CI:**
- `import-linter` contracts: `src.quant` imports nothing from `src.data`, `app` or `streamlit`, and `app`
  never imports `src.portfolio.construct`.
- Run `ruff` (it's in `requirements-dev.txt`, but `tests.yml` never runs it) and `mypy --strict` on
  `src/quant` and `src/portfolio`.
- Use a `pyproject.toml` installable package to delete the `sys.path.insert` hack repeated at the top of
  every view (`1_Overview.py:8-10` and seven others).
- Use `logging` in place of `print(..., file=sys.stderr)` (`run_pipeline.py:_stage`,
  `jugaad_indices.py:133`).

**Today's coupling to cut first:** the decision rule (`decision_frame`) lives in `app/components/metrics.py`,
which imports `streamlit` at line 10, and `tools/detect_alerts.py:23` imports it. The nightly alert job
therefore depends on the UI package.

---

## 4. Target user interface blueprint

**The 5-second test, today:**

| Question | Answer on `/` today |
|---|---|
| What is my allocation? | Not shown anywhere. There are 12 BUY labels, no weights, and 6 of them are unbuyable |
| Risk-on or risk-off? | Contradictory: a BEARISH chip in the header beside 12 BUYs |
| What trade now? | Not derivable. No prior holdings, no deltas, no vehicle on the BUY row |
| Next rebalance? | No page shows a date. "Rebalance" appears only generically on the Backtest and Method pages, and never in `1_Overview.py` |

**Page 1: Portfolio** (replaces `1_Overview.py`). Everything above the fold is answerable from
`portfolio_target.parquet`.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ RISK-OFF  Nifty 50 TRI 12M −8.3% vs cash +6.5%      Next rebalance: 30 Oct   │  ← one line, colour = regime
│ Data as of 09 Oct 2026 · 47/47 TRI · strategy v1.0 (a1b2c3)                  │
├──────────────────────────────────────────────────────────────────────────────┤
│ TARGET PORTFOLIO                                                             │
│  Exposure            Vehicle           Target   Held now   Action            │
│  Pharma              PHARMABEES          40%      0%       BUY  +40%         │
│  Mid & Small Health  <index fund>        30%     50%       TRIM −20%         │
│  Cash (liquid fund)  <liquid fund>       30%     50%       —                 │
│  Est. cost of these trades: 0.15% · days to build at ₹30L: 1                 │
├──────────────────────────────────────────────────────────────────────────────┤
│ Why: one line per row, e.g. "rank 3, 12M/vol score +1.4, 12M excess over     │
│ cash +13.7%; Telecom (rank 1) skipped: no fund"                              │
├──────────────────────────────────────────────────────────────────────────────┤
│ ON THE EDGE (ranks N+1…M): names that would enter or leave next rebalance    │
└──────────────────────────────────────────────────────────────────────────────┘
```
(Values are illustrative layout only, not model output.)

Rules for this page:
1. No counts of labels, no breadth bar, no three-column action board, no full ranking, no audit dump.
   Each moves to a secondary page.
2. Exactly one colour-coded state, the regime. Actions are in text: BUY / TRIM / SELL / HOLD / —.
3. A name without a vehicle never appears in the portfolio. It appears only in "Why", as the reason a
   lower rank was taken.
4. Between rebalances the page says "No trades until 30 Oct". Daily signal drift is not shown here.
   Alerts fire only on rebalance-date orders or a regime change.

**Secondary pages, reached from the top nav:**
- **Rankings.** Merge `2_Sectors.py`, `3_Themes.py` and `4_Rankings.py`. The first two are copies:
  `diff` shows only labels, the category filter, chart row limits (22 vs 21) and widget keys. One table, a Sector/Theme/All segmented
  control, and the RRG scatter collapsed by default.
- **Evidence.** Today's `5_Backtest.py`, rebuilt. It shows the precomputed default config net of costs
  first: equity curve vs Nifty, net excess, deflated Sharpe, rolling 12M distribution, early/recent
  split. The 3,456-way control panel goes into an expander titled "What-if (not validated)", and each
  run there is labelled as one of 3,456 trials.
- **Exposure, Data Health, Method:** keep. Fix the RS-ratio wording throughout.

**Defects to fix regardless:**
- `streamlit_app.py:31` links the logo to `/Overview`, which returns "Page not found" on the live site.
  The default page is served at `/`, and its `url_path="Overview"` at `:44` is not routable.
- `1_Overview.py:45` hardcodes "TRI".

---

## 5. Prioritised refactoring plan

**Phase 0: stop publishing wrong statements (no strategy change, ~1–2 days)**

| # | Action | Files | Done when |
|---|---|---|---|
| 0.1 | Record the benchmark `value_type`; add value-type-flip and benchmark-type checks as error-level alerts | `pipeline/run_pipeline.py:193,363`, `src/quantitative/quality.py` | A test with a CLOSE benchmark fails `--strict` |
| 0.2 | Make the jugaad fetch fail loudly: log exceptions, retry with backoff, and reject a series with a missing chunk (fewer sessions than the benchmark calendar for that span) | `src/data/jugaad_indices.py:98-117` | Test with one empty chunk → series rejected, alert raised |
| 0.3 | Correct the RS-ratio wording ("vs its 52-week trend") and the redundant rule text | `app/components/metrics.py:174-197`, `app/views/1_Overview.py:114-116,150-157`, README decision table, `8_Method.py` | `grep -n "the benchmark" app/` shows no RS-ratio claims |
| 0.4 | Backtest correctness: drop the partial final period, Sharpe with rf, cash accrues rf, turnover includes cash, add `momentum_z > 0` to `require_buy` (or document its absence) | `src/quantitative/backtest.py:52-69,225,248-249,265,328` | New tests in `tests/test_backtest.py` per item |
| 0.5 | Remove the hand-typed backtest numbers from README; the pipeline writes `backtest_stats.json` | `README.md` (Backtest section), `pipeline/run_pipeline.py` | README cites the Evidence page |
| 0.6 | Fix the logo link and the hardcoded "TRI" label | `app/streamlit_app.py:31`, `app/views/1_Overview.py:45` | `/` loads with no "Page not found" |
| 0.7 | Delete dead files: the six stray `init.py` stubs (`src/init.py`, `src/{data,models,quantitative,universe}/init.py`, `app/components/init.py`) and the unused `validate_price_matrix`/`validate_returns`, `multi_period_returns` — or wire the validators into the pipeline (preferred for the validators) | as listed | `pytest` green |

**Phase 1: one model (the core fix)**

| # | Action | Files |
|---|---|---|
| 1.1 | Create `src/config/strategy.json` and freeze v1.0 *before* looking at any new result. Pre-specify N=2, M=4, 12M/σ score (or the segment composite), cash hurdle, t+1 fills, 25 bps/side | new |
| 1.2 | `src/portfolio/construct.py`: `target_weights(...)` implementing table rows 8–12 | new |
| 1.3 | Rewrite the `run_backtest` loop body to call `target_weights` and apply t+1 fills, costs and cash accrual (rows 10–15) | `src/quantitative/backtest.py:194-272` → `src/backtest/engine.py` |
| 1.4 | Move `decision_frame` out of `app/` to `src/quant/rs.py` as display-only RRG labels; `tools/detect_alerts.py` diffs `portfolio_target.parquet` instead | `app/components/metrics.py:222-278`, `tools/detect_alerts.py:23` |
| 1.5 | `tests/test_live_equals_backtest.py`: the live target at the last rebalance equals the backtest's final holdings, byte for byte | new |

**Phase 2: data that can be trusted for longer than 5 years**

| # | Action | Files |
|---|---|---|
| 2.1 | Append-only raw store with incremental fetch (only sessions after the last stored date, plus a 10-session overlap to detect restatements). History grows instead of rolling | `src/data/store.py` new; `run_pipeline.py:173,177,193`; `jugaad_indices.py:126` |
| 2.2 | Add `launch_date` and `base_date` per exposure; the backtest treats pre-launch history as not investable in every mode, and shows "All indices" with and without back-calculated history | `src/models/exposure.py:57-64`, `data/universe/universe.json`, backtest |
| 2.3 | A cash series: a liquid or overnight fund NAV through the existing MFAPI path, stored like any vehicle | `src/data/mfapi.py`, universe config |
| 2.4 | `calendar.py`: expected sessions from the benchmark; ingestion and quality checks use it | new |
| 2.5 | Schema contracts on every artifact; the app refuses an artifact that fails its schema | `src/data/contracts.py` new; `app/data.py:19-25` |

**Phase 3: the interface**

| # | Action | Files |
|---|---|---|
| 3.1 | New `1_Portfolio.py` per section 4; delete the current dashboard body | `app/views/1_Overview.py` |
| 3.2 | Merge Sectors and Themes into Rankings | delete `app/views/2_Sectors.py`, `3_Themes.py`; extend `4_Rankings.py` |
| 3.3 | Evidence page reads `backtest_default.parquet`; what-ifs behind an expander; `max_entries` on `_backtest`/`_sensitivity` caches (each cold run is 4.1 s locally; the sensitivity grid is 6 runs) | `app/views/5_Backtest.py`, `app/data.py:113,224` |

**Phase 4: the only evidence that will count**

| # | Action |
|---|---|
| 4.1 | From the first rebalance after v1.0 is frozen, commit `portfolio_target.parquet` every rebalance and never rewrite it. A forward paper record is the only out-of-sample test this universe will ever have. With only five years of data, every backtest answer is in-sample |
| 4.2 | Report the forward record next to the backtest on the Evidence page, with a deflated Sharpe. Revisit v1.0 only after 24 forward months |

**Do not do:**
- Do not adopt 12-1 skip-month. It is contradicted here (section 2a).
- Do not pick weights from the sensitivity grid.
- Do not add more lookbacks, filters or toggles before Phase 1 exists. More configurations make the
  overfitting problem worse, not better.

---

### References (cited by author and year)
Jegadeesh (1990), J. Finance; Jegadeesh & Titman (1993), J. Finance; Moskowitz & Grinblatt (1999),
J. Finance; Faber (2007), J. Wealth Management; Moskowitz, Ooi & Pedersen (2012), J. Financial Economics;
Asness, Moskowitz & Pedersen (2013), J. Finance; Antonacci (2014), *Dual Momentum Investing*; Bailey &
López de Prado (2014), J. Portfolio Management; Barroso & Santa-Clara (2015), J. Financial Economics;
Daniel & Moskowitz (2016), J. Financial Economics; Harvey, Liu & Zhu (2016), Rev. Financial Studies;
Novy-Marx & Velikov (2016), Rev. Financial Studies.
