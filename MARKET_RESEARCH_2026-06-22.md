# Market-Trend Validation — 2026-06-22

**Purpose:** Check whether our model's signal labels trend in the SAME direction as how these
sealed/single cards are ACTUALLY selling right now, and flag where we're likely wrong.

**Method:** Public market data only — TCGplayer product pages, PriceCharting / PokeData /
PokeScope / CollectorWorth aggregators, Sports Card Investor 30-day sold-anchored deltas,
CardMarket averages, and recent editorial/community trend pieces (Bleeding Cool Value Watch,
Wargamer, CardChill, SNKRDUNK). We did **not** scrape eBay sold/completed-listings pages; all
sold figures are publicly summarized. Exact dollar levels are ±~10% and small-sample-sensitive,
especially on new sets and sub-$150 cards.

> **Confidence caveat:** Several aggregator pages (PriceCharting, TCGplayer product, PokeData)
> were not machine-readable (403 / login / JS). Trend direction is cross-checked across ≥2
> independent sources per card where possible; precise magnitudes lean on Sports Card Investor's
> rolling "last 30 days" deltas, which reflect roughly May–June 2026.

---

## Summary table

| # | Card | Our signal | Real recent trend | Verdict |
|---|------|-----------|-------------------|---------|
| 1 | Umbreon ex — Prismatic Evolutions — SIR | Opportunity — dipping with firm demand | **Rising ~+19–27% / 30d** | **CONTRADICT** |
| 2 | Pikachu ex — Ascended Heroes — SIR | Quiet — no recent divergence | Flat (new set, thin) | **MATCH** (low-confidence set) |
| 3 | Mew ex — Paldean Fates — SIR | Demand building | Mildly rising (~+2% / 30d) | **PARTIAL MATCH** |
| 4 | Mega Charizard Y ex — Ascended Heroes — Mega Hyper Rare | Quiet — no recent divergence | Falling ~−7% to −14% / 30d | **PARTIAL MATCH → leans CONTRADICT** |
| 5 | Charizard ex — 151 — SIR | Easing | Flat-to-down ~−5% / 30d after big run | **MATCH** |
| 6 | Pikachu ex — Surging Sparks — SIR | Rising — no clear market driver | Falling ~−4.5% / 30d | **CONTRADICT** |
| 7 | Charizard ex — Paldean Fates — SIR | Quiet — no recent divergence | Flat (raw) | **MATCH** (trend); price level high |
| 8 | Pikachu — 151 — Illustration Rare | Demand building | Rising ~+6.7% / 30d | **MATCH** |

**Scorecard:** 4 MATCH, 1 PARTIAL MATCH, 1 PARTIAL→CONTRADICT, 2 CONTRADICT.
Net: the labeling is directionally right on the cheaper/quieter cards but **wrong on the two
biggest "story" calls** (Umbreon and Surging Sparks Pikachu), in both cases because a stale/high
price anchor drove the signal rather than recent sold momentum.

---

## Card-by-card

### 1. Umbreon ex — Prismatic Evolutions — Special Illustration Rare (#161/131)
- **Our model:** market $1,523, expected $191, signal **"Opportunity — dipping with firm demand."**
- **Current price:** ~$1,500–$1,575 raw NM; recent sold $1,575 (6/21) and $1,685 (LP). Most
  valuable card in the set.
- **Trend (30d):** **RISING, ~+19% to +27%.** Sports Card Investor showed +18.7% on one read and
  **+$358 / +26.9% (last sold $1,685)** on another — the latter figure surfaced independently in a
  second search, so the direction is well-confirmed. Pattern: dipped below ~$1,000 in Jan 2026,
  recovered, and is now climbing through Q2.
- **Driver:** Renewed demand for the set's flagship chase Eeveelution after the early-2026
  correction.
- **Confidence:** High on direction; medium on magnitude (100%+ volatility flag).
- **Verdict: CONTRADICT.** "Firm demand" is correct, but the card is **rising hard, not dipping.**
  The "dipping" read looks stale — it echoes the January correction, not June momentum. (Separately,
  the $191 expected value is wildly below a $1,500 market — the regression is not modeling this card
  at all.)

### 2. Pikachu ex — Ascended Heroes — Special Illustration Rare (#276/217)
- **Our model:** market $1,368, signal **"Quiet — no recent divergence."**
- **Set status:** **Ascended Heroes is REAL, not presale** — full name *Mega Evolution — Ascended
  Heroes*, released **Jan 30, 2026** (~5 months old). Singles are thin and volatile; sealed product
  is down sharply from launch.
