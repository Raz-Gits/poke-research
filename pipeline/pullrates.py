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
    "Black White Rare": 0.0,              # Black Bolt/White Flare secret tier (override)
    "MEGA_ATTACK_RARE": 0.06,             # PROVISIONAL (new Mega Evolution tier)
    "Mega Hyper Rare": 0.005,             # PROVISIONAL — single gold Mega chase, ~1 in 200
                                          # (was 0.0185/1-in-54, far too easy for a top gold)
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
    # ----- Standard SV sets — Temporal Forces reset the "harder" baseline. SIR
    # holds at 1 in 86 across all four (≈ the base table); Hyper varies with how
    # many golds TPCi printed. TCGplayer 8,000+ pack samples. (Big fix: base
    # Hyper was 1/54 — these are 1/137-188.)
    "sv5": {  # Temporal Forces
        "Special Illustration Rare": 0.011628,  # 1 in 86
        "Hyper Rare": 0.007194,               # 1 in 139
    },
    "sv6": {  # Twilight Masquerade
        "Special Illustration Rare": 0.011628,  # 1 in 86
        "Hyper Rare": 0.006849,               # 1 in 146
    },
    "sv7": {  # Stellar Crown
        "Special Illustration Rare": 0.011628,  # 1 in 86
        "Hyper Rare": 0.007299,               # 1 in 137
    },
    "sv8": {  # Surging Sparks
        "Special Illustration Rare": 0.011628,  # 1 in 86
        "Hyper Rare": 0.005319,               # 1 in 188
    },
    "sv9": {  # Journey Together — SIR confirmed 1/86; Hyper PLACEHOLDER (~1/150)
        "Special Illustration Rare": 0.011628,  # 1 in 86
        "Hyper Rare": 0.006667,               # ~1 in 150 (PLACEHOLDER — get exact)
    },
    "sv10": {  # Destined Rivals — SIR confirmed 1/86; Hyper PLACEHOLDER (~1/150)
        "Special Illustration Rare": 0.011628,  # 1 in 86
        "Hyper Rare": 0.006667,               # ~1 in 150 (PLACEHOLDER — get exact)
    },
    # Black Bolt (zsv10pt5) — DATA-BACKED (owner, mid-2026 community openings).
    # IR-rich special set; the top secret is "Black White Rare" (2 in Black Bolt —
    # Victini #171, Zekrom ex #172; the other 2 BWRs live in White Flare, untracked).
    # NOTE: the Poke Ball (1/3) & Master Ball (1/19) pattern foils are NOT separate
    # cards in pokemontcg.io's data, so they can't be valued here -> our EV slightly
    # UNDER-counts (omits pattern-foil value).
    "zsv10pt5": {
        "Double Rare": 0.211,                 # 1 in ~5
        "Illustration Rare": 0.164,           # 1 in ~6 (≈2x a standard SV set)
        "Ultra Rare": 0.0645,                 # 1 in 14-17 (midpoint ~1/15.5)
        "Special Illustration Rare": 0.01227, # 1 in 80-83 (midpoint ~1/81.5)
        "Black White Rare": 0.002016,         # 1 in 496 per pack (either BWR); ~1/992 each
    },
    # Mega Evolution (me1) — DATA-BACKED (owner, mid-2026). ~19% Double-Rare-or-better
    # hit rate; an extremely hard Mega Hyper Rare (~35 boxes/pull) — don't lean box EV
    # on it; the 1-in-101 SIR is the realistic chase ceiling.
    "me1": {
        "Double Rare": 0.209,                 # 1 in ~5
        "Illustration Rare": 0.109,           # 1 in ~9
        "Ultra Rare": 0.082,                  # 1 in ~12
        "Special Illustration Rare": 0.009901,  # 1 in 101
        "Mega Hyper Rare": 0.000794,          # 1 in 1,260 per pack (either MHR)
    },
    # ----- Mega-era sets: "any card of that rarity" per-pack odds from large-
    # sample community/TCGplayer-style data (IR ~1/9 across the Mega era; SIR and
    # Hyper drift set-to-set). Hyper/MHR biased to the conservative source so EV
    # doesn't overestimate upside.
    # Ascended Heroes (me2pt5) — loosest top end of the four.
    "me2pt5": {
        "Illustration Rare": 0.1111,          # 1 in 9
        "MEGA_ATTACK_RARE": 0.034483,         # 1 in 29 (replaced UR in the hit slot)
        "Special Illustration Rare": 0.014286,  # 1 in 70
        "Mega Hyper Rare": 0.001852,          # 1 in 540
    },
    # Perfect Order (me3) — SIR harder, Hyper pushed way out (Obsidia 3,500+ packs
    # = 1 in 1,786; conservative choice over the 1/1,260 alt).
    "me3": {
        "Illustration Rare": 0.1111,          # 1 in 9
        "Special Illustration Rare": 0.012346,  # 1 in 81
        "Mega Hyper Rare": 0.00056,           # 1 in 1,786
    },
    # Chaos Rising (me4) — SIR a touch harder than Perfect Order, Hyper a bit kinder.
    "me4": {
        "Illustration Rare": 0.1111,          # 1 in 9
        "Special Illustration Rare": 0.011111,  # 1 in 90
        "Mega Hyper Rare": 0.000909,          # 1 in 1,100
    },
    # Shrouded Fable (sv6pt5) — mini special set; cards carry STANDARD rarity
    # names in our data (not "Shiny *"). IR/SIR from community aggregates; Hyper
    # is still a small-sample estimate until a large write-up lands.
    "sv6pt5": {
        "Illustration Rare": 0.083333,        # 1 in 12 (mini set, tougher IR)
        "Special Illustration Rare": 0.014925,  # 1 in 67
        "Hyper Rare": 0.006944,               # 1 in 144 (DripShop 1,000+ packs)
        "ACE SPEC Rare": 0.05,                # 1 in 20
    },
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
