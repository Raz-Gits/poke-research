"""Shared walk-forward forward-IC harness for evaluating a custom feature set.

This is the FOUNDATION other agents import to score alternative ``feature_names``
lists for the clustered ridge price model. It reuses ``pipeline.backtest``
internals verbatim (panel loader, pull costs, nearest-forward pairing, the
Spearman + Newey-West helpers, the age gating, the floors, the HAC lag) so the
numbers it reports are DIRECTLY comparable to the committed walk-forward
backtest in ``pipeline/backtest.py``.

The single difference from ``backtest.residuals_at`` is the injection point the
task requires: we refit ``model.fit(cards_T, feats_T, feature_names=...)`` with
a caller-supplied ordered feature list, instead of letting the model default to
all of ``config.FEATURES``. Everything else — how a card's price at T is gated,
how the forward return to T+horizon is computed, how per-date Spearman ICs are
pooled and turned into a HAC t-stat — is identical to the committed backtest.

Public API::

    from experiments.eval_formula import evaluate
    evaluate(['char_premium','scarcity','pull_cost','months_since_release','set_rank'])

``evaluate`` is PURE: it returns a dict and writes NOTHING to disk (so many
agents can call it concurrently). ``print`` is avoided inside it.

Segments (mirroring backtest.py's headline cuts exactly):
  * fresh:  post-release cards 0..35d old (negative/presale ages EXCLUDED).
  * mature: cards >90d old AND market_price >= $10 at T.
  * all:    every priced card above the $2 base floor.

Returns::

    {fresh_ic, fresh_t, mature_ic, mature_t, all_ic, decile_spread_pct, r2_log}
"""
from __future__ import annotations

import json
from datetime import date
from typing import Dict, List, Optional, Sequence

import numpy as np

from pipeline import backtest, config, model, signals

# Re-export the exact constants the committed backtest uses, so this harness and
# pipeline/backtest.py stay byte-for-byte aligned on universe definition.
BASE_FLOOR = backtest.BASE_FLOOR        # 2.0  — minimum price to enter at all
MATURE_AGE = backtest.MATURE_AGE        # 90   — days post-release => "mature"
FRESH_AGE = backtest.FRESH_AGE          # 35   — days post-release => "fresh"
MATURE_FLOOR = backtest.MATURE_FLOOR    # 10.0 — price floor for the mature cut
DEFAULT_HORIZON = backtest.PRIMARY_HORIZON  # 28
DEFAULT_STEP = backtest.STEP_DAYS           # 7


# ---------------------------------------------------------------------------
# As-of-T refit WITH a custom feature_names list.
# ---------------------------------------------------------------------------
def residuals_at(
    T: date,
    prices_T: Dict[str, float],
    cards: List[dict],
    pull_costs: Dict[str, float],
    feature_names: Sequence[str],
    alpha: float = config.RIDGE_ALPHA,
) -> Dict[str, float]:
    """Replica of ``backtest.residuals_at`` that PASSES ``feature_names``.

    Identical to the committed routine line-for-line except for the single
    ``model.fit(..., feature_names=feature_names)`` argument, so the residuals
    this produces for the default 5-feature list match the committed backtest's.
    ``alpha`` lets a caller sweep the ridge L2 strength. Returns
    ``{card_id: residual_pct}``. No future information enters.
    """
    cards_T: List[dict] = []
    for c in cards:
        p = prices_T.get(c["id"])
        if p is None or p <= 0:
            continue
        cards_T.append({**c, "market_price": p})
    if len(cards_T) < config.MIN_CLUSTER_SIZE:
        return {}
    feats = signals.compute_features(cards_T, today=T)
    signals.inject_pull_cost(
        feats, {c["id"]: pull_costs.get(c["id"], 0.0) for c in cards_T}
    )
    result = model.fit(cards_T, feats, feature_names=list(feature_names), alpha=alpha)
    out: Dict[str, float] = {}
    for c in cards_T:
        pred = result.get(c["id"])
        if pred is not None and pred.residual_pct is not None:
            out[c["id"]] = float(pred.residual_pct)
    return out


