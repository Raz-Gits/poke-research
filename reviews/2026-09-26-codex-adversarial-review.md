# Codex adversarial review, 2026-09-26

- **Reviewer:** Codex (OpenAI) CLI 0.153.0-alpha.5 (model gpt-5.6-sol, reasoning effort medium, per the run log)
- **Sandbox:** read-only
- **Run:** 2026-09-26, against `origin/main` at `8f25b49` ("data: daily refresh 2026-09-25")
- **Prompt (exact):**

> Do an adversarial review of this repository. It is a public Pokemon TCG analytics project: a daily GitHub Action pulls prices (eBay Browse API and other collectors), a clustered ridge model flags under- and overvalued cards and estimates sealed-product EV, and a static site on Netlify publishes the results. Assume real people read the site and may buy or sell cards based on it. Find what can go wrong: wrong or stale numbers published without anyone noticing, a daily run that fails silently or half-succeeds, API keys or secrets leaking into logs or the repo, quota or rate-limit burn, data corruption from the Action's own pushes, model results presented as more certain than they are (for example in-sample fit shown as accuracy, leakage, tiny samples), untested paths, anything in the README or site that the code does not back up. For each finding give the file and line, what can go wrong, why the code allows it, the likely impact, a concrete fix, and your confidence from 0 to 1. Start with a verdict: SHIP, FIX_THEN_SHIP or NO-SHIP. Do not modify any files. Output the full review in Markdown as your final message.

Codex's text below is verbatim; only its file links were changed from local paths to repo-relative ones.

Line numbers in those links point at `8f25b49`, the commit it reviewed. My decisions, with the commits that carry them out, follow the review.

---

# Adversarial repository review

## Verdict: **FIX_THEN_SHIP**

The project should not currently present its outputs as daily-fresh, live valuation guidance. The main blockers are:

- A failed price pull can still produce a successful deployment stamped with today’s date.
- eBay request failures can be recorded as zero listings, creating false “sold” demand.
- The advertised production-gated backtest does not reproduce the production gate.
- Sealed prices from June are labeled live in September.
- The deal monitor labeled “live” is roughly seven weeks stale.
- Several model and pull-rate claims are more confident than the implementation supports.

The underlying architecture is salvageable, but these should be fixed before encouraging real buying or selling decisions.

---

## Findings

### 1. Critical — A failed price pull is published as a successful fresh update

