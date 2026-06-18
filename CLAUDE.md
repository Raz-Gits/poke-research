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
  fallback; + a systematic **Kanto/Gen-1 tilt**: every char with dex# 1-151
  gets +0.75, capped 9.5, never lowering — preserves intra-region ranking,
  validated to not hurt forward IC), `scarcity` = 10·(0.7·rarity_rank +
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
  saturation. Needs `EBAY_APP_ID`/`EBAY_CERT_ID` in `.env` (gitignored). Until
  then dynamics stays `awaiting_data` — the live site must NEVER present
  simulated data as real.
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

- eBay demand feed: waiting on the owner's Production key → `.env` (see
  `EBAY_SETUP.md`). After it's live: fix the demand-gauge scale + relabel the
  movers chip stub→live in `docs/app.js`. The backtest's Hyper-Rare/blue-chip
  blind spot is exactly what this demand signal should fill — re-run the backtest
  after to measure the lift.
- Black Bolt (zsv10pt5) + Mega Evolution (me1) pull odds are special-set
  ESTIMATES (`pullrates.py`), pending the owner's large-sample numbers. Shrouded
  Fable's Hyper is also a small-sample estimate (~1/240).
- The id-map is built from TODAY's live TCGplayer products (mild survivorship);
  delisted cards never enter the backtest. Re-runs need `data/tcgcsv_archive/`
  (gitignored, ~380MB) re-downloaded — `data/history/` panel is committed.
- Possible future signal: Google Trends "universal appeal".
