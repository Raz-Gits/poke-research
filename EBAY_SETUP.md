# Turning on the eBay demand feed

The collector + demand-pressure / supply-saturation math are already built. They
go live once you add a free eBay **Production** key and let a few days of
snapshots accumulate.

## 1. Get an eBay App ID (free, ~5 min)

1. Go to **https://developer.ebay.com** and sign in / create a free account.
2. **My Account → Application Keysets**.
3. Create a **Production** keyset (NOT Sandbox — we want real listings).
4. Copy the two values:
   - **App ID** (a.k.a. Client ID) → `EBAY_APP_ID`
   - **Cert ID** (a.k.a. Client Secret) → `EBAY_CERT_ID`

The Browse API (active listings) is read-only and included on the free tier
(~5,000 calls/day — our 2,143-card sweep fits in one run).

## 2. Add your keys (kept out of git)

```bash
cp .env.example .env
# edit .env and paste your App ID + Cert ID
```

`.env` is gitignored — your keys never get committed or deployed.

## 3. Test it (small, before the full sweep)

```bash
set -a; . ./.env; set +a
./.venv/bin/python -c "
import json
from pipeline import config
from collectors import ebay
cards = json.load(open('data/normalized/cards.json'))[:25]   # just 25 cards
ebay.collect_snapshot(cards, out_dir=config.SNAPSHOTS)
import glob, json as j
f = sorted(glob.glob('data/snapshots/ebay-*.json'))[-1]
d = j.load(open(f))
got = [v for v in d.values() if v.get('active_listings')]
print(f'{len(got)}/25 cards returned live active listings -> {f}')
"
```

If that prints real active-listing counts, the live path works.

## 4. Daily run

```bash
./run_daily.sh           # fetch prices + collect eBay snapshot + rebuild
DEPLOY=1 ./run_daily.sh  # ...and auto-commit+push docs/data to redeploy
```

Schedule it once a day (macOS `cron`/`launchd`, or a GitHub Action). Example cron
(9am daily):

```
0 9 * * *  cd "/Users/razsela/Pokemon Bot/poke-research" && DEPLOY=1 ./run_daily.sh >> data/daily.log 2>&1
```

## What to expect

- **Day 1:** snapshot recorded; demand/movers still say "awaiting data" (need ≥2 days).
- **~Day 3-7:** demand pressure + supply-saturation start populating; movers board
  ranks by real supply shift.
- **~Week 2-4:** numbers stabilize as history deepens (eBay gives active listings
  only, so sold-vs-delisted is *inferred* by diffing snapshots — more days = better).

When the data goes live I'll also fix the two known frontend bugs (demand-gauge
scale, and relabeling the movers chip from stub → live) so it renders correctly.
