"""Build orchestrator for Poke Research.

This is the single command that turns the cached, normalized pokemontcg.io data
into the JSON the static frontend consumes. It wires every owned module together
in the order the contract mandates and writes ``site/data/*.json``.

Pipeline (see CONTRACT.md, "Build orchestrator")::

    load cached normalized cards/sets
      -> pullrates.rarity_counts
      -> ev.ev_for_set            (per set)
      -> signals.compute_features
      -> inject real pull_cost     (pullrates.pull_cost per card)
      -> market_dynamics.compute   (stub; eBay snapshot history)
      -> model.fit + model.export
      -> iq_score                  (0-100 blend of scarcity, char_premium, set_rank)
      -> write site/data/{cards,sets,leaderboard,model,meta}.json

Run from the project root::

    ./.venv/bin/python -m pipeline.build

Only the standard library and numpy are used (numpy lives inside the owned
modules; build.py itself is pure stdlib).
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from . import config, ev, market_dynamics, model, pullrates, sealed_market, signal_labels, signals
from collectors import ebay


# ---------------------------------------------------------------------------
# IQ score
# ---------------------------------------------------------------------------
# The IQ score is the at-a-glance "card score" (0-100): a weighted mean of the
# card's normalized live signals. It is intentionally separate from
# residual_pct (the over/under-valuation signal). scarcity and char_premium are
# already on a 0-10 scale; set_rank is already 0-1. We normalize each to 0-1
# and blend. momentum (a price/saturation trend) is folded in only when real
# market history exists; with the eBay feed stubbed it is absent, so the blend
# uses the three live signals.
IQ_WEIGHTS = {
    "scarcity": 0.40,       # rarity + out-of-print pressure
    "char_premium": 0.35,   # character desirability
    "set_rank": 0.25,       # standing within its own set
}


def iq_score(feats: Dict[str, float], momentum: Optional[float] = None) -> float:
    """Blend a card's live signals into a 0-100 IQ score.

    Parameters
    ----------
    feats:
        The card's feature dict (needs ``scarcity`` 0-10, ``char_premium`` 0-10,
        ``set_rank`` 0-1).
    momentum:
        Optional 0-1 market-momentum signal. When present it is blended in with
        a small weight and the live weights are rescaled so the result stays in
        [0, 100]. With the eBay feed stubbed this is ``None`` for every card.

    Returns
    -------
    float
        IQ score in ``[0, 100]``, rounded to 2 dp.
    """
    # Normalize each live signal to 0-1.
    norm = {
        "scarcity": _clamp01(feats.get("scarcity", 0.0) / 10.0),
        "char_premium": _clamp01(feats.get("char_premium", 0.0) / 10.0),
        "set_rank": _clamp01(feats.get("set_rank", 0.5)),
    }
    weights = dict(IQ_WEIGHTS)
    if momentum is not None:
        # Reserve 20% for momentum and proportionally shrink the live weights.
        scale = 0.80
        weights = {k: w * scale for k, w in weights.items()}
        weights["momentum"] = 0.20
        norm["momentum"] = _clamp01(momentum)

    total_w = sum(weights.values())
    blended = sum(norm[k] * w for k, w in weights.items()) / total_w
    return round(100.0 * _clamp01(blended), 2)


def _clamp01(x: float) -> float:
    """Clamp a float into ``[0, 1]``."""
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return float(x)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def _load_json(path: Path):
    return json.loads(Path(path).read_text())


def _load_cards() -> List[dict]:
    return _load_json(config.NORMALIZED / "cards.json")


def _load_sets() -> List[dict]:
    return _load_json(config.NORMALIZED / "sets.json")


def _load_ebay_history(out_dir: Path) -> Dict[str, List[dict]]:
    """Load every ``ebay-<date>.json`` snapshot into per-card history.

    Delegates to :func:`market_dynamics.load_history`, which reads each
    ``ebay-<YYYY-MM-DD>.json`` in date order, stamps every per-card row with its
    file date, and backfills the day-over-day flow fields
    (``new_listings``/``ended_listings``/``est_sold``/``est_unsold``) via
    ``collectors.ebay.diff_row`` so demand pressure works even from counts-only
    snapshots. Returns ``{card_id: [rows sorted by date]}``. With the collector
    stubbed (no key, no history) every row is neutral, so compute() returns the
    awaiting-data fallback — which is exactly what we surface honestly in the UI.
    """
    return market_dynamics.load_history(out_dir)


# ---------------------------------------------------------------------------
# Per-stage builders
# ---------------------------------------------------------------------------
def build_sets(
    cards: List[dict], sets: List[dict], counts: Dict[str, Dict[str, int]]
) -> List[dict]:
    """Build the per-set EV leaderboard rows (sets.json payload).

    Each row is the SetRecord merged with the EV fields from
    :func:`ev.ev_for_set`. Rows are ordered best-bang-for-buck first
    (highest ``signal_pct`` -> most undervalued box).
    """
    by_set: Dict[str, List[dict]] = {}
    for c in cards:
        by_set.setdefault(c["set_id"], []).append(c)

    rows: List[dict] = []
    for s in sets:
        sid = s["set_id"]
        ev_fields = ev.ev_for_set(by_set.get(sid, []), s, counts)
        row = dict(s)
        row.update(ev_fields)
        rows.append(row)

    # Best value (most undervalued box) first; None signals sort last.
    rows.sort(
        key=lambda r: (r["signal_pct"] is None, -(r["signal_pct"] or 0.0))
    )
    return rows


def build_dynamics(
    cards: List[dict], ebay_history: Dict[str, List[dict]]
) -> Dict[str, dict]:
    """Compute market-dynamics signals per card from the eBay snapshot history.

    With the collector stubbed this is the neutral ``awaiting_data`` fallback for
    every card; the schema is the deliverable and a real feed drops straight in.
    """
    return {
        c["id"]: market_dynamics.compute(c["id"], ebay_history) for c in cards
    }


def build_cards(
    cards: List[dict],
    features: Dict[str, Dict[str, float]],
    result: "model.ModelResult",
    dynamics: Dict[str, dict],
    signals_by_id: Optional[Dict[str, dict]] = None,
) -> List[dict]:
    """Assemble the enriched per-card records for cards.json.

    Each record is the NormalizedCard plus: ``features``, ``cluster``,
    ``expected_price``, ``residual_pct``, ``iq_score``, ``contributions``,
    ``dynamics``, ``price_move``, ``signal`` and ``image_small`` (already present).
    """
    signals_by_id = signals_by_id or {}
    out: List[dict] = []
    for c in cards:
        cid = c["id"]
        feats = features.get(cid, {})
        pred = result.get(cid)

        record = dict(c)  # keep all NormalizedCard fields (incl. image_small)
        record["features"] = feats
        record["iq_score"] = iq_score(feats)
        record["dynamics"] = dynamics.get(cid, dict(market_dynamics.NEUTRAL))
        sig = signals_by_id.get(cid)
        if sig is not None:
            record["price_move"] = sig.get("price_move")
            record["signal"] = sig.get("signal")

        if pred is not None:
            record["cluster"] = pred.cluster
            record["expected_price"] = round(pred.expected_price, 4)
            record["residual_pct"] = (
                round(pred.residual_pct, 6) if pred.residual_pct is not None else None
            )
            record["contributions"] = {
                k: round(v, 6) for k, v in pred.contributions.items()
            }
        else:
            record["cluster"] = c.get("rarity") or "Unknown"
            record["expected_price"] = None
            record["residual_pct"] = None
            record["contributions"] = {}

        out.append(record)
    return out


def build_leaderboard(card_records: List[dict]) -> dict:
    """Build the undervalued / overvalued / movers leaderboards.

    Cards are ranked by RAW dollar gap (expected - market), like the reference
    site, and cards under ``config.LEADERBOARD_MIN_PRICE`` are dropped so penny
    cards (huge, meaningless % swings) don't crowd out real-dollar movers.

    * ``undervalued`` — biggest positive ``expected - market`` (largest $ discount).
    * ``overvalued``  — biggest negative ``expected - market`` (largest $ premium).
    * ``movers``      — biggest market movers. Primary key is the saturation
      shift from market_dynamics (``|supply_saturation - 1|``); with the eBay
      feed stubbed there is no real shift, so we fall back to the largest
      absolute dollar gap and flag ``awaiting_data`` so the UI never implies a
      feed we don't have.
    """
    floor = getattr(config, "LEADERBOARD_MIN_PRICE", 0.0)
    size = getattr(config, "LEADERBOARD_SIZE", 50)
    # GATING: only surface cards where the model has measured edge. A mature
    # (non-fresh) card priced in the dead zone [GATE_DEAD_LO, GATE_DEAD_HI) is
    # wrong-signed in the backtest (IC -0.05), so we don't publish a call on it.
    fresh_months = config.GATE_FRESH_AGE_DAYS / 30.4375
    def _surfaced(r: dict) -> bool:
        price = r.get("market_price") or 0.0
        if config.GATE_DEAD_LO <= price < config.GATE_DEAD_HI:
            msr = (r.get("features") or {}).get("months_since_release")
            if msr is None or msr > fresh_months:
                return False
        return True

    pool = [
        r
        for r in card_records
        if r.get("residual_pct") is not None
        and r.get("market_price") is not None
        and r.get("expected_price") is not None
        and r["market_price"] >= floor
        and _surfaced(r)
    ]

    def raw_diff(r: dict) -> float:
        return r["expected_price"] - r["market_price"]

    by_diff = sorted(pool, key=raw_diff, reverse=True)
    undervalued = [_leader_row(r) for r in by_diff[:size]]            # biggest $ discount
    overvalued = [_leader_row(r) for r in sorted(pool, key=raw_diff)[:size]]  # biggest $ premium

    # Movers: prefer real saturation shift; fall back to dollar-gap magnitude.
    def saturation_shift(r: dict) -> float:
        sat = (r.get("dynamics") or {}).get("supply_saturation")
        return abs(sat - 1.0) if sat is not None else 0.0

    have_real_shift = any(saturation_shift(r) > 0.0 for r in pool)
    if have_real_shift:
        movers_sorted = sorted(pool, key=saturation_shift, reverse=True)
        movers_basis = "saturation_shift"
    else:
        movers_sorted = sorted(pool, key=lambda r: abs(raw_diff(r)), reverse=True)
        movers_basis = "price_signal_fallback"

    movers = []
    for r in movers_sorted[:size]:
        row = _leader_row(r)
        row["mover_basis"] = movers_basis
        row["awaiting_data"] = not have_real_shift
        movers.append(row)

    return {
        "undervalued": undervalued,
        "overvalued": overvalued,
        "movers": movers,
        "movers_basis": "saturation_shift" if have_real_shift else "price_signal_fallback",
        "min_price": floor,
    }


# ---------------------------------------------------------------------------
# Forward prediction log (self-grading panel for the backtest)
# ---------------------------------------------------------------------------
# Every build records what the model PREDICTED today, next to the market price,
# so we can later check whether the over/under call was right. The daily price
# panel already exists (fetch.py -> snapshot-<date>.json = {id: market}); this
# adds the missing half (expected price + verdict). Joined by date downstream by
# pipeline/backtest.py. Verdict band is intentionally wider than the UI's sign
# split so "fair" is a real bucket and we only grade confident calls.
PRED_BAND = 0.15  # |residual_pct| below this = "fair" (not a directional call)


def _write_prediction_log(card_records: List[dict], built_for: str) -> int:
    """Write ``data/snapshots/pred-<date>.json`` = the model's calls for today.

    One compact row per priced card::

        {card_id: {"m": market, "e": expected, "r": residual_pct, "v": verdict}}

    ``verdict``: ``under`` (market below fair value, r < -BAND), ``over``
    (r > +BAND), else ``fair``. Idempotent per day (overwrite). Returns the row
    count. This is the forward half of the backtest panel — from the day it
    ships, every refresh self-grades going forward.
    """
    log: Dict[str, dict] = {}
    for r in card_records:
        m = r.get("market_price")
        e = r.get("expected_price")
        rp = r.get("residual_pct")
        if m is None or e is None or rp is None:
            continue
        verdict = "under" if rp < -PRED_BAND else "over" if rp > PRED_BAND else "fair"
        log[r["id"]] = {
            "m": round(m, 4),
            "e": round(e, 4),
            "r": round(rp, 6),
            "v": verdict,
        }
    path = config.SNAPSHOTS / f"pred-{built_for}.json"
    path.write_text(json.dumps(log, separators=(",", ":")))
    return len(log)


def _leader_row(r: dict) -> dict:
    """Slim card record for a leaderboard entry (enough for a card row + modal)."""
    return {
        "id": r["id"],
        "name": r["name"],
        "set_name": r["set_name"],
        "set_id": r["set_id"],
        "rarity": r["rarity"],
        "number": r.get("number"),
        "image_small": r.get("image_small"),
        "image_large": r.get("image_large"),
        "market_price": r.get("market_price"),
        "expected_price": r.get("expected_price"),
        "raw_diff": (
            round(r["expected_price"] - r["market_price"], 2)
            if r.get("expected_price") is not None and r.get("market_price") is not None
            else None
        ),
        "residual_pct": r.get("residual_pct"),
        "iq_score": r.get("iq_score"),
        "cluster": r.get("cluster"),
        "dynamics": r.get("dynamics"),
        "price_move": r.get("price_move"),
        "signal": r.get("signal"),
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def _snapshot_is_live(path: Path) -> bool:
    """True if an eBay snapshot file exists AND carries real listing data (any
    card with active_listings > 0) — i.e. not a neutral/awaiting-data stub.

    Lets the build SKIP re-sweeping (and re-spending the daily eBay quota) when
    today's snapshot was already collected (e.g. a manual sweep, or a re-run).
    """
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    return any((row or {}).get("active_listings") for row in data.values())


def build(today: Optional[date] = None) -> dict:
    """Run the whole pipeline on the cached data and write ``site/data/*.json``.

    Returns a small summary dict (also the basis of meta.json). ``today`` is
    threaded through so months_since_release / the build timestamp are
    reproducible in tests.
    """
    out_dir = config.SITE_DATA
    out_dir.mkdir(parents=True, exist_ok=True)
    built_at = (today or date.today()).isoformat()  # the date this build is "for"

    # --- 1. load cached, normalized inputs --------------------------------
    cards = _load_cards()
    sets = _load_sets()
    # Overlay the manual TCGplayer sealed feed (real pack/ETB prices + per-set
    # sealed demand) onto the config estimates, until the eBay feed lands.
    sealed_overlay = sealed_market.load()
    for s in sets:
        ov = sealed_overlay.get(s["set_id"])
        if not ov:
            continue
        if "pack_price" in ov:
            s["pack_price"] = ov["pack_price"]
        if "etb_price" in ov:
            s["etb_price"] = ov["etb_price"]
        s["sealed"] = ov["sealed"]
    set_by_id = {s["set_id"]: s for s in sets}
    priced = [c for c in cards if c.get("market_price") is not None]

    # --- 2. pull rates ----------------------------------------------------
    counts = pullrates.rarity_counts(cards)

    # --- 3. sealed EV per set --------------------------------------------
    set_rows = build_sets(cards, sets, counts)

    # --- 4. live + stub features -----------------------------------------
    features = signals.compute_features(cards, today=today)

    # --- 5. inject the REAL pull_cost (market pack price / pull_rate) -----
    # signals.py deliberately omits pull_cost so it never imports pullrates; we
    # compute it here per card. Uses the SECONDARY (real market) loose-pack price
    # -> what it would ACTUALLY cost in packs today to hit this exact card. Tested
    # stronger than the MSRP basis (model R²(log) 0.955 -> 0.961) and matches the
    # reference site's pull-cost magnitudes (e.g. Ascended Heroes SIR ~$21k).
    pull_costs: Dict[str, float] = {}
    for c in cards:
        sid = c["set_id"]
        set_rec = set_by_id.get(sid)
        pack_price = (set_rec.get("pack_price") or set_rec.get("retail_pack_price")) if set_rec else 0.0
        pc = pullrates.pull_cost(c["rarity"], sid, counts, pack_price)
        # Guard the model against a non-finite feature (unknown set/rarity).
        pull_costs[c["id"]] = pc if pc != float("inf") else 0.0
    signals.inject_pull_cost(features, pull_costs)

    # --- 6. market dynamics (eBay snapshot history) ---
    # Collect today's eBay snapshot ONCE, VALUABLE CARDS FIRST so the daily
    # call-budget cap only ever drops penny commons (never whole recent sets).
    # Idempotent: if today's snapshot already has live data (a manual sweep ran
    # earlier, or this is a re-run), keep it instead of re-spending the quota.
    snap_date = today or date.today()
    snap_path = config.SNAPSHOTS / f"ebay-{snap_date.isoformat()}.json"
    if _snapshot_is_live(snap_path):
        print(f"  eBay snapshot {snap_path.name} already live — keeping it (no re-sweep).")
    else:
        # Only sweep the cards the demand signal is actually used for: those at or
        # above the leaderboard floor (~850 cards), most valuable first. Sweeping
        # all ~2900 (incl. penny commons) just invites eBay rate-limiting for no
        # benefit. The collector's own circuit-breakers cap time on top of this.
        # FIXED, valuable-first universe of a stable size, swept FULLY every day so
        # the same cards get a daily active-listing count and day-over-day demand
        # diffs accrue (the old variable ~850-card slice got budget-truncated at a
        # different point each day -> zero same-card overlap -> demand never built).
        to_sweep = sorted(
            (c for c in cards if (c.get("market_price") or 0) >= config.LEADERBOARD_MIN_PRICE),
            key=lambda c: -(c.get("market_price") or 0),
        )[: config.DEMAND_UNIVERSE_SIZE]
        print(f"  eBay sweep: top {len(to_sweep)} cards by price (fixed daily demand universe)")
        ebay.collect_snapshot(to_sweep, out_dir=config.SNAPSHOTS, snapshot_date=snap_date)
    ebay_history = _load_ebay_history(config.SNAPSHOTS)
    dynamics = build_dynamics(cards, ebay_history)

    # --- 6b. plain-language market-signal labels (rules layer, NOT a model input) ---
    # Fuse recent price move (daily snapshot-<date>.json history) + demand/supply
    # (dynamics) into one English verdict per card. Descriptive only — demand never
    # touches expected_price (see config.FEATURES / the 2026-06-21 audit).
    price_hist = signal_labels.load_price_history(config.SNAPSHOTS, as_of=snap_date)
    signals_by_id: Dict[str, dict] = {}
    for c in cards:
        cid = c["id"]
        pm = signal_labels.price_move(price_hist.get(cid), as_of=snap_date)
        signals_by_id[cid] = {
            "price_move": pm,
            "signal": signal_labels.compute_signal(pm, dynamics.get(cid)),
        }

    # --- 7. fit the clustered ridge model + export model.json ------------
    result = model.fit(cards, features)
    model_payload = result.export(out_dir / "model.json")

    # --- 8. assemble enriched cards + IQ scores --------------------------
    card_records = build_cards(cards, features, result, dynamics, signals_by_id)

    # --- 8b. forward prediction log (self-grading backtest panel) --------
    n_pred = _write_prediction_log(card_records, built_for=built_at)

    # --- 9. leaderboards -------------------------------------------------
    leaderboard = build_leaderboard(card_records)

    # --- 10. meta --------------------------------------------------------
    signal_status = {
        name: meta.get("status", "live") for name, meta in config.FEATURES.items()
    }
    meta = {
        "built_at": datetime.now().replace(microsecond=0).isoformat(),
        "built_for_date": built_at,
        "sets": len(sets),
        "cards": len(cards),
        "priced": len(priced),
        "clusters": len(model_payload["clusters"]),
        "model_r2_log": round(result.r2_log(), 6),
        "predictions_logged": n_pred,
        "sources": {
            "cards": "pokemontcg.io (cached, normalized)",
            "prices": "pokemontcg.io TCGplayer market prices (cached)",
            "ebay": "stub (awaiting Browse API key)",
            "psa": "stub (awaiting PSA pop feed)",
            "trends": "stub (awaiting Google Trends feed)",
        },
        "signal_status": signal_status,
    }

    # --- 11. write all outputs -------------------------------------------
    _write(out_dir / "cards.json", card_records)
    _write(out_dir / "sets.json", set_rows)
    _write(out_dir / "leaderboard.json", leaderboard)
    _write(out_dir / "meta.json", meta)
    # model.json already written by result.export above.

    return {
        "cards": len(card_records),
        "priced": len(priced),
        "sets": len(set_rows),
        "clusters": len(model_payload["clusters"]),
        "r2_log": result.r2_log(),
        "out_dir": str(out_dir),
    }


def _write(path: Path, obj) -> None:
    """Serialize ``obj`` to ``path`` as pretty JSON (NaN/inf -> null-safe)."""
    Path(path).write_text(json.dumps(obj, indent=2, allow_nan=False))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    summary = build()
    print("Build complete:")
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"  {k:10} {v:.4f}")
        else:
            print(f"  {k:10} {v}")
