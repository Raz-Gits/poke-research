#!/usr/bin/env bash
# Quick price refresh: re-pull current card prices (pokemontcg.io) + rebuild
# everything. Run this whenever you want fresh numbers.
#
#   ./refresh.sh            # refresh locally
#   DEPLOY=1 ./refresh.sh   # ...and commit + push so the live site updates
#
# Single-card prices come back live & free; sealed (ETB) prices are not in this
# feed (see EBAY_SETUP.md / CLAUDE.md for the sealed plan).
set -euo pipefail
cd "$(dirname "$0")"

PY=./.venv/bin/python
META=docs/data/meta.json

prev="(none yet)"
[ -f "$META" ] && prev=$($PY -c "import json;print(json.load(open('$META'))['built_at'])" 2>/dev/null || echo "(unknown)")
echo "Last refresh was: $prev"
echo "Refreshing prices now…"

# Load eBay keys if present (no-op without them).
if [ -f .env ]; then set -a; . ./.env; set +a; fi

$PY -m pipeline.fetch
$PY -m pipeline.build

now=$($PY -c "import json;print(json.load(open('$META'))['built_at'])")
echo "✓ Refreshed: $now"

if [ "${DEPLOY:-0}" = "1" ]; then
  git add docs/data data/normalized data/snapshots 2>/dev/null || true
  git commit -q -m "data: price refresh $now" && git push -q && echo "✓ Deployed." \
    || echo "  (nothing to deploy)"
else
  echo "  (run 'DEPLOY=1 ./refresh.sh' to also push it live)"
fi
