"""Market-dynamics signals derived from daily eBay snapshots.

The eBay Browse API only exposes *active* listings, so we cannot read sold
counts directly. Instead `collectors/ebay.py` writes one snapshot per day
(`data/snapshots/ebay-<date>.json`) and we infer flow by diffing consecutive
snapshots over time. This module turns a per-card list of those snapshots into
two interpretable signals:

* ``demand_pressure`` = est_sold / total_supply  (a sell-through rate, %):
  how much of the available + sold supply actually moved. Higher => hotter.
* ``supply_saturation`` = supply_7d_avg / supply_30d_avg
  ( >1 => supply loosening / cooling, <1 => supply tightening / heating ).

Until a card has any eBay history we return an explicit neutral fallback with
``status="awaiting_data"`` so the frontend can badge it honestly rather than
implying we have a feed we don't.

Pure stdlib + numpy.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

try:  # window sizes live in config; fall back to sane defaults in isolation
    from pipeline.config import DYN_SHORT_WINDOW, DYN_LONG_WINDOW
except Exception:  # pragma: no cover - keeps the module self-testable
    DYN_SHORT_WINDOW, DYN_LONG_WINDOW = 7, 30


# Neutral result when we have no eBay history for a card yet.
NEUTRAL = {"demand_pressure": None, "supply_saturation": 1.0, "status": "awaiting_data"}


def _snap_date(snap: dict) -> datetime:
    """Best-effort parse of a snapshot's date; missing => epoch (sorts first)."""
    raw = snap.get("date")
    if not raw:
        return datetime.min
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except (ValueError, TypeError):
            continue
    return datetime.min


def _window_supply_avg(snaps: List[dict], window: int) -> Optional[float]:
    """Mean active-listing supply over the most recent `window` snapshots.

    Snapshots must already be sorted ascending by date. Returns None if there
    are no usable `active_listings` values in the window.
    """
    recent = snaps[-window:] if window > 0 else snaps
    vals = [
        float(s["active_listings"])
        for s in recent
        if s.get("active_listings") is not None
    ]
    if not vals:
        return None
    return float(np.mean(vals))


def compute(card_id: str, ebay_snaps: Dict[str, List[dict]]) -> dict:
    """Compute market-dynamics signals for one card from its eBay snapshots.

    Parameters
    ----------
    card_id:
        The card to compute for.
    ebay_snaps:
        ``{card_id: [snapshot, ...]}`` where each snapshot follows the
        ``collectors/ebay.py`` per-card schema and additionally carries a
        ``date`` key (the collector stamps the file date onto each row when
        loading history). Snapshots may be in any order — we sort by date.

    Returns
    -------
    dict
        ``{"demand_pressure": float|None, "supply_saturation": float,
        "status": str}``. With no history => the NEUTRAL fallback.
    """
    snaps = ebay_snaps.get(card_id) or []
    if not snaps:
        return dict(NEUTRAL)

    snaps = sorted(snaps, key=_snap_date)
    latest = snaps[-1]

    # --- demand_pressure = est_sold / total_supply -------------------------
    est_sold = latest.get("est_sold")
    active = latest.get("active_listings")
    # total_supply = what's still listed (active) + what we estimate already
    # sold over the observed window. Guards against div-by-zero.
    demand_pressure: Optional[float] = None
    if est_sold is not None and active is not None:
        total_supply = float(active) + float(est_sold)
        if total_supply > 0:
            demand_pressure = round(100.0 * float(est_sold) / total_supply, 4)

    # --- supply_saturation = 7d avg / 30d avg ------------------------------
    short_avg = _window_supply_avg(snaps, DYN_SHORT_WINDOW)
    long_avg = _window_supply_avg(snaps, DYN_LONG_WINDOW)
    if short_avg is not None and long_avg is not None and long_avg > 0:
        supply_saturation = round(short_avg / long_avg, 4)
    else:
        supply_saturation = 1.0  # not enough history to detect a shift

    # If we genuinely learned nothing (no demand and no real saturation
    # signal), surface it as awaiting_data rather than faking confidence.
    if demand_pressure is None and supply_saturation == 1.0:
        return dict(NEUTRAL)

    return {
        "demand_pressure": demand_pressure,
        "supply_saturation": supply_saturation,
        "status": "ok",
    }
