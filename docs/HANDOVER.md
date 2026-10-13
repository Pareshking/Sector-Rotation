# Handover — 14 Oct 2026

State of the Sector-Rotation project for whoever picks it up next: a person or a new Claude session.

- Repo: <https://github.com/Pareshking/Sector-Rotation> (public). Default branch `main`.
- Live app: <https://dualmomentum.streamlit.app>. Streamlit Community Cloud redeploys on every push to `main`.
- Design reference: the owner's other app, Paresh: <https://paresh.streamlit.app>. Its source is at `C:\Users\Quali\Paresh` on the owner's machine (repo `Pareshking/Paresh`).

## What the system is

Monthly dual-momentum rotation across 49 Indian sector and theme indices. 47 are NSE (TRI). Two are BSE, Insurance and Hospitals, and are **price-only**: BSE gives out its TRI only with a login.

The rules are strategy v1.1, in `src/config/strategy.json`:
- **Score:** a composite of non-overlapping 1M, 3M-1M, 6M-3M and 12M-6M returns.
- **Holdings:** the top N=2.
- **Retention buffer:** a holding is kept while it ranks within M=4.
- **Cash hurdle:** an exposure is held only while its 12-month return beats the liquid fund's (Nippon Liquid Fund, scheme 118701).
- **Trading:** fill at t+1 close; costs of 25 bps per side.

**Data flow:** a nightly GitHub Actions pipeline (`.github/workflows/data_pipeline.yml`, live mode) writes `data/processed/*` and `data/raw/*` and commits them. The app is a read-only consumer.

**Universe:** `data/universe/universe.json`, 49 exposures and about 159 funds (ETFs and index funds). Every fund has an ISIN, a scheme code and an inception date (its first NAV on MFAPI).

## What shipped on 12–14 Oct (PRs #71–#81)

| PR | What |
| --- | --- |
| #71 | First UI redesign (since superseded by the kit port) |
| #72 | NSE ETF snapshot: retries; keeps the last good snapshot for up to 14 days when NSE refuses GitHub's runners (it often does: 403); `etf_snapshot` block in metadata plus a warning alert; symbols METAL, MOTOUR, MOSERVICE added |
| #73 | ₹20 lakh **model book** (`src/portfolio/book.py`) and a first Paresh-style Portfolio page |
| #74 | Portfolio: sector mix and correlation side by side; version stamp removed from the header |
| #75 | **52 verified funds** added (ISIN matched across NSE, AMFI and MFAPI); `tracked_index` field for proxies (GROWWPOWER → BSE Power, ICICIB22 → BSE Bharat 22) |
| #76 | **Paresh's UI kit ported into `app/kit/`** (stylesheet, header, page kit, saas table, Lightweight Charts, Highcharts, calendar, heatmap); Screener made home; Portfolio rebuilt on the kit |
| #77 | **BSE Insurance and BSE Hospitals** as exposures (`src/data/bse_indices.py`, source `bseindices.com`, price-only, labelled) |
| #78 | **Actions** page (Paresh's `actions_view.py` with this strategy's rules; Kite basket CSV) |
| #79, #80 | **Screener** (Paresh's `ranking_view` and `screener_table`), then the table rebuilt to Paresh's Core table column for column |
| #81 | Evidence, Exposure, Data Health and Method rebuilt on the kit; README and this handover |

Tests: `python -m pytest -q` → 359 passed on #81.

## Owner's decisions (settled; don't re-ask)

- **Look:** white, clean, minimal, "exactly like Paresh". The owner rejected imitations: port Paresh's own code element by element and swap only the data. Light theme only. Keep text short; the owner said the site "looks like a text site".
- **Charts:** TradingView Lightweight Charts for time series, Highcharts otherwise. Personal use, so no logo or credit is needed (licences are in `app/kit/vendor`).
- **Missing values:** always "—", never "None".
- **Screener:** it is home, and opens on **tradeable** exposures by default.
- **Model book:**
  - ₹20 lakh start, history from the backtest start (Nov 2022);
  - every month labelled *Backfilled*, the running month *MTD*;
  - no Monthly record card (it repeated Calendar returns).
