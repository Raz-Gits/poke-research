# Poke Research — project guide for Claude

Free Pokémon TCG analytics site modeled on mycollectrics.com ("Collectrics IQ /
Price Lab"), aiming to match-or-beat it. Scores cards as over/under/fair-valued
from a clustered price model, surfaces undervalued/overvalued cards + sealed EV.

- **Local:** `~/Pokemon Bot/poke-research` · **GitHub:** Raz-Gits/poke-research
- **Live:** https://raz-gits.github.io/poke-research/ (GitHub Pages from `/docs`)
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
./.venv/bin/python -m pipeline.fetch          # refresh prices (pokemontcg.io + TCGdex)
./.venv/bin/python -m pipeline.build          # recompute everything -> docs/data
./.venv/bin/python -m pipeline.review_premium # premium vs price discrepancy report
./.venv/bin/python -m collectors.wikipopularity  # refresh Wikipedia views (rarely)
./run_daily.sh            # fetch + build (DEPLOY=1 to also git commit+push docs/data)
```
Deploy = commit `docs/data` and push; Pages CDN swaps in ~1-2 min (hard-refresh
the browser). Verify a deploy by curling `…/data/<file>.json?cb=$(date +%s)`.

## Pipeline modules (`pipeline/`)

- **config.py** — `SETS` (11: SV + Mega-era), `FEATURES` (label/status/min/max →
  drives the frontend sliders), model constants, `SITE_DATA = docs/data`.
- **fetch.py** — normalize cards; fills Mega-set prices from TCGdex (pokemontcg.io
  doesn't price them). `base_name` is supertype-aware.
- **pullrates.py** — `BASE_TIER_PROB` + per-set `SET_TIER_PROB`. SV sets (151,
  Prismatic, Paldean Fates) have real community samples; the 4 Mega-era sets are
  **PROVISIONAL** estimates (thin data — improve when real box breaks exist).
  pull_cost = pack_price ÷ (tier_prob ÷ #cards-of-that-rarity-in-set).
- **signals.py** — `char_premium_table` (uses popularity.py + structural
  fallback), `scarcity` = 10·(0.7·rarity_rank + 0.3·age_factor), `set_rank`,
  stub features (demand_pressure/grading/universal_appeal).
- **popularity.py** — character premium backbone (see below).
- **review_premium.py** — flags price-vs-premium discrepancies for manual review.
- **model.py** — clustered ridge regression on log(price), one model per
  (supertype · rarity) cluster + global fallback. R²(log) ≈ 0.96.
- **market_dynamics.py** + **collectors/ebay.py** — eBay demand pressure / supply
  saturation. Needs `EBAY_APP_ID`/`EBAY_CERT_ID` in `.env` (gitignored). Until
  then dynamics stays `awaiting_data` — the live site must NEVER present
  simulated data as real.
- **collectors/wikipopularity.py** — caches Wikipedia article views.

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
  movers chip stub→live in `docs/app.js`.
- Mega-era set pull rates are provisional — improve with real per-rarity odds.
- Possible future signal: Google Trends "universal appeal".