- **Current price:** ~$1,300–$1,370 raw NM (TCGplayer market ~$1,308–$1,328). **Dual-SIR trap:**
  there are two Pikachu ex SIRs — **#276 (~$1,300+, matches our $1,368)** and #277 (~$465). Confirm
  the model is pinned to #276.
- **Trend (30d):** **FLAT** — SCI last sale $840 (LP) "no change in 30 days"; NM comps cluster
  $1,200–$1,270.
- **Driver:** New set still settling post-launch.
- **Confidence:** Medium — only ~5 months of data, wide LP/NM spread adds noise. **Low-confidence by
  set age, as expected.**
- **Verdict: MATCH.** Flat / no recent divergence is confirmed. Treat as low-confidence given thin
  data.

### 3. Mew ex ("Bubble Mew") — Paldean Fates — Special Illustration Rare (#232/091)
- **Our model:** market $1,027, signal **"Demand building."**
- **Current price:** Mixed by source/condition. TCGplayer NM ~$1,000–$1,030; CollectorWorth
  "ungraded" $709 (condition-averaged, runs lower than NM-only). Recent ungraded comps ~$695–$769.
- **Trend (30–90d):** **Mildly rising.** CollectorWorth ungraded **+2.29% / 30d**; multi-month arc
  is a steady climb ($90 → $600+ → $1,000+ over the past year). One SCI 30-day datapoint was flat
  *and* stale (last sale March 2026), so the *acute* recent acceleration is softer than the
  long-term story.
- **Driver:** Special-set scarcity (Paldean Fates production wound down) + durable "Bubble Mew" art
  demand; classic slow-burn.
- **Confidence:** Medium-low on freshness of the near-term signal.
- **Verdict: PARTIAL MATCH.** Direction is right (demand genuinely building, mildly up), but the
  acceleration is gentle (~+2%), not a fresh surge — and our $1,027 sits at the top of the range
  vs ~$709 ungraded / ~$1,000 NM.

### 4. Mega Charizard Y ex — Ascended Heroes — Mega Hyper Rare (#294/217)
- **Our model:** market $626, expected $487, signal **"Quiet — no recent divergence."**
- **Current price:** ~$626–$665 raw (TCGplayer/PokeInvest ~$649–$665); LP comps as low as $465.
- **Trend (30d):** **FALLING, ~−7% to −14%.** Card-Codex raw −7.23% (from ~$675); SCI LP
  −$75 / −13.9% (last sale $465, 6/4). Two independent sources agree on direction.
- **Driver:** New-set cooldown — Ascended Heroes singles broadly softening ~5 months post-release as
  supply settles, despite a very low pull rate.
- **Confidence:** Medium; magnitude varies by condition grade; thin/volatile new set.
- **Verdict: PARTIAL MATCH → leans CONTRADICT.** It is **not "quiet"** — there's a real, measurable
  ~−10% 30-day slide. The model is understating a downward divergence. Magnitude is modest and
  condition-dependent, so not a clean contradiction, but the label is wrong in spirit.

### 5. Charizard ex — 151 — Special Illustration Rare (#199/165)
- **Our model:** market $461, expected $282, signal **"Easing."**
- **Current price:** ~$390–$415 raw NM (recent sold ~$393). Our $461 = PokeScope high-end "market,"
  above transactable sold price.
- **Trend (30d):** **Flat-to-falling, ~−5%.** SCI ~−4.7% / −$19; ran up hard Jan→Mar
  ($259 → $294 → $416) then stalled/ticked down post-rotation.
- **Driver:** Standard rotation (G mark, **April 10, 2026**, rotated 151 out) + 30th-anniversary
  nostalgia + sealed scarcity drove the spike; momentum now exhausted at high price.
- **Confidence:** Medium-high — multiple sources agree the parabolic run topped out.
- **Verdict: MATCH.** Flat-to-down after a big run is exactly "easing." Note our $461 market reads
  high vs ~$393 sold, which is consistent with our own model's gap to its $282 fair value.

### 6. Pikachu ex — Surging Sparks — Special Illustration Rare (#238/191)
- **Our model:** market $384, expected $368, signal **"Rising — no clear market driver."**
- **Current price:** ~$315–$330 raw NM (SCI last sold $327.79; PokeInvest live ~$315). Our $384 =
  PokeScope high-end "market," ~$50+ above recent sold.
