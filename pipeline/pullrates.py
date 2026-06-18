"""Rarity -> pull-rate model for Poke Research.

A booster pack yields *some* card of each rarity tier with a per-pack
probability. Within a tier, that probability is spread evenly across every card
of that rarity in the set, so a single specific card's per-pack pull rate is::

    pull_rate(card) = tier_prob(rarity, set) / (# cards of that rarity in the set)

and its "pull cost" — the expected dollars of packs you must rip to land one
copy — is ``pack_price / pull_rate``.

PULL RATES ARE REAL, MEASURED DATA (not my guesses), but NOT official: The
Pokémon Company never publishes pull rates, so these come from large community
pack-opening studies (1,000-8,000+ packs each). They carry a sample-size margin
and every pack is independent — treat them as the best available estimate.

Structure:
  * ``BASE_TIER_PROB`` — measured rates for a STANDARD Scarlet & Violet set
    (the rare slot + reverse-holo+ slot are consistent across the era).
  * ``SET_TIER_PROB``  — per-set overrides where a set's measured rates differ
    (special sets: 151, Prismatic Evolutions, Paldean Fates, Shrouded Fable),
    each cited. Sets without an entry use the base table.

Sources: cardshoplive (SV hit rates, ~1,728 packs), TCGplayer & PokéPatch (151,
1,000+ packs), TCGplayer (Paldean Fates, 1,500 packs), PokéBeach/TCGplayer
(Prismatic Evolutions, 1,200 packs).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, Mapping

# ---------------------------------------------------------------------------
# Measured base rates for a STANDARD Scarlet & Violet set (per pack).
# Common/Uncommon/Rare are ~guaranteed slots (1.0). Shiny tiers are 0 here —
# they only exist in dedicated shiny sets, which override below.
# ---------------------------------------------------------------------------
BASE_TIER_PROB: Dict[str, float] = {
    "Common": 1.0,
    "Uncommon": 1.0,
    "Rare": 1.0,
    "Double Rare": 0.135,                 # ~13.5% (1 in 7.4)
    "ACE SPEC Rare": 0.083,               # ESTIMATE — no large public sample
    "Ultra Rare": 0.065,                  # ~6.5% (1 in 15.4)
    "Illustration Rare": 0.075,           # ~7.5% (1 in 13.3)
    "Special Illustration Rare": 0.0118,  # ~1 in 85 (standard SV, Surging Sparks-era)
    "Hyper Rare": 0.0185,                 # ~1.85% (1 in 54)
    "Shiny Rare": 0.0,                    # shiny sets only (override)
    "Shiny Ultra Rare": 0.0,              # shiny sets only (override)
    "MEGA_ATTACK_RARE": 0.06,             # PROVISIONAL (new Mega Evolution tier)
    "Mega Hyper Rare": 0.0185,            # PROVISIONAL (~Hyper Rare)
    "Unknown": 0.05,
}

# Per-set overrides. Only list rarities whose measured rate differs from base.
SET_TIER_PROB: Dict[str, Dict[str, float]] = {
    # 151 (sv3pt5) — TCGplayer / PokéPatch (1,000+ packs)
    "sv3pt5": {
        "Double Rare": 0.125,              # 1 in 8
        "Ultra Rare": 0.065,
        "Illustration Rare": 0.085,        # ~8.5%
        "Special Illustration Rare": 0.028,  # ~1 in 36
        "Hyper Rare": 0.02,                # ~1 in 50
    },
    # Prismatic Evolutions (sv8pt5) — PokéBeach/TCGplayer (1,200 packs). SIR
    # deliberately ~2x easier; 32 SIRs in the set, so a *specific* one is ~1 in 1,440.
    "sv8pt5": {
        "Double Rare": 0.20,               # ~7-9 ex per box
        "Ultra Rare": 0.065,
        "Illustration Rare": 0.10,         # ~3-4 IR per box
        "Special Illustration Rare": 0.022,  # 1 in 45
        "Hyper Rare": 0.018,
    },
    # Paldean Fates (sv4pt5) — shiny set, TCGplayer (1,500 packs)
    "sv4pt5": {
        "Double Rare": 0.12,
        "Ultra Rare": 0.067,               # 1 in 15
        "Illustration Rare": 0.071,        # 1 in 14
        "Special Illustration Rare": 0.017,  # 1 in 58
        "Shiny Rare": 0.25,                # "baby shinies", 1 in 4
        "Shiny Ultra Rare": 0.075,         # 1 in 13
    },
    # Shrouded Fable (sv6pt5) — special shiny set; PROVISIONAL shiny rates
    # (no large public sample yet).
    "sv6pt5": {
        "Shiny Rare": 0.20,
        "Shiny Ultra Rare": 0.05,
    },
    # Mega Evolution sets — PROVISIONAL: thin community data so far, so they use
    # the base table + the Mega tiers. Update when real openings accumulate.
    "me2pt5": {},
    "me3": {},
    "me4": {},
}

_DEFAULT_PROB = BASE_TIER_PROB["Unknown"]

# Back-compat alias (older code / tests referenced TIER_PROB).
TIER_PROB = BASE_TIER_PROB


def tier_prob(rarity: str, set_id: str) -> float:
    """Per-pack hit probability for ``rarity`` in ``set_id`` (set override else base)."""
    override = SET_TIER_PROB.get(set_id, {})
    if rarity in override:
        return override[rarity]
    return BASE_TIER_PROB.get(rarity, _DEFAULT_PROB)


def rarity_counts(cards: Iterable[Mapping]) -> Dict[str, Dict[str, int]]:
    """Count cards per rarity within each set -> ``{set_id: {rarity: count}}``."""
    counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for card in cards:
        counts[card["set_id"]][card["rarity"]] += 1
    return {sid: dict(rmap) for sid, rmap in counts.items()}


def pull_rate(rarity: str, set_id: str, counts: Mapping[str, Mapping[str, int]]) -> float:
    """Per-pack probability of pulling ONE specific card of ``rarity`` in ``set_id``.

    = ``tier_prob(rarity, set_id) / (# cards of that rarity in that set)``.
    Returns ``0.0`` when the set/rarity is unknown or has no cards.
    """
    p = tier_prob(rarity, set_id)
    n_in_tier = counts.get(set_id, {}).get(rarity, 0)
    if n_in_tier <= 0 or p <= 0.0:
        return 0.0
    return p / n_in_tier


def pull_cost(
    rarity: str,
    set_id: str,
    counts: Mapping[str, Mapping[str, int]],
    pack_price: float,
) -> float:
    """Expected dollars of packs to pull one specific card = ``pack_price / pull_rate``.

    Returns ``inf`` when the per-card pull rate is zero (unknown set/rarity).
    """
    rate = pull_rate(rarity, set_id, counts)
    if rate <= 0.0:
        return float("inf")
    return pack_price / rate
