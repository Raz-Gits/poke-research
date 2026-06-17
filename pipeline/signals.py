"""Per-card feature signals for the Price Lab model.

`compute_features(cards)` turns the raw normalized-card list into a
`{card_id: {feature: value}}` table covering the FEATURES declared in
`pipeline/config.py`.

Two kinds of feature live here:

* **Live** features (`char_premium`, `scarcity`, `months_since_release`,
  `set_rank`) are derived entirely from the free pokemontcg.io data we already
  cache, so they are computed in full below.
* **Stub** features (`demand_pressure`, `grading_intensity`,
  `universal_appeal`) need a paid/scraped feed (eBay / PSA / Google Trends)
  that is not wired yet. Each is implemented as its own one-line function that
  returns a neutral mid-scale value, so the moment a real feed exists you swap
  the body of a single function and nothing else changes.

`pull_cost` is intentionally *not* computed here. It depends on
`pipeline/pullrates.py`, and the contract says `build.py` injects it at build
time (so this module stays importable and self-testable without pullrates).
Use `inject_pull_cost(features, pull_costs)` to merge it in.

Design notes
------------
* `char_premium` ranks a *character* (the card's `base_name`, e.g. "Umbreon")
  by the mean market price of all of its printings across the whole corpus,
  then converts that to a 0-10 percentile. It is blended with the character's
  rank *within its own set+rarity tier* so that, within a tier, the
  chase characters still float to the top. The result is a property of the
  character, so every printing of "Charizard" shares the same premium.
* `scarcity` blends rarity-tier rarity (rarer tier => higher) with
  `months_since_release` (older / more out-of-print => higher). It does NOT
  import pull rates — it uses the rarity-tier ordering directly so the module
  stays decoupled from pullrates; pull_cost is the precise pull-economics
  signal and is injected separately.
* `set_rank` is a 0-1 price percentile *within the card's set*.

Everything is plain stdlib + numpy.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

import numpy as np

# Rarity tiers ordered from most common (0.0) to rarest (1.0). Used by the
# scarcity signal. This is an *ordering* of tiers, independent of the precise
# pull-rate probabilities in pullrates.py (which scarcity deliberately does not
# import). Anything not listed falls back to a neutral mid rank.
RARITY_ORDER: List[str] = [
    "Common",
    "Uncommon",
    "Rare",
    "Double Rare",
    "ACE SPEC Rare",
    "Ultra Rare",
    "Shiny Rare",
    "Illustration Rare",
    "Shiny Ultra Rare",
    "Special Illustration Rare",
    "Hyper Rare",
]
_RARITY_RANK = {r: i / (len(RARITY_ORDER) - 1) for i, r in enumerate(RARITY_ORDER)}
_NEUTRAL_RARITY_RANK = 0.5

# Horizon (months) at which a card is treated as fully "aged" for the scarcity
# blend. ~5 years: old enough to be reliably out of print.
_SCARCITY_AGE_CAP_MONTHS = 60.0

# Weight split for scarcity = w_rarity * rarity_rank + w_age * age_factor.
_SCARCITY_W_RARITY = 0.7
_SCARCITY_W_AGE = 0.3

# Weight split for char_premium = w_corpus * corpus_pct + w_tier * tier_pct.
_CHARPREM_W_CORPUS = 0.6
_CHARPREM_W_TIER = 0.4


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
def _parse_date(value: Optional[str]) -> Optional[date]:
    """Parse a YYYY-MM-DD release date; return None if missing/unparseable."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def months_since_release(release_date: Optional[str], today: Optional[date] = None) -> float:
    """Whole-ish months between a card's release date and `today`.

    `today` defaults to the real current date; passing it in keeps the feature
    deterministic for tests and reproducible builds. Returns 0.0 for missing /
    future dates (never negative).
    """
    today = today or date.today()
    rel = _parse_date(release_date)
    if rel is None:
        return 0.0
    days = (today - rel).days
    if days <= 0:
        return 0.0
    return days / 30.4375  # average days per month


# ---------------------------------------------------------------------------
# Live features
# ---------------------------------------------------------------------------
def _percentile_rank(value: float, sorted_values: np.ndarray) -> float:
    """Fraction of `sorted_values` <= `value`, in [0, 1].

    `sorted_values` must be ascending. Empty input => neutral 0.5.
    """
    n = sorted_values.size
    if n == 0:
        return 0.5
    # np.searchsorted with side='right' gives the count of values <= value.
    count_le = int(np.searchsorted(sorted_values, value, side="right"))
    return count_le / n


