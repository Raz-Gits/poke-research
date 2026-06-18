"""Rarity -> pull-rate model for Poke Research.

A booster pack yields *some* card of each rarity tier with a per-pack
probability (``TIER_PROB``). Within a tier, that probability is spread evenly
across every card of that rarity in the set, so a single specific card's
per-pack pull rate is::

    pull_rate(card) = TIER_PROB[rarity] / (# cards of that rarity in the set)

The "pull cost" of a card is the expected dollars of packs you must rip to land
one copy: ``pack_price / pull_rate``.

All probabilities are ESTIMATES (configurable) — they encode rough secondary
market hit rates, not official, audited pull odds.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, Mapping

# ---------------------------------------------------------------------------
# Per-pack probability that a pack yields a card of each rarity tier.
# ESTIMATE — see CONTRACT.md. Common/Uncommon/Rare are ~guaranteed slots (1.0);
# the chase tiers are fractional "hit" odds.
# ---------------------------------------------------------------------------
TIER_PROB: Dict[str, float] = {
    "Common": 1.0,
    "Uncommon": 1.0,
    "Rare": 1.0,
    "ACE SPEC Rare": 0.083,
    "Double Rare": 0.125,
    "Ultra Rare": 0.083,
    "Illustration Rare": 0.167,
    "Special Illustration Rare": 0.025,
    "Hyper Rare": 0.02,
    "Shiny Rare": 0.20,
    "Shiny Ultra Rare": 0.033,
    # Mega Evolution series (2026) tiers
    "MEGA_ATTACK_RARE": 0.06,
    "Mega Hyper Rare": 0.02,
    "Unknown": 0.05,
}

# Rarity tiers we don't recognise fall back to this probability.
_DEFAULT_PROB = TIER_PROB["Unknown"]


def rarity_counts(cards: Iterable[Mapping]) -> Dict[str, Dict[str, int]]:
    """Count cards per rarity within each set.

    Parameters
    ----------
    cards:
        Iterable of NormalizedCard mappings (each has ``set_id`` and ``rarity``).

    Returns
    -------
    dict
        ``{set_id: {rarity: count}}``.
    """
    counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for card in cards:
        set_id = card["set_id"]
        rarity = card["rarity"]
        counts[set_id][rarity] += 1
    # Freeze the defaultdicts into plain dicts for clean serialisation/repr.
    return {sid: dict(rmap) for sid, rmap in counts.items()}


def pull_rate(rarity: str, set_id: str, counts: Mapping[str, Mapping[str, int]]) -> float:
    """Per-pack probability of pulling ONE specific card of ``rarity`` in ``set_id``.

    = ``TIER_PROB[rarity] / (# cards of that rarity in that set)``.

    Returns ``0.0`` when the set/rarity is unknown (no such card can be pulled).
    """
    tier_prob = TIER_PROB.get(rarity, _DEFAULT_PROB)
    n_in_tier = counts.get(set_id, {}).get(rarity, 0)
    if n_in_tier <= 0:
        return 0.0
    return tier_prob / n_in_tier


def pull_cost(
    rarity: str,
    set_id: str,
    counts: Mapping[str, Mapping[str, int]],
    pack_price: float,
) -> float:
    """Expected dollars of packs to pull one specific card.

    = ``pack_price / pull_rate``. Returns ``inf`` when the per-card pull rate is
    zero (unknown set/rarity), since no number of packs guarantees the pull.
    """
    rate = pull_rate(rarity, set_id, counts)
    if rate <= 0.0:
        return float("inf")
    return pack_price / rate
