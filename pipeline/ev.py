"""Sealed-product expected value (EV) for Poke Research.

Given the cards in a set, the set record (pack/box pricing), and the
rarity-count table, estimate how much *card value* a sealed pack/box yields on
average, and compare that to what the sealed product actually costs.

EV math (per CONTRACT.md)::

    ev_per_pack = Σ over cards (pull_rate_card * market_price_card)   # skip None
    ev_per_box  = ev_per_pack * packs_per_box
    signal_pct  = (ev_per_box - box_price) / box_price               # >0 undervalued
    avg_loss_per_pack = pack_price - ev_per_pack
    raw_value_per_pack = ev_per_pack

``ev_per_pack`` is the sum of each card's per-pack pull rate times its market
price. Because pull rates for guaranteed slots (Common/Uncommon/Rare) sum to
~1 per slot and the chase tiers are fractional, this naturally approximates the
blended expected single-card value of a pack.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from . import pullrates


def ev_for_set(
    cards_in_set: Iterable[Mapping],
    set_record: Mapping,
    counts: Mapping[str, Mapping[str, int]],
) -> dict:
    """Compute sealed EV for one set.

    Parameters
    ----------
    cards_in_set:
        NormalizedCard mappings belonging to this set (each has ``rarity``,
        ``set_id``, ``market_price``).
    set_record:
        SetRecord mapping with ``set_id``, ``pack_price``, ``packs_per_box`` and
        ``box_price``.
    counts:
        Rarity-count table from :func:`pullrates.rarity_counts`.

    Returns
    -------
    dict
        ``{ev_per_pack, ev_per_box, signal_pct, avg_loss_per_pack,
        raw_value_per_pack}``. ``signal_pct`` is ``None`` if there is no positive
        box price to compare against.
    """
    set_id = set_record["set_id"]
    pack_price = set_record["pack_price"]
    packs_per_box = set_record["packs_per_box"]

    # box_price may be given explicitly; otherwise fall back to pack * packs.
    box_price = set_record.get("box_price")
    if box_price is None:
        box_price = pack_price * packs_per_box

    # Expected card value contributed by a single pack: sum each card's per-pack
    # pull rate weighted by its market price (skip unpriced cards).
    ev_per_pack = 0.0
    for card in cards_in_set:
        price = card.get("market_price")
        if price is None:
            continue
        rate = pullrates.pull_rate(card["rarity"], set_id, counts)
        ev_per_pack += rate * price

    ev_per_box = ev_per_pack * packs_per_box

    # Box undervaluation signal: positive => sealed box is cheaper than the
    # expected value of cards inside (undervalued); negative => overvalued.
    if box_price and box_price > 0:
        signal_pct = (ev_per_box - box_price) / box_price
    else:
        signal_pct = None

    return {
        "ev_per_pack": ev_per_pack,
        "ev_per_box": ev_per_box,
        "signal_pct": signal_pct,
        "avg_loss_per_pack": pack_price - ev_per_pack,
        "raw_value_per_pack": ev_per_pack,
    }
