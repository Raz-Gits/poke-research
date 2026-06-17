"""Fetch card + set data (and today's prices) from pokemontcg.io.

Stdlib only so it runs without the numpy venv. Produces:
  data/raw/<set_id>.json          raw API payloads (cache / audit trail)
  data/normalized/cards.json      list[NormalizedCard]
  data/normalized/sets.json       list[SetRecord]
  data/snapshots/snapshot-<date>.json   {card_id: market_price}  (history seed)

NormalizedCard schema (the contract every downstream module reads):
  id, name, base_name, number, rarity, set_id, set_name, series,
  release_date (YYYY-MM-DD), image_small, image_large,
  market_price (float|None), price_variant (str|None), price_updated (str|None)
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date

from pipeline import config

# Suffix tokens that are card mechanics, not part of the character name.
_SUFFIX_TOKENS = {"ex", "EX", "V", "VMAX", "VSTAR", "GX", "BREAK", "LV.X", "δ", "Prime", "Star"}


def base_name(name: str) -> str:
    """Reduce a printed card name to its underlying Pokémon/character.

    'Team Rocket's Moltres ex' -> 'Moltres'; 'N's Zoroark ex' -> 'Zoroark';
    'Blastoise ex' -> 'Blastoise'; 'Iono' -> 'Iono'.
    """
    n = name.strip()
    # Drop trainer-owner possessive prefix: keep text after the last "'s ".
    if "'s " in n:
        n = n.rsplit("'s ", 1)[1]
    tokens = n.split()
    while tokens and tokens[-1] in _SUFFIX_TOKENS:
        tokens.pop()
    return " ".join(tokens) if tokens else n


def _request(path: str, params: dict) -> dict:
    url = f"{config.API_BASE}/{path}?" + urllib.parse.urlencode(params)
    headers = {"User-Agent": "price-lab/0.1"}
    if config.API_KEY:
        headers["X-Api-Key"] = config.API_KEY
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _pick_price(tcgplayer: dict | None):
    """Return (market_price, variant) using VARIANT_PRIORITY, else best available."""
    if not tcgplayer or not tcgplayer.get("prices"):
        return None, None
    prices = tcgplayer["prices"]
    for variant in config.VARIANT_PRIORITY:
        v = prices.get(variant)
        if v and v.get("market"):
            return float(v["market"]), variant
    # Fall back to any variant that has a market price.
    for variant, v in prices.items():
        if v and v.get("market"):
            return float(v["market"]), variant
    return None, None


def fetch_set_cards(set_id: str) -> list[dict]:
    cards, page = [], 1
    while True:
        payload = _request("cards", {"q": f"set.id:{set_id}", "page": page, "pageSize": 250})
        batch = payload.get("data", [])
        cards.extend(batch)
        if len(batch) < 250:
            break
        page += 1
        time.sleep(0.2)
    return cards


def normalize_card(c: dict) -> dict:
    market, variant = _pick_price(c.get("tcgplayer"))
    s = c.get("set", {})
    rel = (s.get("releaseDate") or "").replace("/", "-") or None
    return {
        "id": c["id"],
        "name": c["name"],
        "base_name": base_name(c["name"]),
        "number": c.get("number"),
        "rarity": c.get("rarity") or "Unknown",
        "set_id": s.get("id"),
        "set_name": s.get("name"),
        "series": s.get("series"),
        "release_date": rel,
        "image_small": (c.get("images") or {}).get("small"),
        "image_large": (c.get("images") or {}).get("large"),
        "market_price": market,
        "price_variant": variant,
        "price_updated": (c.get("tcgplayer") or {}).get("updatedAt"),
    }


def main() -> None:
    all_cards: list[dict] = []
    set_records: list[dict] = []
    for set_id, cfg in config.SETS.items():
        print(f"  fetching {set_id} ({cfg['name']}) ...", flush=True)
        raw = fetch_set_cards(set_id)
        (config.RAW / f"{set_id}.json").write_text(json.dumps(raw))
        if not raw:
            print(f"    !! no cards returned for {set_id}")
            continue
        s = raw[0].get("set", {})
        box_price = cfg.get("box_price") or round(cfg["pack_price"] * cfg["packs_per_box"], 2)
        set_records.append({
            "set_id": set_id,
            "name": s.get("name", cfg["name"]),
            "series": s.get("series"),
            "release_date": (s.get("releaseDate") or "").replace("/", "-") or None,
            "printed_total": s.get("printedTotal"),
            "total": s.get("total"),
            "logo": (s.get("images") or {}).get("logo"),
            "symbol": (s.get("images") or {}).get("symbol"),
            "pack_price": cfg["pack_price"],
            "packs_per_box": cfg["packs_per_box"],
            "box_price": box_price,
        })
        for c in raw:
            all_cards.append(normalize_card(c))

    (config.NORMALIZED / "cards.json").write_text(json.dumps(all_cards, indent=1))
    (config.NORMALIZED / "sets.json").write_text(json.dumps(set_records, indent=1))

    # Seed a price snapshot for today (history for trends / movers / demand).
    snap = {c["id"]: c["market_price"] for c in all_cards if c["market_price"] is not None}
    (config.SNAPSHOTS / f"snapshot-{date.today().isoformat()}.json").write_text(json.dumps(snap))

    priced = sum(1 for c in all_cards if c["market_price"] is not None)
    print(f"\n  {len(all_cards)} cards across {len(set_records)} sets "
          f"({priced} with prices). Wrote normalized + snapshot.")


if __name__ == "__main__":
    main()
