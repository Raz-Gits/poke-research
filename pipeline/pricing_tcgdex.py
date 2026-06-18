"""Secondary price source: TCGdex (https://tcgdex.dev) — free, no API key.

Used to fill prices for sets pokemontcg.io catalogues but doesn't price yet
(e.g. the 2026 Mega Evolution series). pokemontcg.io stays the spine; this only
fills gaps. TCGdex carries TCGplayer (USD) market prices + Cardmarket (EUR).

Public surface:
    SET_ID_MAP                  pokemontcg.io set_id -> TCGdex set_id
    prices_for_set(ptcg_set_id) -> {normalized_number: (price_usd, variant, updated)}
"""
from __future__ import annotations

import concurrent.futures
import json
import urllib.request
from typing import Dict, Optional, Tuple

TCGDEX = "https://api.tcgdex.net/v2/en"

# pokemontcg.io set_id -> TCGdex set_id (extend as new uncovered sets appear).
SET_ID_MAP: Dict[str, str] = {
    "me1": "me01",
    "me2": "me02",
    "me2pt5": "me02.5",
    "me3": "me03",
    "me4": "me04",
}

# TCGplayer variant preference (TCGdex uses hyphenated keys).
_VAR_ORDER = ["holofoil", "reverse-holofoil", "normal", "first-edition-holofoil"]
_EUR_USD = 1.08  # rough; only used if a card has no TCGplayer price at all

Price = Tuple[Optional[float], Optional[str], Optional[str]]


def normalize_number(n) -> str:
    """Canonical key for matching across sources: strip leading zeros, upper-case.

    pokemontcg.io '90' and TCGdex '090' both map to '90'.
    """
    s = str(n).strip().upper().lstrip("0")
    return s or "0"


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "price-lab/0.1"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _card_price(card: dict) -> Price:
    """Best USD market price for a TCGdex card: TCGplayer first, Cardmarket fallback."""
    pricing = card.get("pricing") or {}
    tcg = pricing.get("tcgplayer") or {}
    for variant in _VAR_ORDER:
        d = tcg.get(variant)
        if isinstance(d, dict) and d.get("marketPrice"):
            return round(float(d["marketPrice"]), 2), f"tcgplayer:{variant}", tcg.get("updated")
    for variant, d in tcg.items():  # any other TCGplayer variant with a market price
        if isinstance(d, dict) and d.get("marketPrice"):
            return round(float(d["marketPrice"]), 2), f"tcgplayer:{variant}", tcg.get("updated")
    cm = pricing.get("cardmarket") or {}
    if cm.get("avg"):
        return round(float(cm["avg"]) * _EUR_USD, 2), "cardmarket:avg(EUR->USD)", cm.get("updated")
    return None, None, None


def prices_for_set(ptcg_set_id: str) -> Dict[str, Price]:
    """Return ``{normalized_number: (price_usd, variant, updated)}`` for a mapped set.

    Empty dict if the set isn't mapped or TCGdex is unreachable.
    """
    tcgdex_id = SET_ID_MAP.get(ptcg_set_id)
    if not tcgdex_id:
        return {}
    try:
        detail = _get(f"{TCGDEX}/sets/{tcgdex_id}")
    except Exception:
        return {}
    card_ids = [c["id"] for c in detail.get("cards", []) if c.get("id")]

    def fetch_one(cid: str):
        try:
            card = _get(f"{TCGDEX}/cards/{cid}")
            return card.get("localId"), _card_price(card)
        except Exception:
            return None, (None, None, None)

    out: Dict[str, Price] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for local_id, price in ex.map(fetch_one, card_ids):
            if local_id is not None and price[0] is not None:
                out[normalize_number(local_id)] = price
    return out
