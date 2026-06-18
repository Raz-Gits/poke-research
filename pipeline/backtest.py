"""Walk-forward backtest — does the model's over/under call actually predict price?

The site's one falsifiable bet: a card we flag UNDERVALUED (market below model
fair value, ``residual_pct < 0``) should, on average, out-return one we flag
OVERVALUED over the following weeks. This module grades that bet against real
later prices from the TCGCSV history panel (``data/history/price-<date>.json``,
built by ``collectors.tcgcsv``).

Method (no lookahead):
  * For each evaluation date ``T`` in the panel, **refit the whole model using
    only T's prices** — every price-dependent feature (set_rank) and date feature
    (months_since_release, scarcity age) is recomputed as-of T. So the residual
    at T is what the site WOULD have shown that day.
  * Look forward ``horizon`` days to the nearest panel date ``Tf`` and measure the
    realized return ``(price_Tf - price_T) / price_T`` per card.
  * Residuals at T are computed once and scored against several horizons.

Metrics:
  * **Rank IC** — per-date Spearman( mispricing_T , forward_return ), averaged.
    ``mispricing = -residual_pct`` so POSITIVE IC = the model ranks future
    winners correctly. Reported with a t-stat across dates.
  * **Hit-rate** — of confident UNDER calls, % that rose; of OVER calls, % that
    fell. Compared to the base rate (fraction of all cards that rose).
  * **Decile spread** — per date, mean forward return of the most-undervalued
    decile minus the most-overvalued decile, averaged. The "would the call have
    made money" number.
  * Breakdowns by rarity and price tier — to localize where the model has edge
    and where it's blind (chase cards, until the demand signal lands).

This is read-only analysis; it writes ``docs/data/backtest.json`` for the site.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import config, model, signals, pullrates

HISTORY_DIR = config.DATA / "history"
OUT_PATH = config.SITE_DATA / "backtest.json"

PRICE_FLOOR = max(getattr(config, "LEADERBOARD_MIN_PRICE", 2.0), 2.0)
BAND = 0.15                  # |residual| below this = "fair" (not graded for hit-rate)
HORIZONS = [7, 28, 56, 84]   # days; 28 is the headline
PRIMARY_HORIZON = 28
PAIR_TOL_DAYS = 6            # how far from T+horizon a panel date may be and still count


# ---------------------------------------------------------------------------
# Panel loading
# ---------------------------------------------------------------------------
def load_panel() -> Dict[date, Dict[str, float]]:
    """Load ``data/history/price-<date>.json`` -> ``{date: {card_id: price}}``."""
    panel: Dict[date, Dict[str, float]] = {}
    if not HISTORY_DIR.exists():
        return panel
    for f in sorted(HISTORY_DIR.glob("price-*.json")):
        try:
            d = date.fromisoformat(f.stem.replace("price-", ""))
            prices = json.loads(f.read_text())
        except Exception:  # pragma: no cover
            continue
        if prices:
            panel[d] = {k: float(v) for k, v in prices.items() if v is not None}
    return panel


# ---------------------------------------------------------------------------
# As-of-T model refit
# ---------------------------------------------------------------------------
def _pull_costs(cards: List[dict]) -> Dict[str, float]:
    """Price-independent retail pull cost per card (stable across dates)."""
    counts = pullrates.rarity_counts(cards)
    set_by_id = {s["set_id"]: s for s in json.loads((config.NORMALIZED / "sets.json").read_text())}
    out: Dict[str, float] = {}
    for c in cards:
        sr = set_by_id.get(c["set_id"], {})
        pack = sr.get("retail_pack_price") or sr.get("pack_price") or 0.0
        pc = pullrates.pull_cost(c["rarity"], c["set_id"], counts, pack)
        out[c["id"]] = pc if pc != float("inf") else 0.0
    return out


def residuals_at(T: date, prices_T: Dict[str, float], cards: List[dict],
                 pull_costs: Dict[str, float]) -> Dict[str, float]:
    """Refit the model on T's prices and return ``{card_id: residual_pct}``.

    A copy of each priced card carries its T-date market price; features are
    recomputed as-of T (so set_rank / months / scarcity reflect that day). No
    future information enters.
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
    signals.inject_pull_cost(feats, {c["id"]: pull_costs.get(c["id"], 0.0) for c in cards_T})
    result = model.fit(cards_T, feats)
    out: Dict[str, float] = {}
    for c in cards_T:
        pred = result.get(c["id"])
        if pred is not None and pred.residual_pct is not None:
            out[c["id"]] = float(pred.residual_pct)
    return out


