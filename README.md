# Poke Research

A free, data-driven Pokémon TCG analytics site — card & set valuation built on open data.
Inspired by the Collectrics "IQ / Price Lab" approach; rebuilt from scratch on public APIs.

**Live site:** _(GitHub Pages — see the repo's Pages settings)_

## What it does

- **Price Lab** — a clustered regression estimates each card's "fair" price from explainable
  signals; the gap vs the live market flags **undervalued / overvalued** cards (ranked by raw $
  difference, like the original).
- **Sealed EV** — expected value of ripping each set, `Σ (pull_rate × card_price)`, vs the box
  price → the best "bang for your buck" sets.
- **Signals** — *live:* character premium, scarcity, pull cost, months-since-release, in-set rank.
  *Stubbed (pluggable):* demand pressure, grading intensity, Google-Trends appeal.
- **Interactive** — open any card → "View Market Signals" → drag the sliders and watch the
  expected price recompute live (client-side, from the card's cluster coefficients).

## The model

Ridge regression on `log(market_price)`, **one model per rarity cluster** (+ a global fallback) —
the clustering step the original author called out as necessary to fit thousands of cards.
Honest **R²(log) ≈ 0.97** across **1,601 priced cards / 8 modern sets**. The residual
`(market − expected)/expected` is the over/under signal. Chase cards (Umbreon, Mew, Charizard)
correctly sit at the top of expected price and read as "trading above fundamentals" — that premium
is exactly the demand/hype the stubbed feeds would capture.

## Data

- Cards, sets, rarities, images, prices → [pokemontcg.io](https://pokemontcg.io) (TCGplayer market).
- Pull rates → estimated from each set's rarity structure (`pipeline/config.py` → `SETS`,
  `pipeline/pullrates.py` → `TIER_PROB`); official rates are never published.
- eBay market dynamics, PSA pop, Google Trends → **stubs** with documented real-API paths.
  `collectors/ebay.py` seeds a daily snapshot so price/volume history accumulates from day one.

## Run it locally

```bash
python3 -m venv .venv && ./.venv/bin/pip install numpy
./.venv/bin/python -m pipeline.fetch    # pull fresh cards + prices + a daily snapshot
./.venv/bin/python -m pipeline.build    # compute EV + model + scores -> docs/data/*.json
cd docs && python3 -m http.server       # open http://localhost:8000
```

Run `fetch` + `build` on a daily cron to keep prices current and grow the history.

## Layout

```
pipeline/   fetch, pullrates, ev, signals, market_dynamics, model, build, config
collectors/ ebay.py            (daily listing-snapshot collector — stub + integration notes)
data/       normalized/, snapshots/   (source data + price history)
docs/       index.html, app.js, styles.css, data/*.json   (the static site Pages serves)
DESIGN.md   the visual system (Miro-inspired)
CONTRACT.md the build spec every module conforms to
```

## Caveats

Estimates, not financial advice. Pull-rate and pack-price inputs are rough and tunable. Built for
fun and learning. Card data via pokemontcg.io; design language adapted from Miro. Not affiliated
with Nintendo / The Pokémon Company / Collectrics.