def _char_mean_prices(cards: List[dict]) -> Dict[str, float]:
    """Mean market price per character (base_name), priced printings only."""
    by_char: Dict[str, List[float]] = defaultdict(list)
    for c in cards:
        price = c.get("market_price")
        if price is None:
            continue
        by_char[c["base_name"]].append(float(price))
    return {name: float(np.mean(prices)) for name, prices in by_char.items() if prices}


def char_premium_table(cards: List[dict]) -> Dict[str, float]:
    """Per-character premium on a 0-10 scale, keyed by base_name.

    Blends two percentiles:
      * the character's mean price vs every other character across the corpus,
      * the character's mean price vs other characters in the same
        set + rarity tier (so chase cards stand out *within* their tier too).
    """
    char_mean = _char_mean_prices(cards)
    if not char_mean:
        return {}

    # Corpus-wide percentile of each character's mean price.
    corpus_sorted = np.sort(np.fromiter(char_mean.values(), dtype=float))
    corpus_pct = {
        name: _percentile_rank(mean, corpus_sorted) for name, mean in char_mean.items()
    }

    # Within-(set, rarity) percentile. We rank a character by the mean price of
    # that character's printings that fall in the given (set, rarity) bucket,
    # then assign each character the best (max) tier percentile it achieves.
    bucket_char_prices: Dict[tuple, Dict[str, List[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for c in cards:
        price = c.get("market_price")
        if price is None:
            continue
        key = (c["set_id"], c["rarity"])
        bucket_char_prices[key][c["base_name"]].append(float(price))

    tier_pct_best: Dict[str, float] = {}
    for char_prices in bucket_char_prices.values():
        means = {name: float(np.mean(p)) for name, p in char_prices.items()}
        bucket_sorted = np.sort(np.fromiter(means.values(), dtype=float))
        for name, m in means.items():
            pct = _percentile_rank(m, bucket_sorted)
            if pct > tier_pct_best.get(name, -1.0):
                tier_pct_best[name] = pct

    premium: Dict[str, float] = {}
    for name, mean in char_mean.items():
        cp = corpus_pct.get(name, 0.5)
        tp = tier_pct_best.get(name, cp)
        blended = _CHARPREM_W_CORPUS * cp + _CHARPREM_W_TIER * tp
        premium[name] = round(10.0 * blended, 4)
    return premium


def scarcity(rarity: str, months_old: float) -> float:
    """Scarcity score 0-10: rarer tier + older release => higher.

    Blends the rarity-tier rank (0..1) with an age factor (0..1, saturating at
    `_SCARCITY_AGE_CAP_MONTHS`). Decoupled from pullrates by design.
    """
    rarity_rank = _RARITY_RANK.get(rarity, _NEUTRAL_RARITY_RANK)
    age_factor = min(months_old / _SCARCITY_AGE_CAP_MONTHS, 1.0)
    blended = _SCARCITY_W_RARITY * rarity_rank + _SCARCITY_W_AGE * age_factor
    return round(10.0 * blended, 4)


def set_rank_table(cards: List[dict]) -> Dict[str, float]:
    """Per-card 0-1 market-price percentile *within its own set*.

    Cards with no price get a neutral 0.5.
    """
    by_set: Dict[str, List[float]] = defaultdict(list)
    for c in cards:
        price = c.get("market_price")
        if price is not None:
            by_set[c["set_id"]].append(float(price))
    set_sorted = {sid: np.sort(np.array(p, dtype=float)) for sid, p in by_set.items()}

    ranks: Dict[str, float] = {}
    for c in cards:
        price = c.get("market_price")
        if price is None:
            ranks[c["id"]] = 0.5
            continue
        ranks[c["id"]] = round(_percentile_rank(float(price), set_sorted[c["set_id"]]), 4)
    return ranks


# ---------------------------------------------------------------------------
# Stub features — one function each, neutral mid value until a feed is wired.
# Swap a single body when the real data source lands; nothing else changes.
# ---------------------------------------------------------------------------
def demand_pressure_stub(card: dict) -> float:
    """STUB: eBay sold-through pressure (%). Neutral until the eBay feed lands.

    Real version: pull from market_dynamics.compute() once daily eBay snapshots
    accumulate (est_sold / total_supply).
    """
    return 0.0  # neutral: no observed demand yet (config min=0)


def grading_intensity_stub(card: dict) -> float:
    """STUB: PSA/CGC grading volume signal (0-10). Neutral mid until PSA pop feed."""
    return 5.0


def universal_appeal_stub(card: dict) -> float:
    """STUB: cross-collector desirability (0-10). Neutral mid until a Trends feed."""
    return 5.0


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def compute_features(
    cards: Iterable[dict], today: Optional[date] = None
) -> Dict[str, Dict[str, float]]:
    """Compute the live + stub feature table for every card.

    Returns ``{card_id: {feature: value}}`` covering: char_premium, scarcity,
    months_since_release, set_rank, demand_pressure, grading_intensity,
    universal_appeal.

    NOTE: ``pull_cost`` is deliberately omitted — it depends on
    ``pipeline/pullrates.py`` and is merged in by ``build.py`` via
    :func:`inject_pull_cost`. ``today`` is threaded through so months_since_release
    is reproducible.
    """
    cards = list(cards)
    char_prem = char_premium_table(cards)
    set_ranks = set_rank_table(cards)

    features: Dict[str, Dict[str, float]] = {}
    for c in cards:
        cid = c["id"]
        months = months_since_release(c.get("release_date"), today=today)
        features[cid] = {
            "char_premium": char_prem.get(c["base_name"], 0.0),
            "scarcity": scarcity(c["rarity"], months),
            "months_since_release": round(months, 4),
            "set_rank": set_ranks.get(cid, 0.5),
            "demand_pressure": demand_pressure_stub(c),
            "grading_intensity": grading_intensity_stub(c),
            "universal_appeal": universal_appeal_stub(c),
        }
    return features


def inject_pull_cost(
    features: Dict[str, Dict[str, float]], pull_costs: Dict[str, float]
) -> Dict[str, Dict[str, float]]:
    """Merge build-time ``{card_id: pull_cost}`` into an existing feature table.

    Kept separate so this module never imports ``pipeline/pullrates.py``.
    Mutates and returns ``features`` for convenience.
    """
    for cid, cost in pull_costs.items():
        if cid in features:
            features[cid]["pull_cost"] = cost
    return features


# ---------------------------------------------------------------------------
# Self-test in isolation (no pullrates import).
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    cards = json.loads((root / "data" / "normalized" / "cards.json").read_text())
    feats = compute_features(cards)

    by_id = {c["id"]: c for c in cards}

    def show(label: str, card_id: str) -> None:
        c = by_id[card_id]
        f = feats[card_id]
        print(
            f"{label:30} {card_id:14} {c['base_name']:12} "
            f"{c['rarity']:26} price=${c['market_price']:<8} "
            f"char_premium={f['char_premium']:.3f} scarcity={f['scarcity']:.3f} "
            f"set_rank={f['set_rank']:.3f}"
        )

    print("=== char_premium sanity check ===")
    show("Umbreon (SIR chase)", "sv8pt5-161")
    show("Charizard (SIR chase)", "sv3pt5-199")

    # char_premium is a CHARACTER-level signal: every printing of a character
    # shares its premium (per the contract: percentile of the character's MEAN
    # price). So for a fair contrast we want a Common whose *character* is also
    # genuinely cheap everywhere — not e.g. the Common Bulbasaur, whose mean is
    # dragged up by its $90+ Illustration Rare printings.
    char_mean = _char_mean_prices(cards)
    a_common = min(
        (c for c in cards if c["rarity"] == "Common" and c.get("market_price")),
        key=lambda c: char_mean.get(c["base_name"], 0.0),
    )
    show("A true Common (cheap char)", a_common["id"])

    umb = feats["sv8pt5-161"]["char_premium"]
    chz = feats["sv3pt5-199"]["char_premium"]
    com = feats[a_common["id"]]["char_premium"]
    print()
    print(f"Umbreon char_premium   = {umb:.3f}")
    print(f"Charizard char_premium = {chz:.3f}")
    print(f"Common  char_premium   = {com:.3f}  ({a_common['base_name']})")
    assert umb > com, "Umbreon should dominate a true Common"
    assert chz > com, "Charizard should dominate a true Common"
    assert umb > 9 and chz > 9 and com < 2, "premiums should be well separated"
    print("\nPASS: Umbreon and Charizard char_premium >> Common char_premium")