- **Funds:** add every verified fund on an index we already cover. A labelled proxy on a different index is acceptable ("something is better than nothing"), e.g. GROWWPOWER for NIFTY POWER.
- **Exposures:** BSE Insurance and Hospitals added as price-only. Do **not** add ESG, Shariah or factor ETFs.
- **Workflow:**
  - Ship small PRs and merge them so the owner can review live. The repo has no required checks, so `gh pr merge` merges at once; run the full suite first.
  - Use plain language and ask the owner specific questions. They will research facts, e.g. which funds track an index.

## Open items

1. **Ten exposures have no fund at all:** Capital Goods, Consumer Durables, Consumer Services, Media, NIFTY WAVES, Mobility, REITs & InvITs, Rural, Sugar & Ethanol, Telecom. The owner's research confirms none exists. Groww Nifty Sugar & Ethanol ETF has a SEBI draft filing (18 Sep 2026); add it once it lists.
2. **Sixteen newly added funds have no price history yet:** they are only weeks old or MFAPI has too few NAVs (e.g. CEMNTGROWW, INSUREIETF, INSURADD, EMETAL, MOMETAL, MOOILGAS, the Kotak and Invesco index funds). They fill in automatically; check `etf_skipped_symbols` in metadata.
3. **HDFCNIMEG (HDFC Nifty Metal ETF)** is left out because AMFI publishes no ISIN for scheme 154504. Add it when one appears.
4. **The NSE ETF snapshot** is often refused from GitHub (403). Carry-forward covers up to 14 days; past that, turnover and premium go blank. A durable fix would be another snapshot source (e.g. the nsearchives CSVs) or a self-hosted runner.
5. **Model book:**
   - Forward recording is built (PR #85): `tools/record_book.py` runs nightly and appends each closed month from Nov 2026 to `data/processed/model_book_record.csv` (append-only). The app pins the book to it (`src/portfolio/record.py`) and labels those months *Recorded*. The first row lands after the first nightly run in Dec 2026; check it then.
   - Vehicle choice uses tracking measured over the full history, a mild look-ahead.
6. **Remaining differences from Paresh:**
   - **Screener:** Paresh's stock columns (52W high, 50 EMA, volume) are replaced by a Model group. Column widths follow the content.
   - **Evidence / Exposure / Data Health / Method:** some kit tables take text columns where Paresh's renderer has no number format for them. Exposure has no full stock-page hero card. Not yet compared side by side with Paresh at 1280px.
   - **Bug in Paresh:** its own Screener group header is misaligned (its "3M" spans 3M Ret and 6M Ret).
7. **Optional:** the Dhan CSV gives AUM and expense ratio for CPSEETF, ICICIB22 and BANKBEES. The model has `tracking.aum_crore` and `tracking.expense_ratio`, currently null.
8. **Housekeeping:**
   - 30 orphaned folders under `data/raw/vehicle/<old wrong scheme code>`; the owner chose to leave them.
   - PR #2 (old diagnostic branch) is still open.
   - The auto-mode classifier blocks `git rm`.

## Working notes

- Run locally: `python -m streamlit run app/streamlit_app.py`. The `.claude/launch.json` configuration "streamlit" uses port 8501.
- **Headless check of a page:** `streamlit.testing.v1.AppTest.from_file("app/views/<page>.py").run()`. Kit tables render in iframes; the tests read them with `_iframe_text` in `tests/test_ui.py`.
- **Paresh's table renderer** (`app/kit/theme.py: render_saas_table`) formats by column name and raises on an undeclared percentage column. Use Paresh's names, or declare the column in `FRACTION_PERCENT_COLUMNS` / `SCALED_PERCENT_COLUMNS`.
- **Triggering the pipeline:** `gh workflow run data_pipeline.yml --ref main`. It takes about 3 minutes and commits data to `main`.
- **Sessions get auto-archived** when their PR merges, so the owner may think a chat was deleted. Project memory is under `~/.claude/projects/C--Users-Quali-Sector-Rotation/memory/`.
