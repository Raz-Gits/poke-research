"""eBay market collector — writes a daily per-card snapshot of live listings.

v1 is a clean **STUB**: we have no eBay API key wired yet, so
``collect_snapshot(cards)`` writes a fully-formed snapshot file in which every
card carries neutral/empty values. The *schema and the file* are the
deliverable; the moment a key exists you fill in `_fetch_card_market()` and
nothing downstream changes.

Output: ``data/snapshots/ebay-<YYYY-MM-DD>.json`` shaped as::

    {
      "<card_id>": {
        "active_listings": int | None,   # live "Buy It Now"+auction count today
        "new_listings":    int | None,   # appeared since yesterday's snapshot
        "ended_listings":  int | None,   # gone since yesterday's snapshot
        "est_sold":        int | None,   # of the ended ones, estimated SOLD
        "est_unsold":      int | None,   # of the ended ones, estimated relisted/expired
        "avg_price":       float | None  # outlier-cleaned mean active BIN price
      },
      ...
    }

In the stub, counts are ``None`` and prices ``None`` — i.e. "awaiting data".
`pipeline/market_dynamics.compute()` consumes a *history* of these files and
returns the neutral fallback until real numbers accumulate.

------------------------------------------------------------------------------
REAL eBay Browse API path (how the production collector will work)
------------------------------------------------------------------------------
The eBay Browse API (`buy.browse` scope, OAuth client-credentials token) only
returns **ACTIVE** listings — there is no public "sold/completed" endpoint
anymore. So sold-through is *inferred by diffing daily snapshots*, not read.

Per card, per day:

1. **Query active listings.** Call
   ``GET /buy/browse/v1/item_summary/search`` with a tight query, e.g.
   ``q="Umbreon ex 161 Prismatic Evolutions"`` (base_name + number + set_name),
   plus ``category_ids`` for trading cards and ``filter=buyingOptions:{FIXED_PRICE|AUCTION}``.
   Page through ``itemSummaries`` (limit 200/page, ``offset``) capturing each
   item's ``itemId``, ``price.value``, ``price.currency``, and
   ``buyingOptions``. Respect the ~5k calls/day default quota — batch by set
   and cache aggressively.

2. **Clean prices.** Drop obvious junk: graded slabs (PSA/CGC/BGS in title)
   when we want raw, lots/bundles, wrong-number variants, non-USD, and
   statistical outliers (e.g. keep prices within 1.5*IQR, or median-absolute-
   deviation filter). ``avg_price`` = mean of the cleaned active BIN prices;
   record ``active_listings`` = cleaned count.

3. **Diff against yesterday's snapshot** (the file we wrote last run) by
   ``itemId`` set:
      * ``new_listings``   = ids present today but not yesterday.
      * ``ended_listings`` = ids present yesterday but not today.
   Ended listings are the only window into demand.

4. **Estimate sold vs unsold among ended listings.** An ended fixed-price
   listing either *sold* or was *ended/expired/relisted*. Heuristics:
      * Fixed-price items that vanish well before any end date and are not
        re-listed at the same/similar price → likely SOLD.
      * Items that reappear as a *new* listing within a day or two at a similar
        price (same seller) → likely RELISTED (unsold).
      * Auctions that ended with bids (if `bidCount` was tracked) → SOLD.
   ``est_sold`` / ``est_unsold`` partition ``ended_listings`` accordingly.
   These are estimates — always surfaced as "estimated" in the UI.

5. **Write the snapshot.** Persist the per-card row above to
   ``ebay-<date>.json``. Over time the snapshot series feeds
   ``market_dynamics.compute()``:
   ``demand_pressure = est_sold / (active + est_sold)`` and
   ``supply_saturation = 7d_avg(active) / 30d_avg(active)``.

Rate-limit / hygiene notes: cache the OAuth token (it lasts ~2h), exponential
backoff on 429, and never scrape or attempt checkout — this collector only
*reads* public active listings.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

try:
    from pipeline.config import SNAPSHOTS
except Exception:  # pragma: no cover - keep collector runnable in isolation
    SNAPSHOTS = Path(__file__).resolve().parent.parent / "data" / "snapshots"


# A neutral per-card row: correct shape, no fabricated numbers.
def _empty_row() -> Dict[str, Optional[float]]:
    return {
        "active_listings": None,
        "new_listings": None,
        "ended_listings": None,
        "est_sold": None,
        "est_unsold": None,
        "avg_price": None,
    }


def _fetch_card_market(card: dict) -> Dict[str, Optional[float]]:
    """STUB hook for one card's live eBay market.

    Returns a neutral row today. Replace this body with the real Browse API
    query + price-cleaning + snapshot-diff described in the module docstring;
    `collect_snapshot` will then write real numbers with zero other changes.
    """
    return _empty_row()


def collect_snapshot(
    cards: List[dict],
    out_dir: Optional[Path] = None,
    snapshot_date: Optional[date] = None,
) -> Path:
    """Write today's eBay snapshot for every card and return the file path.

    Parameters
    ----------
    cards:
        Normalized card list (each needs at least ``id``).
    out_dir:
        Directory to write into; defaults to ``data/snapshots`` from config.
    snapshot_date:
        Date to stamp the filename with; defaults to today. Injectable so the
        collector is deterministic in tests.

    The written file maps ``card_id -> per-card schema row`` (see module
    docstring). In v1 every row is neutral/empty.
    """
    out_dir = Path(out_dir) if out_dir is not None else Path(SNAPSHOTS)
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_date = snapshot_date or date.today()

    snapshot: Dict[str, Dict[str, Optional[float]]] = {
        card["id"]: _fetch_card_market(card) for card in cards
    }

    out_path = out_dir / f"ebay-{snapshot_date.isoformat()}.json"
    out_path.write_text(json.dumps(snapshot, indent=2))
    return out_path


if __name__ == "__main__":
    # Self-test: write a stub snapshot from the cached cards and verify shape.
    root = Path(__file__).resolve().parent.parent
    cards = json.loads((root / "data" / "normalized" / "cards.json").read_text())
    path = collect_snapshot(cards)
    written = json.loads(path.read_text())
    sample_id = cards[0]["id"]
    print(f"Wrote {path} ({len(written)} cards)")
    print(f"Schema for {sample_id}: {json.dumps(written[sample_id])}")
    assert set(written[sample_id]) == set(_empty_row()), "row schema mismatch"
    print("PASS: ebay stub snapshot written with documented neutral schema")
