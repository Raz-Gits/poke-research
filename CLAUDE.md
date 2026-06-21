# Poke Research — project guide for Claude

Free Pokémon TCG analytics site modeled on mycollectrics.com ("Collectrics IQ /
Price Lab"), aiming to match-or-beat it. Scores cards as over/under/fair-valued
from a clustered price model, surfaces undervalued/overvalued cards + sealed EV.

- **Local:** `~/Pokemon Bot/poke-research` · **GitHub:** Raz-Gits/poke-research (**private**)
- **Live:** deployed on **Netlify** (auto-deploys from `main` on every push;
  `netlify.toml` pins publish dir = `docs`). GitHub Pages is **disabled**.
- **Owner:** values accuracy and honest signals; this is a clean analytics tool —
  **never** build scalping / anti-bot evasion / auto-checkout.

## Stack & data flow

Python pipeline (stdlib + numpy in `.venv`) → writes `docs/data/*.json` → static
vanilla-JS frontend in `docs/` (Miro design system, see `DESIGN.md`). No build
step for the frontend; Pages serves `/docs` directly.

```
fetch.py ──→ data/normalized/cards.json ──→ build.py ──→ docs/data/{cards,model,
  (pokemontcg.io + TCGdex prices)                         leaderboard,sets,meta,
                                                          premium_review}.json
```

## Run it

```bash
./refresh.sh                                  # SHORTCUT: fetch + build (DEPLOY=1 to push live)
./.venv/bin/python -m pipeline.fetch          # refresh prices (pokemontcg.io + TCGdex)
./.venv/bin/python -m pipeline.build          # recompute everything -> docs/data
./.venv/bin/python -m pipeline.review_premium # premium vs price discrepancy report
./.venv/bin/python -m collectors.wikipopularity  # refresh Wikipedia views (rarely)
./run_daily.sh            # fetch + build (DEPLOY=1 to also git commit+push docs/data)
```
```bash
# Backtest pipeline (validates the model against real TCGplayer history)
./.venv/bin/python -m collectors.tcgcsv idmap   # rebuild card->TCGplayer id-map (+ coverage)
./.venv/bin/python -m collectors.tcgcsv         # download archives + backfill data/history/
./.venv/bin/python -m pipeline.backtest         # walk-forward backtest -> docs/data/backtest.json
```
Deploy = commit + push to `main`; **Netlify** rebuilds and swaps in ~1 min
(hard-refresh). No GitHub Pages anymore. `pip install -r requirements.txt`
(numpy, py7zr) into `.venv` on a fresh clone.

## Pipeline modules (`pipeline/`)

- **config.py** — `SETS` (15: SV + Mega-era), `FEATURES` (label/status/min/max →
  drives the frontend sliders), model constants, `SITE_DATA = docs/data`.
- **fetch.py** — normalize cards; fills Mega-set prices from TCGdex (pokemontcg.io
  doesn't price them). `base_name` is supertype-aware.
- **pullrates.py** — `BASE_TIER_PROB` + per-set `SET_TIER_PROB`. SV sets (151,
  Prismatic, Paldean Fates) and the 4 Mega-era sets (Ascended Heroes, Perfect
  Order, Chaos Rising, Shrouded Fable) now have data-backed per-rarity odds
  (only Shrouded's Hyper is still a small-sample estimate). pull_cost =
  pack_price ÷ (tier_prob ÷ #cards-of-that-rarity-in-set).
- **signals.py** — `char_premium_table` (uses popularity.py + structural
  fallback; now FULLY price-INDEPENDENT — the old 30% current-price component was
  dropped per the Codex audit, `_CHARPREM_W_PRICE=0`: it was mild residual
  circularity for no-prior chars; backtest showed dropping it holds forward IC +
  improves decile spread; + a systematic **Kanto/Gen-1 tilt**: every char with
  dex# 1-151 gets +0.75, capped 9.5, never lowering — preserves intra-region
  ranking, validated to not hurt forward IC), `scarcity` = 10·(0.7·rarity_rank +
  0.3·age_factor), `set_rank` = within-set **rarity-tier** percentile
  (price-FREE, non-circular — was a within-set *price* percentile that leaked
  the label, corr 0.86 w/ price; swapped after the formula-eval backtest),
  stub features (demand_pressure/grading/universal_appeal).
- **popularity.py** — character premium backbone (see below).
- **review_premium.py** — flags price-vs-premium discrepancies for manual review.
- **model.py** — clustered ridge regression on log(price), one model per
  (supertype · rarity) cluster + global fallback. R²(log) ≈ 0.92 (was 0.96
  before removing the circular set_rank — R² is IN-SAMPLE fit, NOT accuracy;
  judge the model on forward IC, not R²; the frontend chip says "in-sample fit").
- **market_dynamics.py** + **collectors/ebay.py** — eBay demand pressure / supply
  saturation. `EBAY_APP_ID`/`EBAY_CERT_ID` are LIVE (in `.env`, gitignored; also
  GitHub repo secrets for the Action). Browse API = ACTIVE listings only (no
  public sold endpoint), so demand is INFERRED from day-over-day listing/price
  diffs → needs a few daily snapshots to accrue. Collector hardened after a
  rate-limit incident: `MAX_PAGES_PER_CARD=1`, `REQUEST_PAUSE_S=0.25` (~4 req/s;
  20/s tripped eBay's burst limit → 65-min 429 backoff crawl), plus wall-clock
  (7-min) + consecutive-fail circuit-breakers so a sweep can NEVER hang. The
  daily sweep is scoped to cards ≥ `$LEADERBOARD_MIN_PRICE` (~850, valuable-
  first) — the only cards the signal serves. **Market-anchored price band**
  (`_apply_price_band`, `PRICE_BAND_LOW=0.5`/`HIGH=4.0`, anchor ≥$2): drops eBay
  listings <50% / >4× the card's TCGplayer `market_price` BEFORE IQR cleaning —
  the free-text search matches same-name printings (a chase IR query also pulls
  the $2 base print), which collapsed avg_price (audit: Ethan's Ho-Oh ex read
  $5.71 vs $198). Verified live to fix the mismatches without hurting good
  matches (`experiments/verify_price_band.py`). Still NOT a model feature yet
  (dynamics is display-only / `awaiting_data`); the live site must NEVER present
  simulated data as real. When wiring into the model/backtest, `compute()` MUST
  become as-of-date aware (it currently reads latest history) or it leaks.
- **collectors/wikipopularity.py** — caches Wikipedia article views.
- **collectors/tcgcsv.py** — real TCGplayer price *history* from tcgcsv.com (free
  mirror of TCGplayer's price API; NOT a scrape). Builds the card→productId
  id-map by (set→group)+(collector number), name-validated (2937/2937);
  downloads daily `.ppmd.7z` archives → `data/history/price-<date>.json` panel.
  `SET_TO_GROUP` + `RARITY_CORRECTIONS` (fetch.py) handle source quirks.
- **backtest.py** — walk-forward backtest: refit the model as-of each historical
  date (no lookahead), score over/under calls vs real later prices. Newey-West
  (HAC) significance, age-gating, floor sweep → `docs/data/backtest.json`
  (the Track Record page). build.py also writes `pred-<date>.json` each run for
  forward self-grading.

## Backtest / Track Record — what it found (honest)

The model's edge is **real but specific** (28-day horizon, HAC t). Current
formula (rarity-ordinal set_rank + Kanto tilt):
- **Strong on fresh releases** (post-release ≤35d): IC ≈ +0.27, HAC t ≈ 10.9,
  positive 63/64 weeks — fresh chase cards are overpriced and fall ~10%/month,
  and the model ranks which fall hardest.
- **≈ zero on mature, liquid cards** (>90d & >$10): IC ≈ −0.03 (HAC t −1.05,
  insignificant). Not a crystal ball for blue-chips. Edge also collapses above
  a ~$10 floor (cheap-card noise). all-cards IC ≈ +0.094 (t 6.5).
- **formula-eval (multi-agent, 6 variants)**: proved `set_rank` was circular
  (corr 0.86 w/ price), inflating R² 0.91→0.95 without aiding forward IC.
  Swapping to a non-circular rarity ordinal lifted fresh IC 0.23→0.27 and made
  R² honest. Supply-only (drop char_premium) is NOT better — it flips mature IC
  to significantly wrong-signed (t −2.27). Don't strip features; don't chase R².
  One modest cost: decile spread on 'all' dipped 0.096→0.081.
4 adversarial agents verified: no look-ahead leakage, id-map correct. They caught
the inflated naive t (10→~6 after HAC), the presale-window effect (TCGCSV carries
presale prices; headline fresh-cut excludes negative ages), and the ME variant
bug — all fixed. Present these numbers honestly; never lead with the inflated IC.

## Character premium — how it works (important, heavily iterated)

Popularity is a **durable, price-INDEPENDENT** signal (so an Eevee reads as
valuable for *being Eevee*, not because a card is currently hyped). Two
recognition signals combined in `popularity.py`:

1. **Wikipedia** 12-mo article views (mainstream recognition) — `data/wiki_pageviews.json`.
2. **2020 "Pokémon of the Year" poll** vote counts (fan recognition) — 240 ranked.

Combine: both present → `0.7·max + 0.3·min` (rewards corroboration, tempers
high-wiki/low-poll spikes like Raichu); poll-only trusted alone; wiki-only capped
at 8.3 (nostalgia noise — Jynx/Butterfree/Cubone). Characters with neither →
structural print-metadata fallback, compressed below 6.0.

**`USER_OVERRIDES`** in popularity.py win over everything (10.0 reserved for
them). The premiums are a **starting point, not gospel** — run `review_premium`,
eyeball the flags, and pin values in `USER_OVERRIDES`. Most "market hotter than
rating" flags are art-driven Illustration Rares (card art ≠ character fame).

## Open threads

- **Watchlists tab** (`#/watchlists`, `docs/app.js` `viewWatchlists`): a sealed-
  ETB **deal monitor**, separate from the price model. Fed by
  `docs/data/watchlist.json`, written by **`../ebay_deals.py`** (lives in the
  parent `~/Pokemon Bot`, NOT this repo — same place as the restock `monitor.py`).
  That watcher polls eBay Browse for a small watchlist (`../deals_watchlist.json`:
  6 ETBs incl. Pokémon Center variants) and pushes a phone alert (ntfy, reusing
  the restock monitor's `config.NTFY_TOPIC`) when a deal lands at/under the per-
  product `max_price` cap. Notify-only, manual buy — same clean-monitor boundary
  as the restock alerter (no scraping/auto-checkout; Browse API's intended use).
  Junk control = the SAME ">50% under market → ignore" rule as the card
  collector, anchored to each watch's `market_price` (clean live median), plus
  `exclude_all` keywords (graded singles incl. ACE/Black-Star-Promo slabs,
  opened/empty boxes, foreign-language prints, single-pack mislistings, proxies,
  lots). Already-ended/sold listings are dropped (`_hours_left < 0`) so neither
  the site nor the phone shows stale results. First run primes silently (no alert
  storm). **Phone-alert gate (`_push_worthy`):** only Buy-It-Nows + auctions
  ending within `PUSH_AUCTION_WINDOW_H` (24h) ping the phone; auctions with more
  time left ride the site until they enter the closing window, THEN ping (priming
  silences only currently-worthy ones, so a far-off auction still fires when it
  closes in). The **site keeps ALL** active under-cap deals (both kinds, any
  time-left) — the 24h/BIN gate is phone-only. The site JSON is a lean snapshot
  (aggregates + 2 best links + up to 8 under-cap listings); page shows "updated
  <time>".
  - **RUN MODEL (live):** always-on **launchd** service
    `~/Library/LaunchAgents/com.razsela.ebay-deals.plist` (label
    `com.razsela.ebay-deals`, KeepAlive, `PYTHONUNBUFFERED=1`, log →
    `~/Pokemon Bot/ebay_deals.log`), mirroring the restock `com.razsela.pokemon-
    monitor`. Runs the loop (180s sweeps). `launchctl unload …plist` to pause.
  - **TODO:** optional periodic auto-commit of `watchlist.json` so the live site
    tab stays fresh between manual pushes (service updates the LOCAL JSON each
    sweep; the deployed tab only changes on commit+push).
- eBay demand feed is LIVE (Production keys in `.env` + GitHub secrets). Daily
  snapshots accrue via the `daily-refresh` GitHub Action (`.github/workflows/`,
  14:00 UTC: fetch → build [collects eBay, valuable-first, idempotent] → push →
  Netlify). Demand is still DISPLAY-ONLY, not a model feature yet. **Next big
  step — wire demand into the model** (after ~3-5 days of snapshots): (a) Codex
  #5 — make `market_dynamics.compute()` as-of-date aware FIRST (else look-ahead);
  (b) add demand features + backtest the lift on the dead mature segment; (c)
  Codex #4 — cross-fit/leave-one-out the displayed residuals (own-card leakage).
  Then fix the demand-gauge scale + movers chip stub→live in `docs/app.js`.
- Codex pricing audit (done): UI now respects a ±15% verdict band ("fair" inside
  it; `CARD_BAND` in app.js); char_premium price component dropped; RIDGE_ALPHA
  swept and kept at 1.0 (all within noise). #4/#5 above are the remaining items.
- PSA grading intensity (`collectors/psa.py`, token LIVE): real per-card DEMAND
  signal (graded pop + PSA-10 count) via PSA's free Public API. Gotchas: (1) auth
  is `authorization: bearer <PSA_API_TOKEN>` + a real User-Agent (Cloudflare 403s
  the default urllib UA, error 1010); (2) the API has NO card→spec search — pop
  is only by `specID`, so we keep a curated `data/psa_specs.json` (card_id→specID,
  looked up via web search → the number in a psacard.com `/spec/psa/<id>` URL),
  cache 14 days, ~100 calls/day free tier. Quick check on the leaderboard CONFIRMS
  it differentiates: overvalued chase cards (Umbreon 19k / Mew 48k graded) dwarf
  an undervalued peer (Eevee 8.7k). NOT yet a model feature — pop is a snapshot
  (no history), so it can't be backtested against the past; grow the spec map +
  accrue, then validate going forward. Output: `data/psa_pop.json`.
- Black Bolt (zsv10pt5) + Mega Evolution (me1) pull odds are special-set
  ESTIMATES (`pullrates.py`), pending the owner's large-sample numbers. Shrouded
  Fable's Hyper is also a small-sample estimate (~1/240).
- The id-map is built from TODAY's live TCGplayer products (mild survivorship);
  delisted cards never enter the backtest. Re-runs need `data/tcgcsv_archive/`
  (gitignored, ~380MB) re-downloaded — `data/history/` panel is committed.
- Possible future signal: Google Trends "universal appeal".