- **Trend (30d):** **FALLING, ~−4.5%.** SCI −$15.55 / −4.5% (last sold $327.79); CardMarket 7-day
  avg (€277) below 30-day avg (€287) — corroborates the downtrend. Down materially from the ~$489
  release peak. Bleeding Cool (March) had the set "mostly static."
- **Driver:** No positive catalyst — still Standard-legal (not rotation-driven), set aging, ample
  supply. Gentle post-hype bleed.
- **Confidence:** Medium-high that it is NOT rising.
- **Verdict: CONTRADICT.** Sold data shows it flat-to-down ~4–5%, not rising. **"Rising — no clear
  driver" is almost certainly a high-anchor artifact** (model reads PokeScope $384 vs ~$328 sold),
  not a real uptrend. This is the weakest signal in the set — flag for review.

### 7. Charizard ex — Paldean Fates — Special Illustration Rare (#234/091)
- **Our model:** market $337, signal **"Quiet — no recent divergence."**
- **Current price:** ~$220–$263 raw NM (recent raw sold ~$217; retail/Value Watch ~$236–$263). Our
  $337 sits well above current raw market — likely stale or graded-influenced.
- **Trend (30d):** **FLAT (raw)** — SCI no change over 30 days. Choppy over the year
  ($314 Oct → $220 Jan → $263 Mar). PSA 10 copies up ~+31% / 30d (graded-only strength, not raw).
- **Driver:** Aging set, partial rotation exposure, no catalyst on raw singles; graded is the only
  active pocket.
- **Confidence:** Medium — "flat raw" well-supported; the $337 level could not be verified.
- **Verdict: MATCH on trend (quiet/flat).** But the **price level is questionable** — real raw
  market is ~$220–$263, not $337. Trend label fine; level likely stale/high.

### 8. Pikachu — 151 — Illustration Rare (#173/165)
- **Our model:** market $105, signal **"Demand building."**
- **Current price:** ~$84–$95 raw NM (SCI last sold $87.09). Our $105 = PokeScope high-end.
- **Trend (30d):** **RISING (mild), ~+6.7%.** SCI +$5.49 / +6.7%; Bleeding Cool (March) +$40 that
  month; Japanese version up +16% / 30d.
- **Driver:** 151 nostalgia/rotation/anniversary tailwind; cheap chase IR riding the Charizard halo.
- **Confidence:** Medium — small absolute moves, some noise, but sources agree direction is up.
- **Verdict: MATCH.** Mild appreciation confirmed. Directionally correct; $105 sits ~top of range
  vs ~$87 sold.

---

## Overall read: is the model trending right or wrong?

**Mostly right on the quiet/cheap cards, wrong on the two highest-visibility calls.** 4 clean
matches plus 2 partials means the *direction* of most labels is defensible. But the two outright
contradictions are the ones that matter most for user trust:

- **Umbreon ex (CONTRADICT):** we say "dipping," the market is up ~20–27% in 30 days. We're calling
  a buy-the-dip on a card that's ripping upward.
- **Pikachu ex Surging Sparks (CONTRADICT):** we say "rising," the market is down ~4.5%. We're
  flagging momentum that doesn't exist.

Both errors share one root cause, visible across the whole set: **our "market price" is anchored to
a high-end estimate (PokeScope / TCGplayer "market"), which on the verified cards runs $30–$60+
above recent *sold* prices.** That high anchor manufactures phantom "rising"/"opportunity" signals
and lags real turning points.

### Top 3 things that would most improve accuracy

1. **Anchor signals to sold-data, not "market" estimates.** Drive trend labels off a sold-anchored
   feed (Sports Card Investor-style 30-day deltas, CardMarket 7-day vs 30-day avg, or PriceCharting
   sold) rather than PokeScope/TCGplayer "market." This single change would have flipped both
   contradictions (Umbreon, Surging Sparks Pikachu) and corrected the high price levels on cards
   5–8.
2. **Use a fresh, short trend window and reject stale comps.** Umbreon's "dipping" echoes the Jan
   correction; Mew's flat read came off a March last-sale. Require the trend window's last verified
   sale to be recent (e.g. ≤30 days) or downgrade the signal's confidence and stop emitting
   directional labels off stale data.
