"""Plain-language market-signal labels (the "market divergence" layer).

This is a RULES layer, not a model. It fuses three observed signals into one
short English verdict per card so a reader doesn't have to assemble the gauges
into a story themselves:

  * price move   — recent % change from the daily ``snapshot-<date>.json`` price
                   history (``load_price_history`` / ``price_move``).
  * demand       — ``dynamics.demand_pressure`` (sell-through % = est_sold(7d) /
                   (active + est_sold), from the eBay snapshot feed).
  * supply       — ``dynamics.supply_saturation`` (mean active 7d / 30d).

IMPORTANT — what this is NOT:
  * NOT a price prediction. The labels DESCRIBE what the market has recently done;
    they make no claim about the future.
  * NOT a model input. ``demand_pressure``/``supply_saturation`` deliberately do
    NOT feed ``expected_price`` (see config.FEATURES / the 2026-06-21 audit) —
    that signal is still data-blocked for *prediction* and must clear a forward
    backtest first. Describing the market in a label carries no look-ahead risk;
    feeding it into the price estimate would. We keep the two strictly separate.

GRACEFUL DEGRADATION (auto-lights as the feed matures):
  * Only ~few days of history -> ``supply_saturation`` is exactly 1.0 (the 7d and
    30d windows coincide) so supply/"cooling" clauses cannot fire. We never assert
    cooling/loosening from a *low* demand level (low sell-through is the noisy
    default, not a signal) — only from real supply build (sat > LOOSEN) or, in the
    future, a measured demand DROP. Cooling clauses light up automatically once
    there is >7 days of span.
  * A card with no eBay sweep (``status != 'ok'``) gets a PRICE-ONLY label, badged
    ``confidence='price_only'`` so the UI is honest about not having the flow feed.
  * No price history AND no flow -> ``confidence='none'`` ("awaiting data").

Pure stdlib. Import-safe (no project imports).
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import json

try:  # thresholds live in config; fall back to these in isolation / self-test
    from pipeline.config import (
        SIGNAL_PRICE_WINDOW_DAYS,
        SIGNAL_PRICE_UP_PCT,
        SIGNAL_PRICE_DOWN_PCT,
        SIGNAL_DEMAND_HOT,
        SIGNAL_SAT_TIGHTEN,
        SIGNAL_SAT_LOOSEN,
    )
except Exception:  # pragma: no cover - keep self-testable
    SIGNAL_PRICE_WINDOW_DAYS = 7
    SIGNAL_PRICE_UP_PCT = 3.0
    SIGNAL_PRICE_DOWN_PCT = -3.0
    SIGNAL_DEMAND_HOT = 15.0
    SIGNAL_SAT_TIGHTEN = 0.97
    SIGNAL_SAT_LOOSEN = 1.03


# ---------------------------------------------------------------------------
# Price history (daily snapshot-<date>.json = {card_id: market_price})
# ---------------------------------------------------------------------------
def load_price_history(snap_dir, as_of: Optional[date] = None
                       ) -> Dict[str, List[Tuple[date, float]]]:
    """Load ``snapshot-<date>.json`` price files into ``{card_id: [(date, price)]}``.

    ``as_of`` (AS-OF GATE): snapshots dated after ``as_of`` are skipped, so a
    backtest recomputing the label at a historical date never reads a future
    price. Files whose date doesn't parse are dropped (not mis-anchored). Each
    card's series is returned sorted ascending by date.
    """
    snap_dir = Path(snap_dir)
    hist: Dict[str, List[Tuple[date, float]]] = {}
    for f in sorted(snap_dir.glob("snapshot-*.json")):
        datestr = f.stem.replace("snapshot-", "")  # snapshot-YYYY-MM-DD.json
        try:
            d = datetime.strptime(datestr, "%Y-%m-%d").date()
        except ValueError:
            continue
        if as_of is not None and d > as_of:
            continue
        try:
            rows = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(rows, dict):
            continue
        for cid, price in rows.items():
            if price is None:
                continue
            try:
                p = float(price)
            except (TypeError, ValueError):
                continue
            if p <= 0:
                continue
            hist.setdefault(cid, []).append((d, p))
    for cid in hist:
        hist[cid].sort(key=lambda t: t[0])
    return hist


def price_move(series: Optional[List[Tuple[date, float]]],
               window_days: int = SIGNAL_PRICE_WINDOW_DAYS,
               as_of: Optional[date] = None) -> Optional[dict]:
    """Recent % price move for one card from its ``(date, price)`` series.

    Compares the latest price (on/before ``as_of``) to the earliest price within
    ``window_days`` of it (or the earliest available point if the series is
    shorter than the window). Returns ``{pct, days, from_price, to_price, n}`` or
    ``None`` when there are fewer than two usable points.
    """
    if not series:
        return None
    pts = series if as_of is None else [(d, p) for d, p in series if d <= as_of]
    if len(pts) < 2:
        return None
    latest_d, latest_p = pts[-1]
    # earliest point still inside the window ending at latest_d
    base_d, base_p = pts[0]
    for d, p in pts:
        if (latest_d - d).days <= window_days:
            base_d, base_p = d, p
            break
    if base_p <= 0 or base_d == latest_d:
        return None
    pct = round(100.0 * (latest_p - base_p) / base_p, 2)
    return {
        "pct": pct,
        "days": (latest_d - base_d).days,
        "from_price": round(base_p, 2),
        "to_price": round(latest_p, 2),
        "n": len(pts),
    }


# ---------------------------------------------------------------------------
# Market state + label fusion
# ---------------------------------------------------------------------------
def _price_state(pm: Optional[dict]) -> str:
    """'up' | 'down' | 'flat' | 'unknown' from a price_move dict."""
    if pm is None or pm.get("pct") is None:
        return "unknown"
    pct = pm["pct"]
    if pct >= SIGNAL_PRICE_UP_PCT:
        return "up"
    if pct <= SIGNAL_PRICE_DOWN_PCT:
        return "down"
    return "flat"


def _market_state(dynamics: Optional[dict]) -> str:
    """'tightening' | 'loosening' | 'steady' | 'unknown' from dynamics.

    'unknown'  -> no live eBay read for this card (status != 'ok'): we never
                  invent a flow story we can't see.
    'tightening' -> firm sell-through (demand_pressure >= HOT) OR real supply
                    contraction (saturation < TIGHTEN).
    'loosening' -> real supply build (saturation > LOOSEN). We do NOT loosen on a
                   *low* demand level — low sell-through is the noisy default, not
                   a measured cooldown; this clause stays dark until there's
                   enough span for saturation to move (or a future demand-drop
                   signal), then lights up on its own.
    'steady'   -> we looked and nothing is notable.
    """
    d = dynamics or {}
    if d.get("status") != "ok":
        return "unknown"
    dp = d.get("demand_pressure")
    sat = d.get("supply_saturation")
    tighten = (dp is not None and dp >= SIGNAL_DEMAND_HOT) or \
              (sat is not None and sat < SIGNAL_SAT_TIGHTEN)
    loosen = sat is not None and sat > SIGNAL_SAT_LOOSEN
    if tighten and not loosen:
        return "tightening"
    if loosen and not tighten:
        return "loosening"
    return "steady"


# (price_state, market_state) -> (label, tone)
_LABELS = {
    ("up", "tightening"):   ("Heating up", "hot"),
    ("up", "loosening"):    ("Overextended — price up, supply building", "caution"),
    ("up", "steady"):       ("Rising — no clear market driver", "warm"),
    ("up", "unknown"):      ("Rising", "warm"),
    ("down", "tightening"): ("Opportunity — dipping with firm demand", "opportunity"),
    ("down", "loosening"):  ("Cooling — price and demand sliding", "cold"),
    ("down", "steady"):     ("Easing", "cool"),
    ("down", "unknown"):    ("Falling", "cool"),
    ("flat", "tightening"): ("Demand building", "warm"),
    ("flat", "loosening"):  ("Supply building", "cool"),
    ("flat", "steady"):     ("Quiet — no recent divergence", "neutral"),
    ("flat", "unknown"):    ("Quiet", "neutral"),
}


def _detail(pm: Optional[dict], dynamics: Optional[dict]) -> str:
    """Human-readable supporting numbers, only for parts we actually have."""
    parts: List[str] = []
    if pm and pm.get("pct") is not None:
        sign = "+" if pm["pct"] >= 0 else ""
        span = f"{pm['days']}d" if pm.get("days") else "recent"
        parts.append(f"price {sign}{pm['pct']:.1f}% ({span})")
    d = dynamics or {}
    if d.get("status") == "ok":
        dp = d.get("demand_pressure")
        if dp is not None:
            parts.append(f"sell-through {dp:.0f}%")
        sat = d.get("supply_saturation")
        if sat is not None and abs(sat - 1.0) >= (1 - SIGNAL_SAT_TIGHTEN):
            parts.append(f"supply ×{sat:.2f}")
    return " · ".join(parts)


def compute_signal(pm: Optional[dict], dynamics: Optional[dict]) -> dict:
    """Fuse price move + market dynamics into one plain-language label.

    Returns ``{label, tone, detail, confidence, basis}``:
      * ``confidence='full'``       — both price and a live eBay flow read.
      * ``confidence='price_only'`` — price move but no eBay sweep for this card.
      * ``confidence='none'``       — neither (awaiting data).
    """
    ps = _price_state(pm)
    ms = _market_state(dynamics)

    if ps == "unknown" and ms == "unknown":
        return {
            "label": "Awaiting data",
            "tone": "neutral",
            "detail": "",
            "confidence": "none",
            "basis": {"price_state": ps, "market_state": ms},
        }

    # No price history yet, but we DO have a live flow read -> lead with the market.
    if ps == "unknown":
        label, tone = _LABELS[("flat", ms)]
        if ms == "tightening":
            label, tone = "Demand building", "warm"
        elif ms == "loosening":
            label, tone = "Supply building", "cool"
        else:
            label, tone = "Quiet — no recent divergence", "neutral"
    else:
        label, tone = _LABELS[(ps, ms)]

    confidence = "full" if ms != "unknown" else "price_only"
    return {
        "label": label,
        "tone": tone,
        "detail": _detail(pm, dynamics),
        "confidence": confidence,
        "basis": {
            "price_state": ps,
            "market_state": ms,
            "price_pct": (pm or {}).get("pct"),
            "demand_pressure": (dynamics or {}).get("demand_pressure"),
            "supply_saturation": (dynamics or {}).get("supply_saturation"),
        },
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    OK = lambda d: dict(d, status="ok")
    cases = [
        ("price up + hot demand",   {"pct": 8.0, "days": 7}, OK({"demand_pressure": 30.0, "supply_saturation": 1.0})),
        ("price down + hot demand", {"pct": -6.0, "days": 7}, OK({"demand_pressure": 25.0, "supply_saturation": 1.0})),
        ("price up + calm",         {"pct": 5.0, "days": 7}, OK({"demand_pressure": 1.0, "supply_saturation": 1.0})),
        ("price flat + calm",       {"pct": 0.5, "days": 7}, OK({"demand_pressure": 1.0, "supply_saturation": 1.0})),
        ("price up + no feed",      {"pct": 5.0, "days": 7}, {"status": "awaiting_data"}),
        ("no price + hot demand",   None,                    OK({"demand_pressure": 40.0, "supply_saturation": 1.0})),
        ("nothing",                 None,                    {"status": "awaiting_data"}),
        ("price up + supply build", {"pct": 5.0, "days": 9}, OK({"demand_pressure": 2.0, "supply_saturation": 1.10})),
    ]
    print(f"{'case':<26} {'label':<42} {'tone':<12} conf")
    print("-" * 92)
    for name, pm, dyn in cases:
        s = compute_signal(pm, dyn)
        print(f"{name:<26} {s['label']:<42} {s['tone']:<12} {s['confidence']}")
