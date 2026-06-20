"""One-off: verify the eBay price-band fix on the cards that showed match-noise.

For each target card we query the live Browse API once and compute avg_price the
OLD way (IQR-only) vs the NEW way (market-anchored band + IQR), so we can see
whether the band actually rescues the chase-card mismatches the data audit found
(e.g. Ethan's Ho-Oh ex reading $5.71 vs $198 market).

Run:  set -a; source .env; set +a; ./.venv/bin/python -m experiments.verify_price_band
"""
from __future__ import annotations

import json
from pathlib import Path

from collectors import ebay

ROOT = Path(__file__).resolve().parent.parent

# Specific chase-card IDs flagged in the data-quality audit (their eBay avg
# collapsed when the search scooped up cheap same-name printings), plus two
# high-value controls to make sure the band doesn't hurt already-good matches.
TARGET_IDS = [
    "sv10-230",      # Ethan's Ho-Oh ex (SIR, $198 market) — audit: eBay read $5.71
    "sv6pt5-98",     # Basic Darkness Energy (Hyper Rare, $67) — audit: eBay $1.70
    "sv6pt5-66",     # Houndoom (IR, $55)
    "sv6pt5-67",     # Horsea (IR, $52)
    "zsv10pt5-92",   # Lilligant (IR, $52)
    "zsv10pt5-127",  # Conkeldurr (IR, $40)
    "sv8pt5-161",    # control: Umbreon ex (SIR, $1559) — should stay sane
    "sv3pt5-199",    # control: Charizard ex (SIR, $471)
]


def _avg_old(prices):
    return ebay._mean(ebay._clean_prices(prices))


def _avg_new(prices, mkt):
    banded, dropped = ebay._apply_price_band(prices, mkt)
    return ebay._mean(ebay._clean_prices(banded)), dropped


def _raw_prices(card, token):
    """Re-run the live fetch loop but keep the raw price list (no band/clean)."""
    q = ebay._build_query(card)
    prices = []
    data = ebay._browse_request(token, q, offset=0)
    for it in (data or {}).get("itemSummaries") or []:
        title = str(it.get("title") or "")
        if ebay._is_graded(f" {title} "):
            continue
        price = it.get("price") or {}
        if str(price.get("currency")) != "USD":
            continue
        try:
            prices.append(float(price.get("value")))
        except (TypeError, ValueError):
            continue
    return q, prices


def main():
    cards = json.loads((ROOT / "docs" / "data" / "cards.json").read_text())
    by_id = {c.get("id"): c for c in cards}
    targets = [by_id[i] for i in TARGET_IDS if i in by_id]
    missing = [i for i in TARGET_IDS if i not in by_id]
    if missing:
        print(f"(not found, skipping: {missing})")

    app_id, cert_id = ebay._ebay_credentials()
    if not (app_id and cert_id):
        raise SystemExit("EBAY_APP_ID/EBAY_CERT_ID not set — `set -a; source .env; set +a` first.")
    token = ebay._get_app_token(app_id, cert_id)
    if not token:
        raise SystemExit("could not get eBay token")

    print(f"\n{'card':28s} {'market':>8s} {'n':>4s} {'old avg':>9s} {'new avg':>9s} {'dropped':>8s}")
    print("-" * 72)
    for card in targets:
        mkt = card.get("market_price")
        q, prices = _raw_prices(card, token)
        if not prices:
            print(f"{card['name'][:28]:28s} {mkt or 0:>8.2f}  (no listings)")
            continue
        old = _avg_old(prices)
        new, dropped = _avg_new(prices, mkt)
        print(f"{card['name'][:28]:28s} {mkt or 0:>8.2f} {len(prices):>4d} "
              f"{old or 0:>9.2f} {new or 0:>9.2f} {dropped:>8d}")


if __name__ == "__main__":
    main()