def _fit_result_at(
    T: date,
    prices_T: Dict[str, float],
    cards: List[dict],
    pull_costs: Dict[str, float],
    feature_names: Sequence[str],
    alpha: float = config.RIDGE_ALPHA,
) -> Optional[model.ModelResult]:
    """Same as ``residuals_at`` but returns the full fitted ``ModelResult``.

    Used only for the in-sample ``r2_log`` on the most recent date.
    """
    cards_T: List[dict] = []
    for c in cards:
        p = prices_T.get(c["id"])
        if p is None or p <= 0:
            continue
        cards_T.append({**c, "market_price": p})
    if len(cards_T) < config.MIN_CLUSTER_SIZE:
        return None
    feats = signals.compute_features(cards_T, today=T)
    signals.inject_pull_cost(
        feats, {c["id"]: pull_costs.get(c["id"], 0.0) for c in cards_T}
    )
    return model.fit(cards_T, feats, feature_names=list(feature_names), alpha=alpha)


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------
def evaluate(
    feature_names: List[str],
    horizon: int = DEFAULT_HORIZON,
    step_days: int = DEFAULT_STEP,
    alpha: float = config.RIDGE_ALPHA,
) -> dict:
    """Walk-forward forward-IC evaluation of a custom ``feature_names`` list.

    For every weekly eval date T in the committed price panel we refit the
    clustered ridge model as-of T (no lookahead) using ONLY ``feature_names``,
    compute each priced card's residual_pct, and pair it with the realized
    forward return to the nearest panel date ~``horizon`` days ahead. Per-date
    Spearman ICs of mispricing (= -residual) vs forward return are pooled within
    each segment and averaged, with a Newey-West (HAC) t-stat across dates.

    Args:
      feature_names: ordered feature list to fit the model with.
      horizon: forward horizon in days (default 28, the backtest headline).
      step_days: weekly panel spacing; only used to derive the HAC lag, exactly
        as backtest._hac_lag does (it reads the module-level STEP_DAYS, so we
        compute the lag the same way to stay comparable).

    Returns:
      {fresh_ic, fresh_t, mature_ic, mature_t, all_ic, decile_spread_pct,
       r2_log}. IC/t values may be None for a segment that never has >=8 cards
      on >=5 dates (mirrors backtest's _ic_stats guard).
    """
    feature_names = list(feature_names)

    cards = json.loads((config.NORMALIZED / "cards.json").read_text())
    card_meta = {c["id"]: c for c in cards}
    panel = backtest.load_panel()
    dates = sorted(panel)
    if len(dates) < 3:
        raise SystemExit(
            f"need >=3 history dates to evaluate (have {len(dates)})."
        )

    pull_costs = backtest._pull_costs(cards)

    # HAC lag for the overlapping weekly windows. backtest._hac_lag uses its own
    # module-level STEP_DAYS; we replicate the formula honoring the caller's
    # step_days so the t-stat correction matches the committed convention.
    import math

    lag = max(1, math.ceil(horizon / step_days) + 1)

    # 1) Residuals at every eval date (the expensive step, done once).
    resid: Dict[date, Dict[str, float]] = {}
    for T in dates:
        resid[T] = residuals_at(T, panel[T], cards, pull_costs, feature_names, alpha=alpha)

    # 2) Build per-date observation rows, IDENTICAL shape to backtest.build_obs:
    #    row = (mispricing, fwd_return, age_days, price_at_T, rarity_group).
    #    A card enters only if priced at both T and Tf and >= BASE_FLOOR at T.
    obs: Dict[date, List[tuple]] = {}
    for T in dates:
        Tf = backtest._nearest_forward(dates, T, horizon)
        if Tf is None:
            continue
        rT, pT, pF = resid[T], panel[T], panel[Tf]
        rows = []
        for cid, r in rT.items():
            a, b = pT.get(cid), pF.get(cid)
            if a is None or b is None or a < BASE_FLOOR:
                continue
            rows.append(
                (
                    -r,                                   # mispricing = -residual
                    (b - a) / a,                          # forward return
                    backtest._age_days(card_meta.get(cid), T),
                    a,                                    # price at T
                    backtest._rarity_group(
                        card_meta.get(cid, {}).get("rarity", "")
                    ),
                )
            )
        if rows:
            obs[T] = rows

    # 3) Segment IC via the committed _ic_stats path (per-date Spearman, >=8
    #    cards/date, >=5 dates, HAC t). Predicate matches backtest's cuts EXACTLY.
    def ic_over(pred) -> Optional[dict]:
        per_date = []
        for rows in obs.values():
            sel = [(m, fr) for (m, fr, age, a, rg) in rows if pred(age, a, rg)]
            if len(sel) >= 8:
                per_date.append(([x[0] for x in sel], [x[1] for x in sel]))
        return backtest._ic_stats(per_date, lag)

    all_stats = ic_over(lambda age, a, rg: True)
    mature_stats = ic_over(
        lambda age, a, rg: a >= MATURE_FLOOR and age is not None and age > MATURE_AGE
    )
    # Fresh = POST-release only (0..35d); negative (presale) ages excluded, just
    # like backtest's fresh headline cut.
    fresh_stats = ic_over(
        lambda age, a, rg: age is not None and 0 <= age <= FRESH_AGE
    )

    # 4) Decile spread on 'all' (base floor): per date, mean fwd return of the
    #    most-undervalued decile minus the most-overvalued decile, averaged.
    #    Replicates backtest's decile-legs loop verbatim.
    top_legs, bot_legs = [], []
    for rows in obs.values():
        if len(rows) < 20:
            continue
        m = np.asarray([r[0] for r in rows])
        fr = np.asarray([r[1] for r in rows])
        order = np.argsort(m)
        k = max(1, len(order) // 10)
        top_legs.append(float(fr[order[-k:]].mean()))   # most undervalued
        bot_legs.append(float(fr[order[:k]].mean()))    # most overvalued
    decile_spread_pct = None
    if top_legs:
        decile_spread_pct = float(np.mean(top_legs)) - float(np.mean(bot_legs))

    # 5) In-sample log R^2 of the final fit on the most recent date.
    r2_log = None
    last = dates[-1]
    final_fit = _fit_result_at(last, panel[last], cards, pull_costs, feature_names, alpha=alpha)
    if final_fit is not None:
        r2 = final_fit.r2_log()
        r2_log = float(r2) if r2 == r2 else None  # guard NaN

    def _ic(st):
        return st["ic"] if st else None

    def _t(st):
        return st["nw_t"] if st else None

    return {
        "fresh_ic": _ic(fresh_stats),
        "fresh_t": _t(fresh_stats),
        "mature_ic": _ic(mature_stats),
        "mature_t": _t(mature_stats),
        "all_ic": _ic(all_stats),
        "decile_spread_pct": (
            round(decile_spread_pct, 4) if decile_spread_pct is not None else None
        ),
        "r2_log": round(r2_log, 4) if r2_log is not None else None,
    }


if __name__ == "__main__":
    import sys

    feats = (
        sys.argv[1].split(",")
        if len(sys.argv) > 1
        else ["char_premium", "scarcity", "pull_cost", "months_since_release", "set_rank"]
    )
    out = evaluate(feats)
    print(f"features = {feats}")
    for k, v in out.items():
        print(f"  {k:18s} = {v}")
