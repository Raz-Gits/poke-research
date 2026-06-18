# Backtesting Poke Research — implementation plan

Status: **BUILT & deployed (2026-06-18).** All four components shipped:
- A) Forward prediction log — `pred-<date>.json` each build (`pipeline/build.py`).
- B) TCGCSV collector + 2937/2937 id-map + 123-week price panel (`collectors/tcgcsv.py`).
- C) Walk-forward backtest, refit-per-date, HAC significance (`pipeline/backtest.py`).
- D) Track Record page (`docs/app.js` `viewTrackRecord`, `docs/data/backtest.json`).

**Honest headline (28-day, overlap-corrected HAC t):** the edge is real but
specific — strong on freshly-released cards (post-release ≤35d: IC +0.22,
HAC t≈8, positive 57/64 weeks, avg −10% over the month), ~zero on mature liquid
cards (>90d & >$10: IC −0.02), modest overall (all $2+: IC +0.08, HAC t≈5).
Audited by 4 adversarial agents: no look-ahead leakage, id-map join verified;
they caught the inflated naive t (10→~6), the presale-window effect, and a
variant-resolution bug (all fixed). Below is the original spec for reference.

----

## The point

The site makes one falsifiable bet: a card we flag **undervalued**
(`residual_pct < 0` → market below model fair value) should, on average, drift
UP toward fair value faster than one we flag **overvalued** (`residual_pct > 0`).
Backtesting = grading that bet against real later prices, so we can see if we're
right and tune as we go.

`residual_pct = (market − expected) / expected` (negative = undervalued). This is
the model's existing convention (see `pipeline/model.py`, `docs/app.js` header).

## Where we are right now

- **Have:** daily PRICE panel — `pipeline/fetch.py` writes
  `data/snapshots/snapshot-<date>.json` = `{card_id: market_price}` every refresh
  (Jun 17, Jun 18 so far).
- **Missing #1 (forward grading):** we never record what the model PREDICTED that
  day (expected price / verdict). Without the prediction stored next to the price,
  we can see a price moved but not whether *we called it*. → Component A.
- **Missing #2 (backward data):** no price history before Jun 17. → Component B
  (TCGCSV).
- **Blocker found (the fiddly bit):** our normalized cards carry **no TCGplayer
  product ID** (`tcgplayer_id`/`tcgplayer` are null; the raw pokemontcg.io cache
  has zero `tcgplayer.com/product/<id>` URLs). So joining our cards to TCGCSV
  CANNOT be done by ID — it must be matched by **(set → TCGCSV group) +
  (collector number → TCGCSV product)**, with rarity as a tiebreaker. This is the
  main implementation risk; everything else is plumbing.

## Free backward data source — verified live

**TCGCSV** (`tcgcsv.com`) — a free, no-auth mirror of TCGplayer's OWN price API
(market/low/mid/high/direct per product, sealed included). NOT a scrape of their
JS site → stays on the right side of the "clean tool" line.

Verified 2026-06-18:
- Pokémon = `categoryId 3` (`Pokemon Japan` = 85, ignore for now).
- Daily archive: `https://tcgcsv.com/archive/tcgplayer/prices-<YYYY-MM-DD>.ppmd.7z`
  - `prices-2024-02-08.ppmd.7z` → HTTP 200, 2.1 MB (day 1 of archive)
  - `prices-2026-06-17.ppmd.7z` → HTTP 200, 3.9 MB (yesterday)
  - ⇒ **~2.3 years of daily real TCGplayer prices, free.**
- Archive expands to `tcgplayer/<categoryId>/<groupId>/{prices,products}` JSON.
  `.ppmd.7z` = 7-zip PPMd → needs `py7zr` (pure-python, pip) or system `7z`.

