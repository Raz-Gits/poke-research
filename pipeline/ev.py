"""Sealed-product expected value (EV) for Poke Research.

Given the cards in a set, the set record (pack/ETB pricing), and the
rarity-count table, estimate how much *card value* a sealed pack/ETB yields on
average, and compare that to what the sealed product actually costs.

EV math, reported BOTH ways so a single loose pack and a sealed Elite Trainer
Box can be compared::

    ev_per_pack    = Σ over cards (pull_rate_card * market_price_card)   # skip None
    pack_signal    = (ev_per_pack - pack_price) / pack_price             # rip 1 pack
    ev_per_etb     = ev_per_pack * packs_per_etb
    etb_signal     = (ev_per_etb - etb_price) / etb_price                # buy an ETB
    signal_pct     = etb_signal   # primary (sealed-product verdict)

``ev_per_pack`` is the sum of each card's per-pack pull rate times its market
price. Because pull rates for guaranteed slots (Common/Uncommon/Rare) sum to ~1
per slot and the chase tiers are fractional, this naturally approximates the
blended expected single-card value of a pack. We use ETBs (9 packs) rather than
booster boxes because every set ships an ETB while boxes don't exist for the
special / Mega-era sets.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional

from . import pullrates


def _signal(value: float, cost: Optional[float]) -> Optional[float]:
    """(value - cost) / cost, or None when there's no positive cost to compare."""
    if cost and cost > 0:
        return (value - cost) / cost
    return None


def ev_for_set(
    cards_in_set: Iterable[Mapping],
    set_record: Mapping,
    counts: Mapping[str, Mapping[str, int]],
) -> dict:
    """Compute sealed EV for one set, per-pack and per-ETB.

    Parameters
    ----------
    cards_in_set:
        NormalizedCard mappings belonging to this set (each has ``rarity``,
        ``set_id``, ``market_price``).
    set_record:
        SetRecord mapping with ``set_id``, ``pack_price``, ``packs_per_etb`` and
        ``etb_price``.
    counts:
        Rarity-count table from :func:`pullrates.rarity_counts`.

    Returns
    -------
    dict
        ``{ev_per_pack, pack_price, pack_signal_pct, packs_per_etb, etb_price,
        ev_per_etb, etb_signal_pct, signal_pct, avg_loss_per_pack,
        raw_value_per_pack}``. ``signal_pct`` mirrors ``etb_signal_pct`` (the
        primary sealed-product verdict); signals are ``None`` if the matching
        price is missing/zero.
    """
    set_id = set_record["set_id"]
    pack_price = set_record.get("pack_price")
    packs_per_etb = set_record.get("packs_per_etb", 9)
    etb_price = set_record.get("etb_price")

    # Expected card value contributed by a single pack: sum each card's per-pack
    # pull rate weighted by its market price (skip unpriced cards).
    ev_per_pack = 0.0
    for card in cards_in_set:
        price = card.get("market_price")
        if price is None:
            continue
        rate = pullrates.pull_rate(card["rarity"], set_id, counts)
        ev_per_pack += rate * price

    ev_per_etb = ev_per_pack * packs_per_etb
    pack_signal_pct = _signal(ev_per_pack, pack_price)
    etb_signal_pct = _signal(ev_per_etb, etb_price)

    return {
        "ev_per_pack": ev_per_pack,
        "pack_price": pack_price,
        "pack_signal_pct": pack_signal_pct,
        "packs_per_etb": packs_per_etb,
        "etb_price": etb_price,
        "ev_per_etb": ev_per_etb,
        "etb_signal_pct": etb_signal_pct,
        # Primary verdict = the sealed-product (ETB) signal; positive => the
        # cards inside an ETB are worth more than the ETB costs (undervalued).
        "signal_pct": etb_signal_pct,
        "avg_loss_per_pack": (pack_price - ev_per_pack) if pack_price else None,
        "raw_value_per_pack": ev_per_pack,
    }
