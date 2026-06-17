# Poke Research — design system (Miro-inspired, resolved to concrete values)

Adapts Miro's marketing brand language to a data-analytics app. Implement these as CSS
custom properties; the app must look like it belongs to this system. Roobert PRO is
proprietary — use **Hanken Grotesk** (Google Fonts) as the geometric-grotesk substitute,
exposed via `--font` so it can be swapped.

## Tokens (use these exact values)

### Color
```
--canvas:#FFFFFF        --surface:#F5F5F7       --surface-soft:#FAFAFB
--ink:#050038           --ink-deep:#050038      --charcoal:#2D2A45
--slate:#595770         --steel:#787486         --stone:#9B98B0      --muted:#B7B5C4
--primary:#050038       --on-primary:#FFFFFF    --on-dark:#FFFFFF    --on-dark-muted:rgba(255,255,255,.66)
--footer-bg:#050038
--hairline:#E6E6EA      --hairline-soft:#F0F0F3 --hairline-strong:#C9C9D2
--brand-yellow:#FFD02F  --brand-yellow-deep:#F5B800  --yellow-light:#FFF6D6  --yellow-dark:#6B5800  --surface-yellow:#FFF6D6
--brand-blue:#4262FF    --blue-pressed:#2B49D6
--brand-coral:#FF7A59   --coral-light:#FFE4DB   --coral-dark:#8C2E16
--brand-rose:#F6A6C1    --rose-light:#FCE3EC
--brand-teal:#1FB8A6    --teal-light:#D6F1EC    --moss-dark:#0E5A4F
--surface-pricing-featured:#EEEBFF  /* lavender, for featured/highlight */
--success-accent:#2BA66A            /* undervalued / tightening (positive) */
--brand-red:#FBE2E2  --brand-red-dark:#C0392B   /* overvalued / loosening (negative) */
```
Semantic mapping for THIS app: **undervalued / price-discount / tightening supply → success green**;
**overvalued / loosening supply → red**. Demand-pressure gauge fills brand-coral→brand-yellow→red.

### Type — `Hanken Grotesk`, weights 400/500/600 (never 700)
```
hero-display 56px/1.05 w500 -2px   | display-lg 44px/1.10 w500 -1.5px | h1 36px/1.15 w500 -1px
h2 28px/1.2 w500 | h3 22px/1.25 w500 | h4 18px/1.3 w500 | subtitle 18px/1.5 w400
body 16px/1.5 w400 | body-medium 16px/1.5 w500 | body-sm 14px/1.5 w400 | caption 13px/1.4 w400
caption-bold 13px/1.4 w600 | micro-uppercase 11px/1.4 w600 +0.5px | stat-display 56px/1.1 w500 -1.5px
button 14px/1.3 w500
```
(Hero scales down responsively: 56→44 tablet →32 mobile.)

### Spacing (4px base): 4 8 12 16 20 24 32 40 48 64 96. Section rhythm 64–96px. Card padding 24–32px. Max container 1280px, 32px gutters.

### Radius: chips 4 · inputs/search 8 · cards/tables 12 · panels 16 · feature cards 28 · CTA banners 32 · **all buttons/tabs/badges 9999 (pill)**.

### Elevation
```
flat   : 1px solid var(--hairline-soft), no shadow      (default cards, table rows)
card   : 0 4px 12px rgba(5,0,56,.06)                     (feature cards)
raised : 0 12px 32px -4px rgba(5,0,56,.08)               (hero mockup / highlighted card)
modal  : 0 16px 48px -8px rgba(5,0,56,.12)               (card-detail modal, dropdowns)
```

## Components (build these)
- **Top nav** (sticky, white, ~64px): left = "Poke&nbsp;Research" wordmark with a canary-yellow square mark; center = pill-tab nav (Sets · Price Lab · Movers · Search); right = black-pill CTA "Get the data". Collapses to hamburger < 1024px.
- **promo-banner** (optional, above nav): black strip `--primary`, white text, inline yellow pill — use for "Beta · prices updated daily".
- **Buttons**: `button-primary` = black pill (`--primary`/white, 12×24, pill). `button-secondary` = transparent + 1px `--hairline-strong`. `button-yellow` = `--brand-yellow`/`--primary` (brand moments only — never a primary action). `button-blue` = `--brand-blue`/white (inline callouts). Pills always.
- **Pastel feature cards** (28px radius): yellow / coral-light / teal-light / rose-light backgrounds with `--primary` text — use for the landing stat callouts ("1,602 cards", "8 sets tracked", "Updated daily") and section intros. Pair with white cards in the same row.
- **stat-display**: big 56px numbers for headline stats.
- **Leaderboard table** (`card`/`flat`): rounded-12 container, rows divided by `--hairline-soft`, 14px body. Each row: rank, card thumbnail (image_small, 40px, radius 8), name + set (muted), market price, expected price, and a pill **delta badge** (green pill for undervalued −X%, red pill for overvalued +X%), IQ score chip.
- **Gauges**: demand-pressure and supply-saturation as small semicircle/bar gauges on the card detail (coral→yellow→red). Stub signals get a `badge` "awaiting data".
- **Card-detail modal** (`modal` elevation, radius 16): left = card image (image_large); right = name, set, rarity, market vs **expected** price, big delta %, IQ score. Below: **"View Market Signals"** panel — one labeled slider per feature (range from model.json metadata), value readout, and a live-updating expected price that recomputes client-side from the card's cluster coefficients. **Reset** pill restores model values. Stubbed signals visibly tagged.
- **Footer**: dark `--footer-bg`, multi-column (Product · Data sources · About · GitHub), white-muted links, "prices via pokemontcg.io" credit.

## Rules
- White canvas is the default surface; reserve `--brand-yellow` for the wordmark, promo banner, and yellow tag chips — **never** as a primary CTA or large background.
- Black pill (`--primary`) is the dominant CTA everywhere. Every button/tab/badge is a pill.
- Pastel feature cards use 28px radius; keep shadows light and flat — reserve real elevation for the modal and a highlighted hero card.
- No stock photography — the "product imagery" here is the live card data (thumbnails, gauges, the signals panel).
- Every estimated/stub signal must be labeled; never imply eBay/PSA/Trends feeds we don't have.
- Responsive: hero 56→44→32; nav → hamburger < 1024px; leaderboard table → horizontal scroll on mobile; pastel card rows 4-up → 2-up → 1-up; footer 4-col → 2-col → accordion.