**File/line:** [.github/workflows/daily-refresh.yml:35](../.github/workflows/daily-refresh.yml#L35), [pipeline/fetch.py:217](../pipeline/fetch.py#L217), [pipeline/build.py:548](../pipeline/build.py#L548), [docs/app.js:46](../docs/app.js#L46)

**What can go wrong:** An upstream outage, expired key, schema change, or total price-fetch failure leaves old prices in place, but the build stamps `built_at` with the current time and the site says “Prices refreshed Today.”

**Why allowed:** The workflow marks `pipeline.fetch` `continue-on-error`. Independently, a total failure with cached data makes `fetch.main()` return successfully. `build.py` then uses the current clock for `built_at`; the frontend treats that build time as price freshness.

**Likely impact:** Users can buy or sell against stale prices without any visible warning. The Action and Netlify deployment may both appear healthy.

**Concrete fix:** Make price acquisition produce a manifest containing upstream timestamp, sets attempted/succeeded/carried, card coverage, and maximum price age. Fail publication when no fresh source succeeded or coverage/freshness falls outside a declared threshold. Publish separate `build_at` and `prices_as_of` fields, and base all frontend freshness messaging on `prices_as_of`.

**Confidence:** 1.00

---

### 2. Critical — eBay API errors become zero listings and can fabricate a demand spike

**File/line:** [collectors/ebay.py:289](../collectors/ebay.py#L289), [collectors/ebay.py:321](../collectors/ebay.py#L321), [collectors/ebay.py:361](../collectors/ebay.py#L361), [collectors/ebay.py:432](../collectors/ebay.py#L432)

**What can go wrong:** A timeout, 5xx, non-429 HTTP error, or malformed response can appear downstream as a successful observation of zero active listings. Compared with yesterday, all prior listings then look “ended,” and approximately 35–85% can be counted as estimated sales.

**Why allowed:** `_browse_request()` returns `None` on errors. `_fetch_card_market()` breaks its loop but still creates a row with `active_listings = len([])`, i.e. zero, rather than an unknown value. `diff_row()` treats that zero as real and infers ended listings and sales.

**Likely impact:** False demand-pressure and “heating up” signals on exactly the day the upstream API is unhealthy. This is materially worse than missing data because it manufactures a directional market signal.

**Concrete fix:** Return a typed outcome such as `{status: "ok"|"empty"|"error", rows: ...}`. Only a successful HTTP response with valid schema may produce zero listings. Error rows must carry `active_listings: null`, must not be diffed, and must not update history. Fail or quarantine the entire snapshot if successful coverage drops below a threshold.

**Confidence:** 1.00

---

### 3. High — Partial eBay snapshots are accepted as complete and cannot be repaired by a same-day rerun

**File/line:** [collectors/ebay.py:530](../collectors/ebay.py#L530), [pipeline/build.py:393](../pipeline/build.py#L393)

**What can go wrong:** The sweep may stop after a timeout, quota problem, or 30 consecutive failures. If even one row has a positive listing count, `_snapshot_is_live()` considers the whole file live and a retry skips collection.

**Why allowed:** Snapshot validity is `any(active_listings)`, not a coverage or completeness check. The collector writes partial output as its normal successful result and does not persist an explicit completion status.

**Likely impact:** Some cards update while others silently retain unknown or distorted dynamics. The workflow still commits and publishes the mixed-quality snapshot.

**Concrete fix:** Add snapshot metadata: requested cards, successful responses, errors by class, elapsed time, calls, abort reason, and completion status. Require a high successful-coverage percentage and the expected universe identity before using or preserving a snapshot. Allow reruns to fill missing rows.

**Confidence:** 0.99

---

### 4. High — A sidecar failure can commit raw eBay item IDs publicly

**File/line:** [.github/workflows/daily-refresh.yml:64](../.github/workflows/daily-refresh.yml#L64), [.github/workflows/daily-refresh.yml:75](../.github/workflows/daily-refresh.yml#L75), [scripts/ebay_ids_sidecar.py:97](../scripts/ebay_ids_sidecar.py#L97)

**What can go wrong:** If the `stash` step crashes after collection, the workflow continues and stages every snapshot, including the raw `item_ids`.

**Why allowed:** The privacy/sanitization step is `continue-on-error: true`; the commit step has no assertion that `item_ids` are absent.

**Likely impact:** Raw listing identifiers enter permanent public Git history. The README’s statement that IDs are not committed is not enforced.

**Concrete fix:** Make sanitization mandatory. Add a separate fail-closed validation that recursively rejects any staged `item_ids` key before `git commit`. Write a sanitized publication tree rather than destructively rewriting the collector’s source snapshots. Do not claim one-day cache retention unless an explicit deletion policy enforces it.

**Confidence:** 1.00

---

### 5. High — A failed-set cache problem can silently shrink the catalog

**File/line:** [pipeline/fetch.py:155](../pipeline/fetch.py#L155), [pipeline/fetch.py:203](../pipeline/fetch.py#L203), [pipeline/fetch.py:224](../pipeline/fetch.py#L224)

**What can go wrong:** If several sets fetch successfully but a failed set cannot be read from the normalized cache, `all_cards` remains nonempty and the reduced catalog overwrites the prior complete files.

**Why allowed:** Failure to load cached fallback data is only printed. The “do not clobber” guard applies solely when *all* cards are missing. There is no required-set or cardinality invariant.

**Likely impact:** Cards and sets disappear, historical series truncate, cluster composition changes, and model/EV results shift for reasons unrelated to the market.

**Concrete fix:** Build into temporary files and validate exact configured set coverage, unique IDs, minimum per-set counts, price coverage, and bounded day-over-day cardinality changes. If any failed set cannot be carried, exit nonzero and retain the last known-good dataset.

**Confidence:** 0.99

---

### 6. High — The published “what the site surfaces” backtest does not test what the site surfaces

**File/line:** [pipeline/build.py:174](../pipeline/build.py#L174), [pipeline/backtest.py:241](../pipeline/backtest.py#L241), [docs/data/backtest.json:41](../docs/data/backtest.json#L41)

**What can go wrong:** The site advertises a surfaced-universe IC of `0.1336` as the “honest headline,” but production removes both mature mid-price cards and mature chase-premium cards. The backtest removes only the mid-price zone.

**Why allowed:** Production `_edge()` applies `CHASE_PREMIUM_MULT`; backtest `_is_surfaced()` does not. The backtest note nevertheless claims it represents what users actually see.

**Likely impact:** The main evidence offered to users does not evaluate the actual decision rule. The reported result may improve or deteriorate when the omitted gate is reproduced.

**Concrete fix:** Put the gate in one pure shared function used by build and backtest. Backtest the ±15% call band and exact leaderboard selection as well. Add a regression test proving historical and production gate decisions match on identical rows.

**Confidence:** 1.00

---

### 7. High — The production gate was selected on the same backtest used to advertise it

**File/line:** [pipeline/config.py:114](../pipeline/config.py#L114), [pipeline/backtest.py:317](../pipeline/backtest.py#L317)

**What can go wrong:** The `$20–$100` dead zone, fresh-card cutoff, price floor, feature set, and chase treatment were chosen after examining this historical panel. The same panel then supplies the headline significance.

**Why allowed:** There is no train/tune/test separation, nested walk-forward selection, or untouched holdout period. HAC corrects overlapping observations but does not correct strategy-selection bias or repeated experiments.

**Likely impact:** The `t=8.29` surfaced result is optimistic and cannot be treated as confirmatory evidence. A new period may perform substantially worse.

**Concrete fix:** Freeze all rules, then evaluate on an untouched forward period. Better, use nested walk-forward evaluation where thresholds/features are selected only on data preceding each test block. Report how many formulas and gates were tried and distinguish exploratory from confirmatory metrics.

**Confidence:** 0.98

---

### 8. High — Months-old sealed prices are labeled “live” and drive actionable EV verdicts

**File/line:** [data/sealed_market.json:2](../data/sealed_market.json#L2), [pipeline/sealed_market.py:65](../pipeline/sealed_market.py#L65), [docs/app.js:444](../docs/app.js#L444)

**What can go wrong:** The published build is dated 2026-09-25, but the manual sealed-price feed is dated 2026-06-18. The UI labels the page `live · pokemontcg.io` and describes verdicts as “good to rip / hold” or “buy singles.”

**Why allowed:** `sealed_market.load()` reads `as_of` but never rejects or visibly flags stale data. The build overlays the old pack and ETB prices unconditionally.

**Likely impact:** EV percentages can be wrong by large amounts in a volatile sealed market, directly changing the ranking and verdict.

**Concrete fix:** Automate sealed-price acquisition or remove the “live” claim. Carry source and `as_of` into every set record, visibly show age, and suppress the verdict after a short freshness SLA. Separate card-price freshness from sealed-price freshness.

**Confidence:** 1.00

---

### 9. High — The pull-rate sourcing claim contradicts the configured inputs

**File/line:** [pipeline/pullrates.py:38](../pipeline/pullrates.py#L38), [pipeline/pullrates.py:105](../pipeline/pullrates.py#L105), [docs/app.js:455](../docs/app.js#L455)

**What can go wrong:** The site says rates come from large samples, while the configuration contains explicit estimates, placeholders and provisional rates, including ACE SPEC, newer Hyper Rare values, and Mega-era tiers.

**Why allowed:** All tier probabilities feed the same EV computation with no provenance or uncertainty field. The frontend offers only two ETB-price caveats and does not identify provisional pull rates.

**Likely impact:** A single uncertain chase probability can dominate pack EV. Users cannot distinguish well-supported sets from speculative ones.

**Concrete fix:** Represent each rate as `{estimate, sample_n, source_url, observed_period, confidence_interval, status}`. Suppress or visibly downgrade EV when key tiers are provisional. Propagate uncertainty through Monte Carlo or analytical bounds and publish an EV interval rather than only a point value.

**Confidence:** 1.00

---

### 10. Medium — “R²” is calculated as squared correlation, not coefficient of determination

**File/line:** [pipeline/model.py:214](../pipeline/model.py#L214), [README.md:22](../README.md#L22)

**What can go wrong:** A prediction can have strong correlation with actual prices while being systematically too high or too low. Squaring correlation ignores that calibration error but is published as `R²(log)`.

**Why allowed:** `r2_log()` returns `corr(log actual, log predicted)²`; standard \(R²\) is \(1-\text{SSE}/\text{SST}\).

**Likely impact:** The displayed `0.90` looks like 90% explained variance even though it is a different, more forgiving statistic. It is also in-sample.

**Concrete fix:** Rename the existing metric `squared_log_correlation`, and calculate conventional \(R²\), MAE/RMSE in log and dollar space, calibration slope/intercept, and out-of-sample versions. Do not use the in-sample number as evidence of valuation accuracy.

**Confidence:** 1.00

---

### 11. Medium — Thin clusters and log retransformation are presented as precise “fair prices”

**File/line:** [pipeline/config.py:81](../pipeline/config.py#L81), [pipeline/model.py:400](../pipeline/model.py#L400), [docs/data/model.json:410](../docs/data/model.json#L410), [docs/app.js:495](../docs/app.js#L495)

**What can go wrong:** Some cluster models have only 12 or 13 observations for three features plus an intercept. Their point predictions receive the same “fair price” treatment as clusters with hundreds of cards. In addition, `exp(predicted_log)` estimates a conditional median under common log-error assumptions, not an unbiased arithmetic expected price.

**Why allowed:** Twelve rows are enough to activate a standalone cluster. No cross-validation, residual dispersion, prediction interval, shrinkage uncertainty, or smearing correction is exported or displayed.

**Likely impact:** Large, unstable valuation gaps can look precise and actionable, especially in rare categories where prices and samples are most volatile.

**Concrete fix:** Use hierarchical/partial pooling or a materially higher evidence threshold. Estimate cluster-specific out-of-sample error, apply a justified retransformation correction when calling the result an expected price, and display prediction intervals plus sample size. Suppress directional calls whose intervals overlap the market price.

**Confidence:** 0.96

---

### 12. High — The “live eBay” deal monitor is currently weeks stale

**File/line:** [docs/data/watchlist.json:2](../docs/data/watchlist.json#L2), [docs/app.js:1039](../docs/app.js#L1039), [docs/app.js:1083](../docs/app.js#L1083)

**What can go wrong:** The artifact is dated 2026-08-09 while the main build is dated 2026-09-25. The page still displays `live · eBay` and describes real-time phone alerts.

**Why allowed:** The daily workflow does not generate the watchlist. The frontend displays the timestamp but has no age threshold, warning state, or automatic suppression. Its Refresh button only redownloads the same deployed file and reports “Up to date” if unchanged.

**Likely impact:** Users can click expired deals or infer current market floors from data roughly seven weeks old.

**Concrete fix:** Either wire the monitor into a reliable publication path or remove it from the deployed site. Add strict stale-state UI: after minutes/hours, replace “live” with an age warning; after a larger threshold, hide listings entirely. Make “Refresh” distinguish “download succeeded” from “source data is fresh.”

**Confidence:** 1.00

---

### 13. High — Unpinned dependencies run with production secrets available

**File/line:** [requirements.txt:3](../requirements.txt#L3), [.github/workflows/daily-refresh.yml:32](../.github/workflows/daily-refresh.yml#L32), [.github/workflows/daily-refresh.yml:54](../.github/workflows/daily-refresh.yml#L54)

**What can go wrong:** A compromised or unexpectedly incompatible future `numpy`/`py7zr` release is installed automatically. Imported Python code then runs in a step containing the eBay client secret and in a job with repository write permission.

**Why allowed:** Requirements have neither versions nor hashes. Actions use movable major-version tags rather than commit SHAs.

**Likely impact:** At minimum, an unreviewed update can break or change daily model output. At worst, supply-chain code can exfiltrate API credentials or abuse the workflow token.

**Concrete fix:** Lock exact dependency versions with hashes, update them through reviewed automation, and pin Actions to commit SHAs. Minimize secret scope and permissions; split collection from publication if practical.

**Confidence:** 0.98

---

### 14. Medium — There is no CI quality gate or deployed-site verification

**File/line:** [.github/workflows/daily-refresh.yml:32](../.github/workflows/daily-refresh.yml#L32), [.github/workflows/daily-refresh.yml:71](../.github/workflows/daily-refresh.yml#L71)

**What can go wrong:** Schema drift, impossible prices, collapsed coverage, stale timestamps, sidecar leakage, model explosions, or broken frontend data can be committed without tests. A successful Git push is treated as success even if Netlify never deploys or serves an older commit.

**Why allowed:** The workflow goes from dependency installation directly to fetch/build/commit. It runs neither the existing tests nor a publication validator, and it never checks the Netlify deployment or public freshness marker. `pytest` is not even declared as a dependency.

**Likely impact:** Most preceding failures can reach production unnoticed. A non-fast-forward push after the long eBay sweep also burns quota without publishing, with no retry or explicit alerting.

**Concrete fix:** Add:

- unit and integration tests;
- JSON/schema validation;
- coverage and freshness thresholds;
- finite/range checks for all prices, EVs and predictions;
- an assertion that no raw IDs or secrets are staged;
- a generated-data smoke test;
- deployment-status polling and a public-site freshness check;
- explicit failure notifications.

**Confidence:** 1.00

---

### 15. Medium — Source and methodology disclosures contradict the running system

**File/line:** [pipeline/build.py:557](../pipeline/build.py#L557), [docs/data/meta.json:10](../docs/data/meta.json#L10), [docs/app.js:365](../docs/app.js#L365), [docs/index.html:84](../docs/index.html#L84)

**What can go wrong:** `meta.json`, the home-page explainer and footer say eBay is awaiting data even though the repository contains daily live snapshots and the README says the feed is live. The site also says the model uses in-set rank, but `config.FEATURES` excludes it.

**Why allowed:** Data-source metadata and explanatory copy are hard-coded rather than derived from the completed run and exported model.

**Likely impact:** Users cannot tell which inputs are live, stale, display-only, or actually included in predictions. That undermines every confidence disclaimer.

**Concrete fix:** Generate source status from the run manifest and exported model. Include per-source `status`, `as_of`, coverage and failure reason. Render model features directly from `model.json`; remove static methodology claims that can drift from code.

**Confidence:** 1.00

---

## Additional observed stale data

The current normalized catalog includes individual source timestamps from 2025—for example N’s Reshiram at [data/normalized/cards.json:31841](../data/normalized/cards.json#L31841)—but the UI does not expose per-card freshness. Even if the old timestamp represents a legitimately unchanged source row, it should not inherit the global “refreshed today” claim without disclosure.

## Verification notes

- No files were modified; the worktree remained clean.
- All 309 JSON files under the generated/public data paths parsed successfully.
- The current artifacts contain 2,937 cards, 2,936 priced cards, and 807 rows in the latest eBay snapshot.
- The backtest artifact ends on 2026-06-11 while the current build is dated 2026-09-25; the daily workflow does not regenerate it.
- I could not execute the Python tests because this review environment has no `python`, `python3`, or `py` executable. Static inspection found only two focused test modules, covering historical as-of gating and signal labels; none cover fetch failure, partial publication, eBay error semantics, sidecar sanitization, model metrics, EV, workflow behavior, or frontend freshness.

---

## My decisions (Raz Sela, 2026-09-26)

| # | Finding (short) | Decision | Commit(s) |
|---|---|---|---|
| 1 | Failed price pull published as fresh | Partly fixed | `9705045`, `377f8de` |
| 2 | eBay errors become zero listings | Fixed (completed in the verification pass) | `f4c6950`, `0c775d1`, `92a66cb`, `6044b83` |
| 3 | Partial eBay snapshots accepted as complete | Deferred | none |
| 4 | Sidecar failure can commit raw item IDs | Fixed | `69f8115` |
| 5 | Failed-set cache problem can shrink the catalog | Deferred | none |
| 6 | Backtest does not test what the site surfaces | Labeled now, fix later | `019dedb`, `e2bef5e` |
| 7 | Gate selected on the same backtest that advertises it | Labeled now, fix later | `019dedb`, `e2bef5e` |
| 8 | Months-old sealed prices labeled "live" | Partly fixed | `28dc553`, `377f8de`, `e7db31d` |
| 9 | Pull-rate sourcing claim contradicts the inputs | Labeled now, fix later | `019dedb` |
| 10 | "R²" is squared correlation | Fixed | `b34bc47` |
| 11 | Thin clusters shown as precise fair prices | Labeled now, fix later | `019dedb` |
| 12 | "Live eBay" deal monitor is weeks stale | Partly fixed | `06835b7`, `377f8de` |
| 13 | Unpinned dependencies run with secrets | Deferred | none |
| 14 | No CI quality gate or deploy check | Deferred | none (one check added under 4) |
| 15 | Disclosures contradict the running system | Fixed (completed in the verification pass) | `855dba5`, `0e6f3ce` |
| + | Per-card stale price dates | Deferred | none |

### 1. A failed price pull is published as a successful fresh update

**Decision:** Partly fixed.

**Commit:** `9705045`, follow-up `377f8de`

**Why:** The build running on cached prices after a failed fetch is on purpose: a pokemontcg.io outage should not also cost me the day's eBay sweep, and the workflow comment says exactly that. What was wrong is that the site used the build clock as the price clock, so a day with no new prices still said "Prices refreshed Today". The minimum honest fix is to publish the two times separately and let only a real price fetch move the price date. I picked a strict rule for "real": `prices_as_of` moves only when every configured set came back live with at least one priced card. That makes it a true lower bound (every price on the site is at least that fresh), which a "some sets worked" rule would not give me. The stronger fix Codex describes (a manifest with coverage thresholds that refuses to publish) changes when the site publishes at all, and I want to decide that on its own rather than bundle it into a labeling fix.

**How:** `pipeline/fetch.py` now writes `data/normalized/price_fetch.json` after every attempt, including the total-outage early return; `next_price_status()` is the pure rule, and the record also lists which sets were not live. `pipeline/build.py` publishes `prices_as_of` next to `built_at` in `meta.json`. In `docs/app.js`, the home stat card and footer say "Prices refreshed" only from `prices_as_of`; data without the field (everything published before this change) shows "Site built" with the build date and makes no claim about the prices. The headless check then showed "Site built: Today, on 2026-09-25" for an evening build, because the relative label counted 24-hour windows (the old card had the same mismatch), so `377f8de` counts calendar days in the viewer's time zone. `tests/test_prices_as_of.py` (7 tests) runs `fetch.main()` against a temp directory with the network calls replaced: full success, one set timing out, one set coming back unpriced, a total outage, and a first run with no cache. The first daily run after this is pushed writes the first `price_fetch.json`; until then the site says "Site built".

**Still open:** the fetch step keeps `continue-on-error`, and nothing stops publication when prices are stale.

### 2. eBay API errors become zero listings and can fabricate a demand spike

**Decision:** Fixed.

**Commit:** `f4c6950`

**Why:** This was the worst finding, because it does not just lose data, it invents a signal with a direction, on exactly the days eBay is unhealthy. It already happened. On 2026-09-14 three cards (sv5-198, sv8-208, sv10-244) went from about 150 to 170 listings to 0 and back the next day, and the snapshot recorded 102, 90 and 103 estimated sales. Those have left the 7-day demand window, but the zero is still inside the 30-day supply window: Ciphermaniac's Codebreaking (sv5-198) shows "Supply building" on the site today at a saturation of 1.056, and with that day treated as unknown it would be 1.021, which is steady. The rule I want is simple: only a valid response can say zero.

**How:** In `collectors/ebay.py`, `_is_valid_page()` accepts only a dict whose `itemSummaries` is a list of objects, or a dict with no `itemSummaries` and `total == 0`. Anything else (None from a timeout, 5xx, non-429 error or exhausted 429 backoff, an error body, a list, wrong types) makes `_fetch_card_market()` return an all-None row with no `item_ids`. `diff_row()` returns neutral flow when either day's count is unknown, so neither the error day nor the day after it invents ended or new listings. The sweep log now reports how many cards ended up unknown, and unknown rows still count toward the consecutive-failure breaker. `tests/test_ebay_errors.py` (24 tests) covers the error paths through the real `_browse_request()`, seven malformed bodies, the real-empty case, the day after an unknown, and an end-to-end `collect_snapshot()` with no network. 9 of those tests failed on the old code; the normal gross and net diff tests pass before and after with the same numbers.

**Still open:** whether to null the three 2026-09-14 rows by hand. That is an edit to committed data, so it is not in this change; left alone, the sv5-198 label corrects itself when the day leaves the 30-day window around 2026-10-14.

**Update (verification pass):** Codex found malformed bodies that still became zero, and live signals built from older rows when the latest read was unknown; both are fixed (`0c775d1`, `92a66cb`). The three rows, plus a fourth on 2026-07-13, were set to null with my approval (`6044b83`). See "Verification pass" below.

### 3. Partial eBay snapshots are accepted as complete and cannot be repaired by a same-day rerun

**Decision:** Deferred.

**Commit:** none (no code change)

**Why:** The fix for finding 2 removes the worst part of a partial sweep: cards whose request failed now read as unknown instead of zero, and cards the sweep never reached already did. What remains is completeness. The file does not say how much of the sweep succeeded, and `_snapshot_is_live()` treats one good row as a finished day, so a rerun cannot fill the gaps. Fixing it properly touches the rerun path that protects the eBay quota, and I want that designed and tested on its own.

**Next step:** write a small metadata record next to each snapshot (requested, valid, unknown, calls, elapsed, abort reason), kept out of the per-card map so existing readers keep working; require a coverage share before `_snapshot_is_live()` skips a re-sweep; let a rerun fill only the unknown rows.

### 4. A sidecar failure can commit raw eBay item IDs publicly

**Decision:** Fixed.

**Commit:** `69f8115`

**Why:** The repo is public, so the step that strips item IDs cannot be optional. The step's own comment described its worst case in terms of diff accuracy ("tomorrow's diff uses the NET fallback") and missed that a crash there means the raw IDs get committed. I wanted two independent layers: the strip step fails closed, and a separate check looks at exactly what is about to be committed.

**How:** In `.github/workflows/daily-refresh.yml` the stash step no longer has `continue-on-error`. A new step, "Refuse to commit raw eBay item IDs", stages the same paths as the commit step and runs `scripts/check_no_item_ids.py`, which reads the staged copy of each file and exits 1 if any JSON file has an `item_ids` key at any depth (or does not parse and contains the string). The README no longer says the IDs live in the cache "for exactly one day": each run saves a new cache entry and GitHub deletes entries unused for 7 days. `tests/test_check_no_item_ids.py` (8 tests) includes a real temporary git repo where the staged copy, not the working tree, decides the result. All 309 tracked data files pass the check. In a scratch clone, IDs injected into the newest snapshot made the check exit 1; after the stash step it exited 0. The workflow still parses, and compared with `origin/main` the only differences are these two changes.

**Trade-off I accept:** if the strip step fails, nothing is committed that day, and that day's eBay calls are spent without publishing. Codex's other idea, writing a sanitized publication tree instead of rewriting the collector's files in place, is a later refactor.

### 5. A failed-set cache problem can silently shrink the catalog

**Decision:** Deferred.

**Commit:** none (no code change)

**Why:** The risk is real but it needs two failures at once (a set's fetch fails and its cached copy cannot be read), and the latest data shows every set refreshing: in the 8f25b49 data, 2,934 of 2,937 cards carry a price date from the last three days. The right fix changes when fetch refuses to write, and the workflow ignores fetch's exit code (`continue-on-error`), so the guard has to live somewhere the workflow respects. One small side effect of finding 1: `prices_as_of` stops advancing when any set is not live, so a shrink would at least show up as an older price date, though it would not be prevented.

**Next step:** build into temp files, check exact set coverage and per-set counts against the previous run, and have the build step (which has no `continue-on-error`) refuse to publish a catalog that lost a configured set.

### 6. The published "what the site surfaces" backtest does not test what the site surfaces

**Decision:** Labeled now, fix later.

**Commit:** `019dedb`

**Why:** Codex is right, and the history shows how it happened: `backtest.json` was last generated on 2026-06-21, and the chase-premium gate was added to the build the next day (2026-06-22). The backtest's `_is_surfaced()` was never updated, so calling its number "the honest IC of what users actually see" was wrong from that day on. Relabeling costs nothing. The real fix is a shared gate function and a deliberate backtest rerun, which should not ride along with a copy change.

**How:** On the Track Record page the card is now "Gated cards (mid-price gate only)", marked "Exploratory" instead of "The honest headline", with a note that the live site's chase-premium gate is not applied in the backtest. `pipeline/backtest.py`'s note and comment say the same, so the next manual run writes honest text. README caveat added. `tests/test_known_gaps.py` pins the gap (a mature card at 5x its estimate is hidden by `build._edge()` but counted by `backtest._is_surfaced()`); it fails on purpose when the gap is closed, so the caveat gets revisited.

**Next step:** one pure gate function used by build and backtest, a rerun, and a regression test that both agree on identical rows.

### 7. The production gate was selected on the same backtest used to advertise it

**Decision:** Labeled now, fix later.

**Commit:** `019dedb`

**Why:** True. The price floor, the $20 to $100 dead zone, the fresh-card cutoff, the feature set and the chase treatment were all chosen by looking at this one panel. The Newey-West correction handles overlapping windows, not the selection. Without new data the only honest move is to say so; the real fix needs time, a forward period the rules never saw.

**How:** a visible note at the top of the Track Record: "Exploratory, not a confirmed result", why the numbers are likely optimistic, and that the backtest runs by hand and covers data up to 2026-06-11. Same caveat in the README.

**Next step:** freeze the rules and grade them only on data after the freeze date. `build.py` already writes a `pred-<date>.json` log every day, which is the start of that forward record.

### 8. Months-old sealed prices are labeled "live" and drive actionable EV verdicts

**Decision:** Partly fixed.

**Commit:** `28dc553`, follow-up `377f8de`

**Why:** "live · pokemontcg.io" on prices pasted by hand on 2026-06-18 was plainly false, and 10 of the 15 sets never had a pasted price at all; they use rough estimates from the config. I kept the verdicts visible: a dated, clearly flagged verdict is still useful, and hiding them would remove the EV view until sealed prices are automated. The age just has to be impossible to miss.

**How:** Sets page chip "sealed prices as of 2026-06-18" (read from the `sealed.as_of` already in `sets.json`); a visible note when that is more than 14 days old (today it says 100 days); each set's sealed line says which day its "24h" numbers describe; the caption says card prices refresh daily and sealed prices do not, and how many sets use the paste versus config estimates. Frontend only, so it works on the data already published. Checked in headless Chrome on the committed data.

**Still open:** automating sealed prices (`collectors/sealed_history.py` already appends a daily TCGplayer sealed price for the watched ETBs, which could feed EV) or suppressing verdicts after a freshness limit.

### 9. The pull-rate sourcing claim contradicts the configured inputs

**Decision:** Labeled now, fix later.

**Commit:** `019dedb`

**Why:** The site said the rates come from large samples, while `pipeline/pullrates.py` marks several of them ESTIMATE, PROVISIONAL or PLACEHOLDER. Those marks are comments only, with no machine-readable flag, so I did not invent one for this change; a general caveat is the honest label until the rates carry real provenance.

**How:** the Sets caption now says pull rates are estimates, not official odds, and that some tiers are still rough estimates or placeholders; the `pullrates.py` docstring no longer says every rate is measured; README caveat.

**Next step:** store each rate with its source, sample size and status, show which sets rest on provisional tiers, and publish an EV range instead of a single number.

### 10. "R²" is calculated as squared correlation, not coefficient of determination

**Decision:** Fixed.

**Commit:** `b34bc47`

**Why:** The name promised 1 - SSE/SST. The number is corr(log actual, log predicted)², measured on the cards the model was fit on, and it ignores bias: a model that doubles every price scores a perfect 1.0. I had already been calling it "in-sample fit" on the site, but the README still said R². The label had to say what it is.

**How:** the README, the Price Lab chip (with a tooltip), and the `model.py` docstring and self-test output now say "squared log correlation, in-sample" and point to the Track Record for forward tests. `meta.json` keeps the key `model_r2_log`, which the frontend reads, and gains `model_r2_log_label` with the same wording: labels changed, not the data contract. The `index.html` meta description never mentioned the metric, so it is unchanged. `tests/test_fit_metric.py` shows the doubling model scoring 1.0 here while its standard R² is about 0.74.

**Next step:** add a conventional R², MAE in log and dollar terms, and out-of-sample versions.

### 11. Thin clusters and log retransformation are presented as precise "fair prices"

**Decision:** Labeled now, fix later.

**Commit:** `019dedb`

**Why:** Each cluster's sample size was already in `model.json`, so showing it is cheap and honest. Two cluster models are fit on 12 and 13 cards for three features plus an intercept, and 26 cards fall back to the global model. The modeling fixes (partial pooling, prediction intervals, a retransformation correction) change the model and need a backtest, so they come later.

**How:** the card view now says how many cards the estimate is fit on, says when a card uses the global model, and flags clusters under 30 cards as a small sample. The Price Lab caption says estimates are less reliable for small clusters. README caveat. Checked in headless Chrome: sv3pt5-206 (Trainer, Hyper Rare, 13 cards) shows the small-sample note, and sv3pt5-207 (Energy, Hyper Rare) says it uses the global model (2,936 cards).

**Next step:** partial pooling or a higher `MIN_CLUSTER_SIZE`, intervals, and no over/under call when the interval covers the market price.

### 12. The "live eBay" deal monitor is currently weeks stale

**Decision:** Partly fixed.

**Commit:** `06835b7`, follow-up `377f8de`

**Why:** The deal list comes from a watcher that runs on my own machine, and I publish its snapshot by hand (on purpose, to save Netlify build minutes). The page said "live · eBay", and the list online is from 2026-08-09, 48 days old. I kept the listings visible under a clear warning rather than hiding them; hiding past a threshold is Codex's stronger option and may be the next step.

**How:** header chip "deal list last updated" with its date; a visible note past 7 days ("This list is N days old; most listings have likely ended"); the Refresh button says "No newer data" instead of "Up to date" when the file has not changed; the banner explains it is a published snapshot and that phone alerts go to the monitor's owner only. While there, I fixed copy that contradicted the code: it said auctions show only in their final 10 minutes, but `SITE_AUCTION_WINDOW_H` shows them when they end within 24 hours. Checked in headless Chrome, including a click on Refresh.

**Still open:** hide listings after a threshold, or publish the list from a reliable path.

### 13. Unpinned dependencies run with production secrets available

**Decision:** Deferred.

**Commit:** none (no code change)

**Why:** I agree with it. But pinning with hashes needs a lock file generated for the Actions runner (Linux, Python 3.12), and the only real test is a workflow run, which I did not trigger for this change. A broken install stops the daily refresh, so this gets its own change and a manual run.

**Next step:** a hashed lock file for linux/3.12, actions pinned to commit SHAs, and a look at splitting collection from the push. The eBay secrets are already scoped to the build step's environment.

### 14. There is no CI quality gate or deployed-site verification

**Decision:** Deferred.

**Commit:** none (the item-ID check in `69f8115` is the one related change)

**Why:** There are now 53 tests and the workflow runs none of them. Adding a test step is small, but it changes the workflow beyond the two changes I approved today, and a failing test would block that day's data, so I want to decide it on purpose. The item-ID check from finding 4 is the first publication check that runs in the workflow.

**Next step:** pytest in a dev requirements file and a test step before the commit; a validator for `docs/data` (schema, finite prices, coverage, freshness); a post-deploy check that the live `meta.json` matches the pushed commit; a failure notification.

### 15. Source and methodology disclosures contradict the running system

**Decision:** Fixed.

**Commit:** `855dba5`

**Why:** The eBay feed has been live since June, while `meta.json`, the footer and the home explainer still said it was awaiting data. The feature copy drifted when the model went to three features in June and the text kept mentioning in-set rank. Deriving the text from what actually ran is what stops it drifting again.

**How:** `build.py` derives the eBay source line from the newest snapshot with real listing data, with its date and, if older than 3 days, its age (neutral no-key snapshots do not count), and adds `ebay_latest_snapshot` to `meta.json`; the prices source now names TCGdex. The footer's data-source lines say what is actually wired in, and the eBay line shows the snapshot date when `meta.json` has it. The home explainer and Price Lab text render the model's features from `model.json`; the "Honest stubs" card became "Shown, not modeled"; the card view and the Movers fallback no longer say the eBay feed is not wired; the README says which three signals the model uses. `tests/test_source_status.py` (5 tests) covers no snapshots, neutral-only, recent, old and future-dated files. An offline build of the committed data produces "eBay Browse API active listings (latest snapshot 2026-09-25)".

**Not changed:** the promo banner "Beta · prices updated daily" states the schedule, and the stat card now shows the real price date beside it.

**Update (verification pass):** `CONTRACT.md` still called itself the single source of truth while saying eBay is a stub and the build writes `site/data`. It is now marked as a historical document with those statements corrected (`0e6f3ce`).

### Additional observed stale data (per-card price dates)

**Decision:** Deferred.

**Commit:** none (no code change)

**Why:** In the 8f25b49 data, 2,934 of 2,937 cards carry a price date from the last three days. Two carry 2025 dates (Codex's example, N's Reshiram in Journey Together, from 2025-07-18, and one Stellar Crown card from 2025-08-08) and one Paldean Fates card has none. So the global claim was mostly right, but not for those three. `prices_as_of` now describes the fetch, not each card, which is the honest scope.

**Next step:** show each card's `price_updated` in the card view and flag old ones.

### What the review got right that I had missed

The most useful thing Codex did was follow each failure to what a reader of the site would see. I had hardened the eBay collector for rate limits and hangs, but I never asked what value a failed request leaves behind; it left a zero, the diff turned that zero into sales, and it had already happened on 2026-09-14. The privacy step's failure mode was written up in terms of diff accuracy, and I missed that a crash there commits the raw IDs. I had treated `built_at` as price freshness, left "live" on data that was a hand paste from June and a deal list from August, kept the name R² on a squared correlation, and let the backtest's "surfaced" number fall out of step with the site the day after I added the chase gate. None of these were visible from inside any one file.

Codex could not run the tests: its sandbox had no Python executable, and it said so. We ran them ourselves on Python 3.12 (a venv built from `requirements.txt` plus pytest). Before these changes the suite had 7 tests in 2 files, all passing. After them it has 53 tests in 8 files, all passing. On the last code commit (`377f8de`) we also ran an offline build exactly as the workflow invokes it (eBay keys unset, outbound HTTP pointed at a dead proxy): it completed and every JSON file under `docs/data` parsed, and the regenerated data was discarded rather than committed. `node --check docs/app.js` passes. The workflow YAML parses and differs from `origin/main` only by the two approved changes. The site loaded in headless Chrome twice, once on the committed data and once on a local build that includes `prices_as_of`, and every route (home, Sets, Price Lab, Movers, Watchlists, Track Record, Search and three card views) rendered its expected text with no JavaScript exceptions or console errors; the only error logged was a missing favicon.

### Verification pass

Codex re-checked the ten commits above against this repository and returned **DO_NOT_PUSH**. It found no regression that would break the workflow, and it confirmed that the item-ID guard, `prices_as_of`, the deal-monitor labels, the eBay source status and the fit-metric label work as described. It also found one incomplete fix and five smaller gaps. Like the first pass, it could not run the tests in its sandbox. I approved fixing all of them, one commit each:

1. **High: eBay page validation still allowed false zeros** (`0c775d1`). `{"itemSummaries": []}` with no `total`, `{"total": 5, "itemSummaries": []}`, and pages whose summaries all lack an `itemId`, price, currency or value still became zero listings. `_is_valid_page()` now requires a non-negative integer `total`, treats an empty first page that claims results as unknown, and treats a page with no usable summary as unknown. The only way to record zero is a genuinely empty result. A page of well-formed listings that the business rules drop (graded, non-USD) is still a real zero. 15 new tests, including exhausted 429 retries; 8 of them failed on the previous commit.
2. **A latest unknown row could still be a live signal** (`92a66cb`). `market_dynamics.compute()` now returns the existing `awaiting_data` result, with `basis.reason = "no_current_observation"`, whenever the card has no valid read on the build date. The signal label then drops to price-only, and Movers ranks only cards with a current read. On the 2026-09-25 data, 71 cards were published as live eBay signals although they were not in that day's sweep (some last read in July); they now show awaiting data, and the 807 cards swept that day stay live. One consequence I accept: on a day the whole sweep fails, every eBay signal shows awaiting data instead of yesterday's numbers. 8 new tests.
3. **Track Record copy was stronger than its caveat** (`e2bef5e`). "Strong & robust", "genuinely good" and "reliably ranks" became "strongest historical segment" and "in this exploratory replay", and the summary says the result has not been confirmed on data the rules never saw.
4. **Sealed freshness used the newest paste date** (`e7db31d`). One fresh paste could have made the whole Sets page look fresh. Staleness now uses the oldest pasted date, and the chip, note and caption show a date range when the dates differ. Checked in headless Chrome against scratch copies of the site with mixed and all-fresh dates.
5. **`CONTRACT.md` contradicted the running system** (`0e6f3ce`). It is now marked as a historical design document, not maintained since 2026-06-17, with the eBay-stub and `site/` statements corrected in place, and `build.py`'s docstrings fixed the same way. Codex also noted that the run time it had been told (about 18:00 UTC) does not match the workflow. The repository only documents the 14:00 UTC schedule; the daily data commits over the last two weeks landed between about 16:50 and 19:15 UTC.
6. **Data correction** (`6044b83`). Codex confirmed four stored observations where a card's listings fell to 0 for one day and came back the next, which is the finding 2 failure in the data. On those days all six fields are now null. On the following day only the four flow fields are null, because they were diffed against the false zero; that day's valid count and price are kept.

   | Card | Day nulled | Listings (day before, day, day after) | Estimated sales removed | Saturation as of 2026-09-25, before → after |
   |---|---|---|---:|---|
   | sv5-198 | 2026-09-14 | 170, 0, 169 | 102 | 1.0560 → 1.0208 ("Supply building" becomes "Quiet") |
   | sv8-208 | 2026-09-14 | 150, 0, 158 | 90 | 1.0191 → 0.9851 |
   | sv10-244 | 2026-09-14 | 171, 0, 172 | 103 | 1.0238 → 0.9897 |
   | me4-93 | 2026-07-13 | 151, 0, 155 | 91 | 0.9367 → 0.9367 (the July day is outside its current 30-row window) |

   me4-93 was not in the 2026-09-25 sweep (last read 2026-09-23), so after item 2 it shows awaiting data either way. I left zsv10pt5-97 (1, 0, 1 on 2026-07-14) alone on purpose: one listing disappearing and coming back can be a real relisting, and the snapshots alone do not prove it was an error. Only the four snapshot files are committed; the next daily Action rebuilds the site from them.
7. **This record** gained this section and short update notes under findings 2 and 15.

Checks after the verification pass, on `6044b83`: 76 tests in 9 files, all passing (53 after the first pass, 7 before this review). The offline build, run the way the workflow runs it, completed and all 11 JSON files under `docs/data` parsed; the regenerated data was discarded. Built offline today, it has no current eBay read, so every card correctly shows awaiting data and Movers falls back to price gaps. A separate offline build as of 2026-09-25 gave the saturation values in the table, 50 Movers that all have a current read, and no full-confidence label on a card without one. `node --check docs/app.js` passes. The workflow YAML still differs from `origin/main` only by the two approved changes. Headless Chrome loaded the committed data and a local build with `prices_as_of`, and 11 routes and card views rendered their expected text each time, with no JavaScript exceptions or console errors.