# ---------------------------------------------------------------------------
# Stats helpers (numpy only)
# ---------------------------------------------------------------------------
def _rankdata(a: np.ndarray) -> np.ndarray:
    """Average-rank (ties shared) — for Spearman."""
    a = np.asarray(a, dtype=float)
    n = len(a)
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    sorted_a = a[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_a[j + 1] == sorted_a[i]:
            j += 1
        ranks[order[i:j + 1]] = 0.5 * (i + j) + 1.0  # 1-based average rank
        i = j + 1
    return ranks


def _spearman(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 8:
        return None
    rx, ry = _rankdata(x), _rankdata(y)
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def _nw_tstat(ics: Sequence[float], lag: int) -> Optional[float]:
    """Newey-West (HAC) t-stat for the mean of an autocorrelated IC series.

    Weekly evaluation dates with a multi-week forward horizon produce OVERLAPPING
    windows, so the per-date ICs are autocorrelated and the naive
    ``mean/(std/sqrt(n))`` t overstates significance ~2x. Bartlett-weighted HAC
    long-run variance with ``lag`` ≈ horizon/step corrects it.
    """
    x = np.asarray(ics, dtype=float)
    n = len(x)
    if n < 5:
        return None
    d = x - x.mean()
    var = float((d * d).mean())                       # gamma_0
    for l in range(1, min(lag, n - 1) + 1):
        w = 1.0 - l / (lag + 1.0)
        var += 2.0 * w * float((d[l:] * d[:-l]).mean())  # Bartlett-weighted autocov
    if var <= 0:
        return None
    se = math.sqrt(var / n)
    return float(x.mean() / se) if se > 0 else None


def _ic_stats(per_date: List[Tuple[Sequence[float], Sequence[float]]],
              lag: int) -> Optional[dict]:
    """Per-date Spearman ICs -> {ic mean, naive_t, nw_t, sign test, n_dates}."""
    ics = [ic for (m, r) in per_date if (ic := _spearman(m, r)) is not None]
    if len(ics) < 5:
        return None
    arr = np.asarray(ics)
    mean = float(arr.mean())
    std = float(arr.std())
    naive_t = float(mean / (std / math.sqrt(len(ics)))) if std > 0 else None
    pos = int((arr > 0).sum())
    sign_z = float((pos - len(ics) / 2) / (math.sqrt(len(ics)) / 2))
    return {
        "ic": round(mean, 4),
        "naive_t": round(naive_t, 2) if naive_t is not None else None,
        "nw_t": round(_nw_tstat(ics, lag), 2) if _nw_tstat(ics, lag) is not None else None,
        "n_dates": len(ics),
        "sign_pos": pos,
        "sign_z": round(sign_z, 2),
    }


# ---------------------------------------------------------------------------
# Pairing dates by horizon
# ---------------------------------------------------------------------------
def _nearest_forward(dates: List[date], T: date, horizon: int) -> Optional[date]:
    target = T + timedelta(days=horizon)
    best, best_gap = None, PAIR_TOL_DAYS + 1
    for d in dates:
        if d <= T:
            continue
        gap = abs((d - target).days)
        if gap < best_gap:
            best, best_gap = d, gap
    return best


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _rarity_group(rarity: str) -> str:
    r = (rarity or "").lower()
    if "hyper" in r:
        return "Hyper Rare"
    if "special illustration" in r:
        return "Special Illustration Rare"
    if "illustration" in r:
        return "Illustration Rare"
    if "ultra" in r or "mega" in r:
        return "Ultra/Mega Rare"
    if "double" in r:
        return "Double Rare"
    if r in ("common", "uncommon", "rare"):
        return "Common/Uncommon/Rare"
    return "Other"


def _price_tier(p: float) -> str:
    if p < 5:
        return "$2-5"
    if p < 20:
        return "$5-20"
    if p < 100:
        return "$20-100"
    return "$100+"


STEP_DAYS = 7          # weekly panel spacing (drives the HAC lag)
BASE_FLOOR = 2.0       # minimum price to enter the universe at all
MATURE_AGE = 90        # days since release to count a card as "mature"
FRESH_AGE = 35         # days since release to count a card as a "fresh release"
MATURE_FLOOR = 10.0    # price floor for the honest "mature & liquid" headline


def _age_days(card: Optional[dict], T: date) -> Optional[int]:
    """Days between a card's release and evaluation date T (None if unknown)."""
    rel = (card or {}).get("release_date")
    if not rel:
        return None
    try:
        return (T - date.fromisoformat(rel[:10])).days
    except Exception:
        return None


def _hac_lag(horizon: int) -> int:
    """HAC lag for overlapping windows: ~ how many weekly dates a window spans."""
    return max(1, math.ceil(horizon / STEP_DAYS) + 1)


def run(horizons: Sequence[int] = HORIZONS, band: float = BAND,
        write: bool = True) -> dict:
    cards = json.loads((config.NORMALIZED / "cards.json").read_text())
    card_meta = {c["id"]: c for c in cards}
    panel = load_panel()
    dates = sorted(panel)
    if len(dates) < 3:
        raise SystemExit(f"need >=3 history dates to backtest (have {len(dates)}). "
                         "Run: ./.venv/bin/python -m collectors.tcgcsv")

    pull_costs = _pull_costs(cards)

    # 1) residuals at every eval date (the expensive step, done once, no lookahead).
    resid: Dict[date, Dict[str, float]] = {}
    for T in dates:
        resid[T] = residuals_at(T, panel[T], cards, pull_costs)

    # 2) build per-date observations for a horizon: each row carries everything we
    #    need to slice by age / price / rarity afterwards.
    #    row = (mispricing, fwd_return, age_days, price_at_T, rarity_group)
    def build_obs(H: int) -> Dict[date, List[tuple]]:
        obs: Dict[date, List[tuple]] = {}
        for T in dates:
            Tf = _nearest_forward(dates, T, H)
            if Tf is None:
                continue
            rT, pT, pF = resid[T], panel[T], panel[Tf]
            rows = []
            for cid, r in rT.items():
                a, b = pT.get(cid), pF.get(cid)
                if a is None or b is None or a < BASE_FLOOR:
                    continue
                rows.append((-r, (b - a) / a, _age_days(card_meta.get(cid), T),
                             a, _rarity_group(card_meta.get(cid, {}).get("rarity", ""))))
            if rows:
                obs[T] = rows
        return obs

    def ic_over(obs: Dict[date, List[tuple]], pred, lag: int) -> Optional[dict]:
        per_date = []
        for rows in obs.values():
            sel = [(m, fr) for (m, fr, age, a, rg) in rows if pred(age, a, rg)]
            if len(sel) >= 8:
                per_date.append(([x[0] for x in sel], [x[1] for x in sel]))
        return _ic_stats(per_date, lag)

    primary = build_obs(PRIMARY_HORIZON)
    LAG = _hac_lag(PRIMARY_HORIZON)
    flat = [row for rows in primary.values() for row in rows]  # pooled, for means

    # --- headline cuts (primary horizon) --------------------------------------
    all_stats = ic_over(primary, lambda age, a, rg: True, LAG)
    mature = ic_over(primary, lambda age, a, rg: a >= MATURE_FLOOR and age is not None and age > MATURE_AGE, LAG)
    # Fresh = POST-release only (0..35d). We exclude negative ages (presale prices,
    # which the audit flagged as inflating the IC) so the headline doesn't lean on
    # that artifact; the presale effect is disclosed in the caveats instead.
    fresh = ic_over(primary, lambda age, a, rg: age is not None and 0 <= age <= FRESH_AGE, LAG)
    fresh_rows = [r for r in flat if r[2] is not None and 0 <= r[2] <= FRESH_AGE]
    fresh_mean_ret = round(float(np.mean([r[1] for r in fresh_rows])), 4) if fresh_rows else None

    # --- floor sensitivity ----------------------------------------------------
    floor_sensitivity = []
    for f in (2.0, 5.0, 10.0, 20.0):
        st = ic_over(primary, lambda age, a, rg, f=f: a >= f, LAG)
        if st:
            floor_sensitivity.append({"floor": f, "ic": st["ic"], "nw_t": st["nw_t"],
                                      "n_dates": st["n_dates"]})

    # --- by card age ----------------------------------------------------------
    AGE_BUCKETS = [("0-35d (fresh)", 0, 35), ("36-90d", 36, 90),
                   ("91-180d", 91, 180), ("180d+ (mature)", 181, 10 ** 9)]
    by_age = []
    for label, lo, hi in AGE_BUCKETS:
        st = ic_over(primary, lambda age, a, rg, lo=lo, hi=hi: age is not None and lo <= age <= hi, LAG)
        rows = [r for r in flat if r[2] is not None and lo <= r[2] <= hi]
        if st and rows:
            by_age.append({"bucket": label, "ic": st["ic"], "nw_t": st["nw_t"],
                           "mean_return": round(float(np.mean([r[1] for r in rows])), 4),
                           "n_obs": len(rows)})

    # --- by rarity / price tier (pooled IC + mean return) ---------------------
    def bucket_rows(idx_fn) -> List[dict]:
        groups: Dict[str, List[tuple]] = {}
        for r in flat:
            groups.setdefault(idx_fn(r), []).append(r)
        out_rows = []
        for key, rs in groups.items():
            if len(rs) < 30:
                continue
            ic = _spearman([r[0] for r in rs], [r[1] for r in rs])
            out_rows.append({"key": key, "n": len(rs),
                             "ic": round(ic, 4) if ic is not None else None,
                             "frac_up": round(sum(1 for r in rs if r[1] > 0) / len(rs), 4),
                             "mean_return": round(float(np.mean([r[1] for r in rs])), 4)})
        return sorted(out_rows, key=lambda x: -x["n"])

    by_rarity = bucket_rows(lambda r: r[4])
    by_price = bucket_rows(lambda r: _price_tier(r[3]))

    # --- decile legs (primary, base floor) ------------------------------------
    top_legs, bot_legs = [], []
    for rows in primary.values():
        if len(rows) < 20:
            continue
        m = np.asarray([r[0] for r in rows]); fr = np.asarray([r[1] for r in rows])
        order = np.argsort(m); k = max(1, len(order) // 10)
        top_legs.append(float(fr[order[-k:]].mean()))   # most undervalued
        bot_legs.append(float(fr[order[:k]].mean()))    # most overvalued
    decile = None
    if top_legs:
        t, b = float(np.mean(top_legs)), float(np.mean(bot_legs))
        decile = {"top_undervalued_return": round(t, 4),
                  "bottom_overvalued_return": round(b, 4),
                  "spread": round(t - b, 4), "n_dates": len(top_legs)}

    # --- hit rates (primary, base floor) --------------------------------------
    hu = hun = ho = hon = bu = bn = 0
    for rows in primary.values():
        for (m, fr, age, a, rg) in rows:
            bn += 1; bu += 1 if fr > 0 else 0
            if -m < -band:                # residual<-band => under
                hun += 1; hu += 1 if fr > 0 else 0
            elif -m > band:               # residual>band => over
                hon += 1; ho += 1 if fr < 0 else 0
    hit_rates = {"under": round(hu / hun, 4) if hun else None,
                 "over": round(ho / hon, 4) if hon else None,
                 "base_up": round(bu / bn, 4) if bn else None,
                 "n_under": hun, "n_over": hon}

    # --- by horizon (all vs mature; shows the "grows with horizon" caveat) ----
    by_horizon = []
    for H in horizons:
        o = build_obs(H); lag = _hac_lag(H)
        sa = ic_over(o, lambda age, a, rg: True, lag)
        sm = ic_over(o, lambda age, a, rg: a >= MATURE_FLOOR and age is not None and age > MATURE_AGE, lag)
        by_horizon.append({"horizon_days": H,
                           "ic_all": sa["ic"] if sa else None,
                           "nw_t_all": sa["nw_t"] if sa else None,
                           "ic_mature": sm["ic"] if sm else None,
                           "nw_t_mature": sm["nw_t"] if sm else None})

    # --- IC timeseries (all, primary) -----------------------------------------
    ic_ts = []
    for T, rows in primary.items():
        ic = _spearman([r[0] for r in rows], [r[1] for r in rows])
        if ic is not None:
            ic_ts.append({"date": T.isoformat(), "ic": round(ic, 4), "n": len(rows)})

    out = {
        "generated_for": dates[-1].isoformat(),
        "panel": {
            "first_date": dates[0].isoformat(), "last_date": dates[-1].isoformat(),
            "n_dates": len(dates), "step_days": STEP_DAYS,
            "primary_horizon_days": PRIMARY_HORIZON, "base_floor": BASE_FLOOR,
            "verdict_band": band,
        },
        "headline": {
            "mature_liquid": mature and {**mature,
                "note": f"cards >{MATURE_AGE}d old & >=${MATURE_FLOOR:.0f} — the honest steady-state edge"},
            "fresh_release": fresh and {**fresh, "mean_fwd_return": fresh_mean_ret,
                "note": f"cards <={FRESH_AGE}d old — the model's strongest, most real signal "
                        f"(fresh chase cards are overpriced and crash; avg {PRIMARY_HORIZON}d return "
                        f"{(fresh_mean_ret or 0)*100:.0f}%)"},
            "all_cards": all_stats and {**all_stats,
                "note": "floor $2, all ages — inflated by the presale/fresh + cheap-card effects below"},
        },
        "hit_rates": hit_rates,
        "decile": decile,
        "floor_sensitivity": floor_sensitivity,
        "by_age_bucket": by_age,
        "by_horizon": by_horizon,
        "by_rarity": by_rarity,
        "by_price_tier": by_price,
        "ic_timeseries": ic_ts,
        "caveats": [
            "Significance uses Newey-West (HAC) t-stats: weekly dates with a multi-week "
            "horizon overlap, so the naive t roughly doubles the real confidence.",
            "TCGCSV carries presale prices, so fresh cards enter ~1-2 weeks before release "
            "and then fall hard — that decay drives most of the all-cards IC.",
            "The edge concentrates in cheap cards; above $10 it shrinks toward (but stays "
            "above) zero. Treat the mature_liquid number as the honest baseline.",
            "Universe is products that still exist on TCGplayer today (mild survivorship).",
        ],
    }
    if write:
        OUT_PATH.write_text(json.dumps(out, indent=2, allow_nan=False))
    return out


if __name__ == "__main__":
    s = run()
    p, h = s["panel"], s["headline"]
    print(f"Backtest {p['n_dates']} weekly dates {p['first_date']}..{p['last_date']} "
          f"(horizon {p['primary_horizon_days']}d, HAC t):")
    for key in ("mature_liquid", "fresh_release", "all_cards"):
        c = h.get(key)
        if c:
            print(f"  {key:14s} IC={c['ic']:+.4f}  HAC t={c['nw_t']}  "
                  f"(naive {c['naive_t']})  sign {c['sign_pos']}/{c['n_dates']}+")
    hr = s["hit_rates"]
    print(f"  hit under={hr['under']} over={hr['over']} (base up {hr['base_up']})")
    print("  floor sensitivity:", "  ".join(
        f"${r['floor']:.0f}:IC{r['ic']:+.3f}(t{r['nw_t']})" for r in s["floor_sensitivity"]))
    print("  by age:", "  ".join(f"{r['bucket']}:IC{r['ic']:+.3f},ret{r['mean_return']:+.0%}"
                                  for r in s["by_age_bucket"]))
