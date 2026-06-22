# eBay Marketplace Insights API — Access Application Packet

This document is a ready-to-submit justification for requesting access to eBay's **Marketplace Insights API** (`buy.marketplace.insights`), a Limited Release / restricted Buy API that returns sold/completed item transactions over the trailing 90 days. The sections below can be pasted directly into eBay's developer application form or a developer-support request.

---

## 1. Summary

I am requesting access to the **Marketplace Insights API** for an existing eBay developer account that already holds production Browse API keys. The account powers **poke-research**, a personal, non-commercial Pokémon TCG (trading card game) price-analytics project. I currently use the Browse API to track active listing counts per card and *infer* sales by diffing active listings day over day. I am requesting Marketplace Insights so I can replace that inference with real sold-transaction signals — actual sold price and sales volume — to make the project's market-demand estimates accurate rather than approximate.

---

## 2. Business / Use-Case Justification

**What the application does.** poke-research is a static analytics website (hosted on Netlify/GitHub Pages) that estimates a fair/expected price for individual Pokémon trading cards using a clustered ridge-regression model, and flags cards that appear over- or under-valued relative to that estimate. It is a personal research and hobby tool. It does not resell data, does not republish eBay listings, and is not a commercial product.

**How Marketplace Insights data will be used.** Sold price and sold volume from the `item_sales/search` endpoint will be consumed only to derive *aggregated market-signal labels* — for example "demand pressure," "market cooling," and "demand tightening" — and to validate and calibrate the expected-price model. Raw transaction records are never displayed as listings or redistributed; they are collapsed into per-card summary statistics (median sold price, sales count, short-window trend) and then discarded or stored only as the derived signal.

**Why the Browse API alone is insufficient.** The Browse API exposes only *active* listings. To approximate demand today I diff active-listing counts between daily snapshots and guess which listings sold versus were merely delisted or relisted. This is noisy and cannot distinguish a genuine sale from a cancellation, nor can it recover the actual sale price. Marketplace Insights provides the real sold price and real sold volume the model needs, which directly improves accuracy and removes a class of inference error that active-only data cannot resolve.

---

## 3. Data Handling & Compliance

- **Aggregated use only.** eBay sold/listing data is reduced to per-card summary statistics and market-signal labels; individual transactions are not surfaced to users.
- **No bulk redistribution.** Raw eBay listing or sold-item data is never republished, exported, sold, or made available for download.
- **Respect for rate limits.** Calls are throttled to stay well within eBay's allotted quota; no scraping or circumvention is used.
- **Compliance with the eBay API License Agreement** and the Marketplace Insights API terms, including all usage and data-retention restrictions.
- **Derived storage only.** Persisted data consists of derived signals and aggregates (e.g., median sold price, sales count, trend direction), not retained raw transaction feeds.

---

## 4. Requested Scope & Volume

- **OAuth scope:** `https://api.ebay.com/oauth/api_scope/buy.marketplace.insights`
- **Endpoint:** `GET /buy/marketplace_insights/v1_beta/item_sales/search`
- **Authentication:** existing application access token (OAuth client-credentials grant) on the current production account.
- **Estimated volume:** approximately **150–300 cards per day**, one `item_sales/search` call each — roughly **150–300 calls/day**. This is a single low-frequency daily batch and sits well under typical rate limits, with no real-time or per-user querying.

---

## 5. Cover Note / Email Template

> Subject: Marketplace Insights API access request — existing Browse API developer account
>
> Hello eBay Developer Support,
>
> I'm requesting access to the Marketplace Insights API for my existing developer account, which already has production Browse API keys. I run a personal, non-commercial Pokémon trading-card price-analytics project that estimates fair card prices with a statistical model and flags over/under-valued cards. Today I use the Browse API to track active listings and infer sales by comparing daily snapshots, but active-only data can't tell me real sold prices or true sales volume. I'd like the `buy.marketplace.insights` scope so I can use the `item_sales/search` endpoint to derive aggregated demand and price signals from actual completed sales — not to redistribute raw listing data. My expected usage is a single daily batch of roughly 150–300 calls, well within rate limits, and all data is stored only as aggregated, derived signals in line with the eBay API License Agreement. I'd be glad to provide any additional detail needed to evaluate the request. Thank you for considering it.
>
> Best regards,
> [Name] — [developer account / App ID]
