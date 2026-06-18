"""Market-dynamics signals derived from daily eBay snapshots.

The eBay Browse API only exposes *active* listings, so we cannot read sold
counts directly. Instead ``collectors/ebay.py`` writes one snapshot per day
(``data/snapshots/ebay-<date>.json``) and we infer flow by diffing consecutive
snapshots over time (``collectors.ebay.diff_snapshots``). This module turns the
snapshot *history* into two interpretable signals, per the build contract:

* ``demand_pressure`` = est_sold(last 7d) / total_supply (active + est_sold),
  as a percent — a sell-through rate: of the available + recently-sold supply,
  how much actually moved this week. Higher => hotter demand.
* ``supply_saturation`` = mean(active last 7d) / mean(active last 30d)
  ( >1 => supply loosening / cooling, <1 => supply tightening / heating ).

Until a card has at least two days of eBay history we return an explicit
neutral fallback with ``status="awaiting_data"`` so the frontend can badge it
honestly rather than implying we have a feed we don't.

Pure stdlib + numpy. Import-safe: the only project import is
``collectors.ebay.diff_snapshots`` (used to backfill flow fields), guarded so
the module still self-tests in isolation.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

try:  # window sizes live in config; fall back to sane defaults in isolation
    from pipeline.config import DYN_SHORT_WINDOW, DYN_LONG_WINDOW
except Exception:  # pragma: no cover - keeps the module self-testable
    DYN_SHORT_WINDOW, DYN_LONG_WINDOW = 7, 30

try:  # only used to backfill new/ended/est_sold/est_unsold from raw counts
    from collectors.ebay import diff_row
except Exception:  # pragma: no cover - keep import-safe in isolation
    diff_row = None  # type: ignore[assignment]


# Neutral result when we have <2 days of eBay history for a card.
NEUTRAL = {
    "demand_pressure": None,
    "supply_saturation": 1.0,
    "status": "awaiting_data",
}


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# History loading
# ---------------------------------------------------------------------------
def load_history(snap_dir) -> Dict[str, List[dict]]:
    """Load every ``ebay-<date>.json`` snapshot into per-card history.

    Reads all ``ebay-<YYYY-MM-DD>.json`` files in ``snap_dir`` in date order,
    stamps each per-card row with its file ``date``, and groups them into
    ``{card_id: [row, ...]}`` sorted ascending by date.

    For each card we then walk consecutive days and apply
    ``collectors.ebay.diff_snapshots(prev, curr)`` to BACKFILL the flow fields
    (``new_listings``/``ended_listings``/``est_sold``/``est_unsold``) on any day
    where they are missing — so the snapshot files only need to carry
    ``active_listings`` (+ optional ``item_ids``) and the demand math still
    works. Rows that already carry those fields are left untouched.

    Returns
    -------
    dict
        ``{card_id: [rows sorted by date]}``. Empty if the directory has no
        snapshot files.
    """
    snap_dir = Path(snap_dir)
    history: Dict[str, List[dict]] = {}
    for f in sorted(snap_dir.glob("ebay-*.json")):
        snap_date = f.stem.replace("ebay-", "")  # ebay-YYYY-MM-DD.json
        try:
            rows = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(rows, dict):
            continue
        for card_id, row in rows.items():
            if not isinstance(row, dict):
                continue
            stamped = dict(row)
            stamped["date"] = snap_date
            history.setdefault(card_id, []).append(stamped)

    # Sort each card's rows by date, then backfill flow fields via day-over-day
    # diff so demand_pressure has est_sold to work with even from counts-only
    # snapshots.
    for card_id, rows in history.items():
        rows.sort(key=_snap_date)
        if diff_row is None:
            continue
        prev: Optional[dict] = None
        filled: List[dict] = []
        for row in rows:
            merged = diff_row(prev, row)
            merged["date"] = row.get("date")
            filled.append(merged)
            prev = merged
        history[card_id] = filled
    return history


# ---------------------------------------------------------------------------
# Windowed aggregates
# ---------------------------------------------------------------------------
def _recent(snaps: List[dict], window: int) -> List[dict]:
    """Most-recent ``window`` snapshots (snaps must be sorted ascending)."""
    return snaps[-window:] if window > 0 else list(snaps)


def _window_active_mean(snaps: List[dict], window: int) -> Optional[float]:
    """Mean ``active_listings`` over the most recent ``window`` snapshots."""
    vals = [
        float(s["active_listings"])
        for s in _recent(snaps, window)
        if s.get("active_listings") is not None
    ]
    if not vals:
        return None
    return float(np.mean(vals))


def _window_sum(snaps: List[dict], window: int, key: str) -> Optional[float]:
    """Sum of ``key`` over the most recent ``window`` snapshots (None if none)."""
    vals = [
        float(s[key])
        for s in _recent(snaps, window)
        if s.get(key) is not None
    ]
    if not vals:
        return None
    return float(sum(vals))


# ---------------------------------------------------------------------------
# Public compute
# ---------------------------------------------------------------------------
def compute(card_id: str, history: Dict[str, List[dict]]) -> dict:
    """Compute market-dynamics signals for one card from its snapshot history.

    Parameters
    ----------
    card_id:
        The card to compute for.
    history:
        ``{card_id: [row, ...]}`` as produced by :func:`load_history` — each row
        is a per-card snapshot row carrying a ``date`` and (after backfill) the
        flow fields. Rows may be in any order; we sort by date defensively.

    Returns
    -------
    dict
        ``{demand_pressure, supply_saturation, active_listings, sold_7d,
        new_7d, status, basis}``. With fewer than two days of history we return
        the NEUTRAL ``awaiting_data`` fallback (still shaped so the frontend can
        read every key).

    Math (from the contract)
    ------------------------
    * ``demand_pressure`` = 100 * est_sold(7d) / (latest active + est_sold(7d))
    * ``supply_saturation`` = mean(active 7d) / mean(active 30d)
    """
    snaps = history.get(card_id) or []
    snaps = sorted(snaps, key=_snap_date)

    # Need at least two days to infer any flow at all.
    if len(snaps) < 2:
        out = dict(NEUTRAL)
        latest_active = snaps[-1].get("active_listings") if snaps else None
        out["active_listings"] = latest_active
        out["sold_7d"] = None
        out["new_7d"] = None
        out["basis"] = {"days": len(snaps)}
        return out

    latest = snaps[-1]
    active = latest.get("active_listings")

    sold_7d = _window_sum(snaps, DYN_SHORT_WINDOW, "est_sold")
    new_7d = _window_sum(snaps, DYN_SHORT_WINDOW, "new_listings")

    # --- demand_pressure = est_sold(7d) / total_supply (%) -----------------
    demand_pressure: Optional[float] = None
    if sold_7d is not None and active is not None:
        total_supply = float(active) + float(sold_7d)
        if total_supply > 0:
            demand_pressure = round(100.0 * float(sold_7d) / total_supply, 4)

    # --- supply_saturation = mean(active 7d) / mean(active 30d) ------------
    short_avg = _window_active_mean(snaps, DYN_SHORT_WINDOW)
    long_avg = _window_active_mean(snaps, DYN_LONG_WINDOW)
    if short_avg is not None and long_avg is not None and long_avg > 0:
        supply_saturation = round(short_avg / long_avg, 4)
    else:
        supply_saturation = 1.0  # not enough span to detect a shift

    # If we genuinely learned nothing, stay honest about it.
    if demand_pressure is None and supply_saturation == 1.0:
        out = dict(NEUTRAL)
        out["active_listings"] = active
        out["sold_7d"] = sold_7d
        out["new_7d"] = new_7d
        out["basis"] = {
            "days": len(snaps),
            "short_window": DYN_SHORT_WINDOW,
            "long_window": DYN_LONG_WINDOW,
        }
        return out

    return {
        "demand_pressure": demand_pressure,
        "supply_saturation": supply_saturation,
        "active_listings": active,
        "sold_7d": sold_7d,
        "new_7d": new_7d,
        "status": "ok",
        "basis": {
            "days": len(snaps),
            "short_window": DYN_SHORT_WINDOW,
            "long_window": DYN_LONG_WINDOW,
            "short_active_avg": None if short_avg is None else round(short_avg, 4),
            "long_active_avg": None if long_avg is None else round(long_avg, 4),
        },
    }


# ---------------------------------------------------------------------------
# Self-test in isolation
# ---------------------------------------------------------------------------
def _synthesize_history() -> Dict[str, List[dict]]:
    """Build a tiny 8-day counts-only history exercising all three regimes.

    Each row carries only ``active_listings`` + ``date``; load_history's diff
    backfill (here applied manually) derives the flow fields. We craft:

    * ``TIGHT`` — active shrinks day over day (supply tightening, <1).
    * ``LOOSE`` — active grows day over day (supply loosening, >1).
    * ``FLAT``  — active roughly constant (saturation ~1.0).
    """
    from datetime import date, timedelta

    base = date(2026, 6, 11)
    days = [(base + timedelta(days=i)).isoformat() for i in range(8)]

    series = {
        "TIGHT": [120, 110, 98, 90, 80, 70, 60, 52],   # selling down -> tightening
        "LOOSE": [40, 46, 52, 60, 66, 74, 82, 90],     # piling up -> loosening
        "FLAT": [75, 76, 74, 75, 75, 76, 74, 75],      # steady
    }
    raw: Dict[str, List[dict]] = {}
    for cid, vals in series.items():
        raw[cid] = [
            {"active_listings": v, "date": d} for v, d in zip(vals, days)
        ]
    return raw


def _backfill_inline(raw: Dict[str, List[dict]]) -> Dict[str, List[dict]]:
    """Apply diff_snapshots day-over-day (mirrors load_history's backfill)."""
    out: Dict[str, List[dict]] = {}
    for cid, rows in raw.items():
        rows = sorted(rows, key=_snap_date)
        prev: Optional[dict] = None
        filled: List[dict] = []
        for row in rows:
            if diff_row is not None:
                merged = diff_row(prev, row)
            else:  # pragma: no cover
                merged = dict(row)
            merged["date"] = row.get("date")
            filled.append(merged)
            prev = merged
        out[cid] = filled
    return out


if __name__ == "__main__":
    # When run standalone (`python pipeline/market_dynamics.py`) the project
    # root isn't on sys.path, so the top-level `from collectors.ebay import
    # diff_snapshots` would have failed and left diff_snapshots=None. Make the
    # root importable and load it now so the demo exercises the full flow math
    # (running as `-m pipeline.market_dynamics` already has it).
    if diff_row is None:  # type: ignore[truthy-function]
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        try:
            from collectors.ebay import diff_row  # type: ignore[no-redef]
        except Exception:
            diff_row = None  # type: ignore[assignment]

    snap_dir = Path(__file__).resolve().parent.parent / "data" / "snapshots"
    have_files = any(snap_dir.glob("ebay-*.json"))

    history: Dict[str, List[dict]] = {}
    usable = False
    if have_files:
        print(f"Loading real snapshot history from {snap_dir}")
        history = load_history(snap_dir)
        n_days = max((len(v) for v in history.values()), default=0)
        # "Usable" = at least one card with >=2 days AND a real active count.
        usable = any(
            len(rows) >= 2
            and sum(1 for r in rows if r.get("active_listings") is not None) >= 2
            for rows in history.values()
        )
        print(
            f"  cards in history: {len(history)} | max days/card: {n_days} | "
            f"usable active-count history: {usable}"
        )

    if not usable:
        if have_files:
            print(
                "  Real snapshots are the awaiting-data stub (active_listings "
                "all null) -> synthesizing an 8-day history to exercise the math.\n"
            )
        else:
            print("No snapshot files found -> synthesizing an 8-day history.\n")
        history = _backfill_inline(_synthesize_history())
        sample = ["TIGHT", "LOOSE", "FLAT"]
    else:
        # Pick three real cards spanning the saturation regimes.
        scored = []
        for cid in history:
            d = compute(cid, history)
            if d.get("status") == "ok":
                scored.append((d["supply_saturation"], cid))
        scored.sort()
        sample = []
        if scored:
            sample = [scored[0][1], scored[-1][1], scored[len(scored) // 2][1]]
        if len(sample) < 3:  # fall back to fill the trio
            sample = (sample + list(history.keys()))[:3]

    print(f"{'card_id':<10} {'demand_%':>9} {'saturation':>11}  status")
    print("-" * 48)
    for cid in sample:
        d = compute(cid, history)
        dp = d["demand_pressure"]
        dp_s = "None" if dp is None else f"{dp:.3f}"
        print(
            f"{cid:<10} {dp_s:>9} {d['supply_saturation']:>11}  {d['status']}"
        )
        regime = (
            "tightening" if d["supply_saturation"] < 1
            else "loosening" if d["supply_saturation"] > 1
            else "flat"
        )
        print(
            f"           active={d.get('active_listings')} "
            f"sold_7d={d.get('sold_7d')} new_7d={d.get('new_7d')} -> {regime}"
        )