History depth varies by set: 151 has ~2 yr; the new Mega-era sets only weeks
(can't backtest a set before it existed — report per-set coverage honestly).

## Components

### A. Forward prediction logging  (cheap, ~30 min, starts grading TODAY)
- Hook in `pipeline/build.py` after `card_records` is built (≈ line 370).
- Write `data/snapshots/pred-<date>.json` =
  `{card_id: {"m": market, "e": expected, "r": residual_pct, "v": verdict}}`
  (verdict: `under` if r < −BAND, `over` if r > +BAND, else `fair`).
- Idempotent per day (overwrite). Commit these so the panel survives.
- From the day this ships, every refresh self-grades forward. No new deps.

### B. TCGCSV historical backfill  (the lift)
- `collectors/tcgcsv.py`:
  - download + extract daily archive for category 3 (cache raw under
    `data/tcgcsv_archive/`, gitignored — large).
  - one-time `build_idmap()` → `data/tcgplayer_idmap.json` =
    `{our_card_id: tcgplayer_productId}`, built by matching
    group→set (group name/abbreviation) and product→card (collector number,
    normalize "2" vs "002/165"; rarity tiebreak). Emit a coverage report
    (matched / ambiguous / unmatched per set) — DO NOT silently drop misses.
  - `backfill(dates)` → `data/history/price-<date>.json` = `{our_card_id: market}`
    for each historical date (weekly sample by default; densify near now).

### C. Walk-forward backtest harness  (`pipeline/backtest.py`)
For each eval date T in the panel (no lookahead):
1. Take T's price cross-section.
2. **Refit the model on T's prices** (`model.fit`), with as-of-T features
   (char_premium/scarcity are price-independent; `months_since_release`
   recomputed as-of T from `release_date`). This avoids using future info.
3. Compute residual_pct as-of T → verdict per card.
4. Look forward Δ days in the panel → realized return
   `(price_{T+Δ} − price_T)/price_T`.
5. Record (verdict, mispricing_T, forward_return, rarity, price_tier).

Aggregate across all T:
- **Hit-rate** — % of `under` calls that rose; % of `over` that fell.
- **Rank IC** — Spearman(mispricing_T, forward_return). The single cleanest
  "does our signal rank future winners" number.
- **Decile spread** — mean return of most-undervalued decile − most-overvalued
  decile (the "would the strategy have made money" number).
- **Breakdowns** — by rarity / price-tier / chase-vs-middle, to quantify the
  KNOWN blind spot (chase cards read overvalued because the eBay demand signal
  isn't wired — the backtest measures exactly how much that costs us).

Honesty guards: price floor like the leaderboards (drop penny cards); report
sample sizes; only cards that existed at T; refit-per-date (no lookahead).

### D. Results surface  (optional, after C reads clean)
- Write `docs/data/backtest.json` (headline metrics + breakdowns + IC time series).
- New "Track Record" route in `docs/app.js`: hit-rate, rank IC, decile-spread
  chart, rarity breakdown — labeled honestly. Makes the tool publicly
  accountable (a real edge over the YouTuber, who shows no track record).

## The feedback loop (the "adjust as we go" part)
Forward log (A) + periodic rerun of the backtest (C) = the tuning loop. When the
backtest surfaces a systematic miss (e.g. chase cards), the fix is concrete:
that residual is what the eBay demand signal should capture, or a manual
override, or a new feature. The backtest tells us which.

## Phasing (green-light any subset)
1. **A** — forward logging (cheap, do anytime; starts the clock honestly).
2. **B** — TCGCSV id-map + backfill (the real work; risk lives in the join).
3. **C** — backtest harness + metrics (gives the first real accuracy number).
4. **D** — site Track Record page.

## Open decisions (with my recommended defaults — I'll use these unless told otherwise)
1. **History granularity/range:** weekly samples per set release→now (~120 dates),
   densified to daily for the last ~30 days. (Daily-all = ~850 dates, heavier.)
2. **Holding horizon Δ:** 28 days primary; also report 7 / 56 / 84 days.
3. **Verdict band:** ±15% (under if r < −0.15, over if r > +0.15, else fair).
4. **7z dependency:** add `py7zr` to `.venv` (pure-python; no system 7z needed).
5. **Model basis:** refit-per-date (rigorous, no lookahead) over frozen-model.
6. **Repo hygiene:** gitignore raw archives + bulky `data/history/`; commit the
   compact `pred-*.json`, the id-map, and `docs/data/backtest.json`.

## What I need from you (only if you want non-defaults)
Nothing required — defaults above are sensible. The single thing that could need
your eyes is the **id-map coverage report** (Component B): if some sets match
poorly by number (promos, alt-number printings), I'll surface the unmatched list
for a quick manual confirm rather than guessing.
