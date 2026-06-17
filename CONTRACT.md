# Price Lab — build contract (single source of truth)

A Pokémon card analytics site, faithful to the "Collectrics IQ Price Lab" design but
built on free data (pokemontcg.io) with paid feeds (eBay/PSA/Trends) left as pluggable stubs.

Product name: **Poke Research**. Run everything from project root: `/Users/razsela/Pokemon Bot/poke-research`
Python (has numpy): `./.venv/bin/python`   Package root: `pipeline/`
`pipeline/fetch.py` already ran — real data is cached. Build against these files; don't refetch.

## Cached inputs (already produced)
- `data/normalized/cards.json` — list[NormalizedCard]
- `data/normalized/sets.json` — list[SetRecord]
- `data/snapshots/snapshot-<date>.json` — {card_id: market_price}  (price history seed)

NormalizedCard: `id, name, base_name, number, rarity, set_id, set_name, series,
release_date(YYYY-MM-DD), image_small, image_large, market_price(float|None),
price_variant, price_updated`
SetRecord: `set_id, name, series, release_date, printed_total, total, logo, symbol,
pack_price, packs_per_box, box_price`

## Rarity → pull-rate model  (owned by pipeline/pullrates.py)
Per-pack probability that a pack yields a card of each rarity (ESTIMATE, configurable):
```
TIER_PROB = {
  "Common": 1.0, "Uncommon": 1.0, "Rare": 1.0, "ACE SPEC Rare": 0.083,
  "Double Rare": 0.125, "Ultra Rare": 0.083, "Illustration Rare": 0.167,
  "Special Illustration Rare": 0.025, "Hyper Rare": 0.02,
  "Shiny Rare": 0.20, "Shiny Ultra Rare": 0.033, "Unknown": 0.05,
}
```
Per-card pull rate = `TIER_PROB[rarity] / (# cards of that rarity in that set)`.
Required functions:
- `rarity_counts(cards) -> {set_id: {rarity: count}}`
- `pull_rate(rarity, set_id, counts) -> float`  (per-pack probability for ONE specific card)
- `pull_cost(rarity, set_id, counts, pack_price) -> float`  ( = pack_price / pull_rate; expected $ to pull one copy)

## Sealed EV  (owned by pipeline/ev.py)
- `ev_for_set(cards_in_set, set_record, counts) -> dict`:
  `ev_per_pack = Σ over cards (pull_rate_card * market_price_card)` (skip None prices),
  `ev_per_box = ev_per_pack * packs_per_box`,
  `signal_pct = (ev_per_box - box_price)/box_price` (>0 undervalued box, <0 overvalued),
  also return `avg_loss_per_pack = pack_price - ev_per_pack`, `raw_value_per_pack = ev_per_pack`.

## Signals / features  (owned by pipeline/signals.py)
`compute_features(cards) -> {card_id: {feature: value}}` for the FEATURES in config:
- `char_premium` (0–10): rank a base_name's printings across the whole corpus by market price
  → percentile of the character's mean price, scaled 0–10. Also rank within set/rarity tier.
- `scarcity` (0–10): from pull_rate (rarer = higher) blended with months_since_release (older/out-of-print = higher).
- `pull_cost` ($): from pullrates.pull_cost (import is fine AT BUILD TIME; self-test in isolation with a stub).
- `months_since_release`: from release_date vs today.
- `set_rank` (0–1): card's market-price percentile within its set.
- `demand_pressure`, `grading_intensity`, `universal_appeal`: STUBS returning a neutral mid value
  until their feed is wired. Each must be a single function so a real feed drops in cleanly.

## Market dynamics  (owned by pipeline/market_dynamics.py + collectors/ebay.py)
- `collectors/ebay.py`: `collect_snapshot(cards) -> writes data/snapshots/ebay-<date>.json`
  mapping `card_id -> {active_listings, new_listings, ended_listings, est_sold, est_unsold, avg_price}`.
  v1 = clean STUB (no eBay key yet): write empty/neutral, but document the real eBay Browse API path
  (active listings only; estimate sold/unsold by diffing daily snapshots). Schema is the deliverable.
- `pipeline/market_dynamics.py`: `compute(card_id, ebay_snaps) -> dict` with
  `demand_pressure = est_sold / total_supply` (%), `supply_saturation = supply_7d_avg / supply_30d_avg`
  (>1 loosening, <1 tightening). Neutral fallback when no eBay history: `{demand_pressure: None,
  supply_saturation: 1.0, status: "awaiting_data"}`.

## Price model  (owned by pipeline/model.py) — his clustered regression
- Cluster cards by rarity tier. For each cluster with ≥ `config.MIN_CLUSTER_SIZE` priced cards,
  fit ridge (alpha=config.RIDGE_ALPHA) on STANDARDIZED features predicting `log(market_price)`.
  Clusters too small → use a global model. Use numpy normal equations (no sklearn).
- `fit(cards, features) -> ModelResult` exposing per card: `expected_price = exp(pred)`,
  `residual_pct = (market - expected)/expected`, `cluster`, and per-feature contribution.
- `export(path)` writes `model.json`: per cluster `{features:[...], means:[...], stds:[...],
  coef:[...], intercept}` + FEATURES display metadata, so the FRONTEND can recompute
  `expected = exp(intercept + Σ coef_i*((x_i-mean_i)/std_i))` live as sliders move.

## IQ score (0–100)  (computed in build.py)
`iq_score = 100 * weighted mean of normalized [scarcity, char_premium, set_rank, (momentum if history)]`.
This is the at-a-glance "card score"; the residual_pct is the over/under signal. Keep both.

## Build orchestrator  (pipeline/build.py) — written in the Integrate phase
fetch(cached) → pullrates/ev → signals → market_dynamics → model.fit → iq_score → write `site/data/`:
- `cards.json`: each card + `expected_price, residual_pct, iq_score, features{}, cluster, dynamics{}, image_small`
- `sets.json`: EV leaderboard rows (per set_record + ev fields)
- `leaderboard.json`: `{undervalued:[top 50 by residual_pct asc], overvalued:[top 50 desc], movers:[by saturation shift, fallback price-change]}`
- `model.json` (from model.export)
- `meta.json`: `{built_at, sets, cards, priced, sources, signal_status}`

## Frontend  (site/index.html, site/app.js, site/styles.css) — plain JS, no build step
Loads `./data/*.json`. **Look & feel MUST follow `DESIGN.md`** (Miro-inspired: white canvas,
black-pill CTAs, canary-yellow "Poke Research" wordmark, pastel feature cards, Hanken Grotesk,
pill everything). Title the site **Poke Research**. Views (hash routing):
1. **Sets / Market Trends** — EV leaderboard (best bang for buck, raw value per pack, box signal %).
2. **Price Lab** — Undervalued & Overvalued leaderboards (card image, market vs expected, premium %, IQ score).
3. **Movers** — biggest market movers (saturation shift; show "awaiting eBay data" badge for stub).
4. **Search** — filter all cards by name/set.
5. **Card detail** (modal) — image, market vs expected, premium %, IQ score, and a
   **"View Market Signals"** panel: one slider per feature (min/max from model.json metadata);
   moving a slider live-recomputes expected price from the cluster's exported coefficients,
   with a Reset button. This is the signature interactive feature — make it work client-side.

Show card images via `image_small`/`image_large` (real URLs); they may be swapped for placeholders.
Every stubbed signal must be visibly labeled "estimated / awaiting data" — never imply we have eBay/PSA feeds we don't.
