#!/usr/bin/env bash
# Daily Poke Research refresh — run this on a cron once a day.
#   1. pulls fresh TCGplayer prices (pokemontcg.io + TCGdex)
#   2. collects today's eBay active-listing snapshot (if .env has keys)
#   3. rebuilds docs/data/*.json (prices, model, EV, market dynamics)
#   4. (optional) commits + pushes docs/data so GitHub Pages redeploys
#
# Demand pressure / supply saturation need history — they stay "awaiting data"
# until a few days of snapshots accumulate, then fill in automatically.
set -euo pipefail
cd "$(dirname "$0")"

# Load eBay keys from .env if present (EBAY_APP_ID / EBAY_CERT_ID).
if [ -f .env ]; then set -a; . ./.env; set +a; fi

PY=./.venv/bin/python

echo "[$(date '+%F %T')] 1/3 fetching prices..."
$PY -m pipeline.fetch

echo "[$(date '+%F %T')] 2/3 building (collects today's eBay snapshot + recomputes everything)..."
$PY -m pipeline.build

# 3/3 optional auto-deploy: set DEPLOY=1 to push the refreshed data.
if [ "${DEPLOY:-0}" = "1" ]; then
  echo "[$(date '+%F %T')] 3/3 deploying..."
  git add docs/data data/snapshots data/normalized
  git commit -q -m "data: daily refresh $(date '+%F')" || echo "  (nothing changed)"
  git push -q && echo "  pushed."
else
  echo "[$(date '+%F %T')] done. (set DEPLOY=1 to auto-commit+push)"
fi