3. **Fix the expected-value model on chase SIRs and surface set-age confidence.** Umbreon expected
   $191 vs $1,500 market shows the cluster regression doesn't fit top-tier SIRs — these need their
   own tier/treatment or they'll perpetually mislabel "opportunity." Separately, explicitly mark
   Ascended Heroes (#2, #4) as low-confidence/thin so "Quiet" isn't read as a confident call on a
   5-month-old set (where #4 is actually sliding ~−10%).

### Secondary fixes
- **Dual-SIR disambiguation:** Pikachu ex Ascended Heroes has #276 (~$1,300) and #277 (~$465); pin
  the right variant.
- **Separate raw vs graded trends:** Paldean Fates Charizard (#7) is flat raw but PSA 10 up ~+31% —
  don't let graded momentum contaminate a raw-card signal (or vice versa).

---

## Sources
- Umbreon #161 — Sports Card Investor: https://www.sportscardinvestor.com/cards/umbreon-ex-pokemon/2025-scarlet-violet-prismatic-evolutions-special-illustration-rare-161-131
- Umbreon Jan-2026 dip context — Wargamer: https://www.wargamer.com/pokemon-trading-card-game/prismatic-evolutions-umbreon-card-price
- Pikachu ex #276 — Sports Card Investor: https://www.sportscardinvestor.com/cards/pikachu-ex-pokemon/2026-mega-evolution-ascended-heroes-special-illustration-rare-276-217
- Ascended Heroes release — Pokemon.com: https://www.pokemon.com/us/pokemon-news/get-the-new-pokemon-tcg-expansion-mega-evolution-ascended-heroes-on-january-30-2026
- Mew ex #232 — CollectorWorth: https://collectorworth.com/cards/mew-ex-pokemon-paldean-fates/
- Mew ex #232 — Sports Card Investor: https://www.sportscardinvestor.com/cards/mew-ex-pokemon/2024-scarlet-violet-paldean-fates-special-illustration-rare-232-091
- Bubble Mew 1-year — Wargamer: https://www.wargamer.com/pokemon-trading-card-game/paldean-fates-bubble-mew-one-year
- M Charizard Y ex #294 — Sports Card Investor: https://www.sportscardinvestor.com/cards/mega-charizard-y-ex-pokemon/2026-mega-evolution-ascended-heroes-mega-hyper-rare-secret-294-217
- M Charizard Y ex #294 — Card-Codex: https://cardcodex.com/pokemon/mega-evolution/ascended-heroes/mega-charizard-y-ex-294-217-mega-hyper-rare/
- Charizard ex 151 #199 — Sports Card Investor: https://www.sportscardinvestor.com/cards/charizard-ex-pokemon/2023-scarlet-violet-151-special-illustration-rare-199-165
- Pikachu ex Surging Sparks #238 — Sports Card Investor: https://www.sportscardinvestor.com/cards/pikachu-ex-pokemon/2024-scarlet-violet-surging-sparks-special-illustration-rare-238-191
- Charizard ex Paldean Fates #234 — Sports Card Investor: https://www.sportscardinvestor.com/cards/charizard-ex-pokemon/2024-scarlet-violet-paldean-fates-special-illustration-rare-234-091
- Pikachu 151 #173 — Sports Card Investor: https://www.sportscardinvestor.com/cards/pikachu-pokemon/2023-scarlet-violet-151-illustration-rare-173-165
- 151 rotation/sealed context — CardChill: https://cardchill.com/article/how-the-2026-pokemon-tcg-rotation-aftermath-is-already-moving-sealed-product-prices-scarlet-violet-151-spikes
- 151 market watch — SNKRDUNK: https://snkrdunk.com/en/magazine/2026/04/08/pokemon-card-151-market-watch-april-2026-is-the-gen-1-masterpiece-headed-for-six-figures/
- Value Watch (Mar 2026) — Bleeding Cool 151 / Surging Sparks / Paldean Fates:
  https://bleedingcool.com/games/pokemon-tcg-value-watch-scarlet-violet-151-in-march-2026/ ·
  https://bleedingcool.com/games/pokemon-tcg-value-watch-surging-sparks-in-march-2026/ ·
  https://bleedingcool.com/games/pokemon-tcg-value-watch-paldean-fates-in-march-2026/
- PokeScope card pages (noted as likely model feed; high-end "market"): https://pokescope.app/card/sv8pt5-161/ · /sv4pt5-232/ · /sv8-238/ · /sv3pt5-199/ · /sv3pt5-173/

**Limitations:** PriceCharting, PokeData, and TCGplayer product pages were not directly machine-
readable (403 / login / JS); their figures came via search summaries. No eBay sold-listings pages
were scraped. Some SCI comps are condition-specific (LP/MP vs NM) and a few editorial pieces are
March/April-dated, supplemented with SCI rolling 30-day deltas current to ~May–June 2026. Treat
exact dollar levels as ±10% and small-sample-sensitive, especially cards 2, 4, 7, and 8.
