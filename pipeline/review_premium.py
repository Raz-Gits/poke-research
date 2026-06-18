"""Flag character-premium discrepancies for manual review.

The character premium (popularity.py: Wikipedia + 2020 poll) is a STARTING POINT,
not a source of truth — card art, hype, and niche collector demand move prices in
ways a popularity signal can't see. This script cross-checks each character's
premium against what the market actually pays for their cards and surfaces the
biggest disagreements, so you can hand-tune popularity.USER_OVERRIDES where it
matters.

Method:
  * price_signal — for each card, its market-price percentile WITHIN its rarity
    (controls for rarity, so a $300 SIR and a $5 common are judged against their
    own kind). A character's price_signal is their *best* card's percentile ×10:
    "how hard does the market pay up for this character, rarity-for-rarity."
  * premium — the character premium already on the site (features.char_premium).
  * gap = price_signal − premium.
      gap >> 0  -> market is hotter than our rating (underrated, OR pure
                   hype/scarcity to discount — your call).
      gap << 0  -> we rate it more popular than the market pays (overrated, OR a
                   genuinely undervalued character to watch).

Run: ./.venv/bin/python -m pipeline.review_premium
Writes docs/data/premium_review.json and prints the top flags.
"""
from __future__ import annotations

import json
from collections import defaultdict

import numpy as np

from . import config, popularity

# Only review characters with at least one reasonably valuable card, so the
# report is about cards that matter, not $0.40 commons.
MIN_TOP_PRICE = 20.0
N_FLAGS = 18         # how many to show per direction
GAP_THRESHOLD = 1.5  # |price_signal - premium| below this is "in agreement"


def _base_char(base_name: str) -> str:
    """Collapse Mega/form variants to the base character key."""
    return list(popularity._variant_keys(base_name))[-1]


def build_review(cards: list) -> dict:
    # Price percentile within rarity (ascending) for every priced card.
    by_rarity: dict = defaultdict(list)
    for c in cards:
        p = c.get("market_price")
        if p is not None:
            by_rarity[c.get("rarity")].append(float(p))
    sorted_rarity = {r: np.sort(np.array(v, float)) for r, v in by_rarity.items()}

    # Aggregate to character: best (max) within-rarity percentile + top price +
    # the premium currently on the site.
    agg: dict = {}
    for c in cards:
        if c.get("supertype") != "Pokémon":
            continue
        price = c.get("market_price")
        if price is None:
            continue
        name = _base_char(c.get("base_name") or "")
        if not name:
            continue
        arr = sorted_rarity[c.get("rarity")]
        pct = float(np.searchsorted(arr, float(price), side="right")) / arr.size
        rec = c.get("features", {}).get("char_premium")
        a = agg.setdefault(name, {"price_pct": 0.0, "top_price": 0.0,
                                  "premium": rec, "top_card": None, "top_rarity": None})
        if pct > a["price_pct"]:
            a["price_pct"] = pct
        if float(price) > a["top_price"]:
            a["top_price"] = float(price)
            a["top_card"] = c.get("name")
            a["top_rarity"] = c.get("rarity")
        if rec is not None:
            a["premium"] = rec

    rows = []
    for name, a in agg.items():
        if a["top_price"] < MIN_TOP_PRICE or a["premium"] is None:
            continue
        price_signal = round(10.0 * a["price_pct"], 2)
        gap = round(price_signal - a["premium"], 2)
        _, src = popularity.popularity_prior(name)
        rows.append({
            "character": name,
            "premium": round(a["premium"], 2),
            "price_signal": price_signal,
            "gap": gap,
            "source": src or "structural",
            "top_card": a["top_card"],
            "top_rarity": a["top_rarity"],
            "top_price": round(a["top_price"], 2),
        })

    underrated = sorted([r for r in rows if r["gap"] >= GAP_THRESHOLD],
                        key=lambda r: -r["gap"])[:N_FLAGS]
    overrated = sorted([r for r in rows if r["gap"] <= -GAP_THRESHOLD],
                       key=lambda r: r["gap"])[:N_FLAGS]
    return {
        "explain": "gap = price_signal - premium. +gap: market hotter than rating "
                   "(maybe underrated or hype). -gap: rated higher than market pays.",
        "reviewed": len(rows),
        "market_hotter": underrated,   # gap >> 0
        "rating_hotter": overrated,    # gap << 0
    }


def main() -> None:
    cards = json.load(open(config.SITE_DATA / "cards.json", encoding="utf-8"))
    review = build_review(cards)
    out = config.SITE_DATA / "premium_review.json"
    json.dump(review, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    def show(rows, title):
        print(f"\n=== {title} ===")
        print(f"{'character':<14}{'prem':>5}{'price':>7}{'gap':>7}  {'src':<5} top card")
        for r in rows:
            print(f"{r['character']:<14}{r['premium']:>5.1f}{r['price_signal']:>7.1f}"
                  f"{r['gap']:>+7.1f}  {r['source']:<5} {r['top_card']} "
                  f"({r['top_rarity']}, ${r['top_price']:,.0f})")

    print(f"reviewed {review['reviewed']} characters with a card >= ${MIN_TOP_PRICE:.0f}")
    show(review["market_hotter"], "MARKET HOTTER THAN RATING (review: bump up? or hype/scarcity)")
    show(review["rating_hotter"], "RATING HOTTER THAN MARKET (review: overrated? or undervalued)")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
