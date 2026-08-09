# Reliability Plan — how we make the predictions *actually* trustworthy

> Status: PLAN ONLY (2026-06-22). Nothing here is built. This is the roadmap for
> turning the model from "right in narrow places, hidden elsewhere" into "trustworthy
> across the catalog, with honest confidence." Reviewed before any of it ships.

## The honest problem we're solving

Today the model is reliable in a *narrow* band and we **hide** the rest:

- **Reliable:** fresh releases (walk-forward IC ~+0.26) and cheap cards.
- **Near-efficient / no edge:** mature mid-price ($20–100) — measured-dry.
- **Actively wrong:** mature *grails* (Umbreon etc.) — the cluster ridge reverts to
  the cluster center, so the priciest card always looks "overvalued." We just shipped
  a relabel that **hides** these as "no edge — chase premium the model can't price."

That relabel is *honesty*, not *reliability*. It stops us lying; it doesn't make the
call. Real reliability = the model makes a **trustworthy, calibrated** call across more
of the catalog, and we can **prove** it forward. This plan is how we get there.

## Principles (the non-negotiables)

1. **Forward validation is the only proof.** A change ships only if it improves the
   *forward* prediction log (`data/snapshots/pred-<date>.json` already records every
   day's calls). In-sample R² is not reliability. No contemporaneous fitting — that's
   the leak the reference site fell into (demand → expected price → "predicts" a move
   that already happened).
2. **Calibrated confidence, not a binary edge.** Replace hand-set gates with a
   *measured* per-card reliability score, so we show "high/med/low confidence" instead
   of silently dropping cards.
3. **Data depth is earned forward.** eBay/demand history can't be backfilled; it
   accrues from when we start. The sweep + snapshots running daily *is* the work.
4. **Honest scope beats fake coverage.** Better to say "low confidence" than to make a
   loud wrong call. The relabel stays until a validated signal replaces it.

## Phased roadmap

### Phase 0 — Data accrual (running now, free, foundational)
Everything below needs history we don't have yet. Keep these running and widen them:
- 850-card/day eBay sweep (active listings → demand/supply, gross-flow est_sold).
- Daily price snapshots → `price_history.json` (now feeding the watchlist chart).
- PSA population (only 3 cards mapped — **widen the spec map**; this is the grail lever).
- **Acceptance:** ≥30 consecutive days of same-card coverage for the top ~850 cards.

### Phase 1 — Measure reliability per segment (cheap, high-value, do first)
We have one global IC. We need to *know* where the model can be trusted.
- Extend the backtest to report IC / hit-rate **per segment** (rarity, price tier, age,
  cluster) — not one headline.
- Derive a **per-card confidence score** from that segment history and bake it onto each
  card (like `edge`, but graded 0–1, *measured* not hand-set).
- Frontend: show confidence (e.g. a high/med/low chip) instead of the binary "no edge".
  The 1.75× chase gate and the dead-zone become *outputs of the measurement*, not magic
  numbers.
- **Acceptance:** every surfaced call carries a backtest-derived confidence; "no edge"
  is a measured low-confidence, not a constant.

### Phase 2 — Validate the signals that explain the unexplained (the real fix)
The grail premium and mature-card moves need a signal the 3 features don't have:
- **Collector intensity** (PSA/CGC grading population + gem rate) — Umbreon's 19k graded
  vs a peer's 8k *is* the "this is a grail" signal. Scale the spec map (Phase 0), then
  forward-backtest: does it lift IC out-of-sample on mature/grail cards?
- **Demand pressure** (eBay sell-through) — already plumbed + as-of-gated, data-blocked.
  After ~30 days (Phase 0), forward-backtest: does demand *change* predict price *change*?
- **Gate:** a signal enters the model **only** if it beats the forward record over N weeks.
  Until then it stays descriptive (labels), never predictive.
- **Acceptance:** at least one new signal demonstrably lifts the *forward* IC on the
  segment it targets; grails get a real estimate instead of a hidden one.

### Phase 3 — Model upgrade (only after Phase 2 signals exist)
- **Hierarchical / shrinkage model** that *allows* a within-cluster premium when a
  validated signal (collector intensity) supports it — so a grail isn't forced to the
  cluster mean.
- **Uncertainty bands** — predict a *range* per card, not a point. The band width *is*
  the reliability, shown directly.
- Optional **chase-tier handling** (card-specific intercept for marquee cards) once
  collector-intensity justifies it.
- **Acceptance:** Umbreon-class cards get a calibrated estimate + band that the forward
  log supports — the relabel can be retired for cards the model can now actually price.

### Phase 4 — Sealed deals & movers (the other surfaces you named)
- **Sealed EV** currently rides TCGplayer *estimates*. Reliability needs real sold sealed
  prices (PriceCharting $40/yr gives current sold-based, incl. graded — not history).
- **Movers** is a price-fallback stub until the demand feed matures (Phase 0); once it
  does, rank by real saturation/demand shift, not the dollar-gap placeholder.

## What we deliberately are NOT doing
- No eBay sold-listings scraper (circumvents their access control; and it can't backfill
  history anyway — eBay shows ~90 days).
- No contemporaneous demand-in-model fit (the reference site's leak).
- No new model feature before it clears the forward-validation gate.

## The one-line version
**Reliability = measure where we're trustworthy (Phase 1), earn the signals that explain
the rest and prove them forward (Phase 2–3), on data that only deepens by running daily
(Phase 0).** Everything else is hiding the problem, which is all the relabel does today.
