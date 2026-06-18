"""Interim sealed-market feed (manual TCGplayer paste) — until the eBay feed.

`data/sealed_market.json` holds a dump of TCGplayer sealed-product data keyed by
set name (price, 24h change, units sold today, active listings). This module
maps those names to our set_ids and extracts, per set:

  * ``pack_price``  — the loose "Booster Pack" market price (single-pack rip EV)
  * ``etb_price``   — the "Elite Trainer Box" market price (ETB EV)
  * ``sealed``      — a per-set demand summary (pack + ETB: price / change_24h /
                      sold_today / listings) used for the Sets-page "sealed heat"

These are SET-LEVEL SEALED signals (not per-card). The per-card demand-pressure
channel still comes from eBay singles. Paste a fresh dump and rebuild to refresh.
"""
from __future__ import annotations

import json
from typing import Dict

from . import config

# TCGplayer set name -> our set_id. Names we don't track are ignored.
NAME_TO_SETID: Dict[str, str] = {
    "151": "sv3pt5",
    "Prismatic Evolutions": "sv8pt5",
    "Surging Sparks": "sv8",
    "Paldean Fates": "sv4pt5",
    "Shrouded Fable": "sv6pt5",
    "Stellar Crown": "sv7",
    "Twilight Masquerade": "sv6",
    "Temporal Forces": "sv5",
    "Ascended Heroes": "me2pt5",
    "Perfect Order": "me3",
    "Chaos Rising": "me4",
    # newly-added sets (mapped here so the same feed updates them once tracked)
    "Mega Evolution": "me1",
    "Journey Together": "sv9",
    "Destined Rivals": "sv10",
    "Black Bolt": "zsv10pt5",
    "White Flare": "rsv10pt5",
}

_FEED_PATH = config.ROOT / "data" / "sealed_market.json" if hasattr(config, "ROOT") \
    else None

_DEMAND_KEYS = ("price", "change_24h", "sold_today", "listings")


def _summary(row):
    return {k: row.get(k) for k in _DEMAND_KEYS} if row else None


def load(path=None) -> Dict[str, dict]:
    """Return ``{set_id: {pack_price?, etb_price?, sealed}}`` from the feed.

    Empty dict if the feed file is missing/unreadable.
    """
    path = path or _FEED_PATH or (config.NORMALIZED.parent / "sealed_market.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}

    as_of = data.get("as_of")
    out: Dict[str, dict] = {}
    for name, products in (data.get("sets") or {}).items():
        sid = NAME_TO_SETID.get(name)
        if not sid:
            continue
        pack = next((p for p in products if p.get("product") == "Booster Pack"), None)
        etb = next(
            (p for p in products
             if str(p.get("product", "")).startswith("Elite Trainer Box")
             and "Pokemon Center" not in p.get("product", "")),
            None,
        )
        rec: dict = {"sealed": {"as_of": as_of, "pack": _summary(pack), "etb": _summary(etb)}}
        if pack and pack.get("price"):
            rec["pack_price"] = pack["price"]
        if etb and etb.get("price"):
            rec["etb_price"] = etb["price"]
        out[sid] = rec
    return out
