"""Clustered ridge price regression for Poke Research.

The core modelling insight (see CONTRACT.md, "Price model"): one global
regression cannot fit thousands of cards whose price is driven by very
different dynamics per rarity tier. So we *cluster first* (on rarity tier — the
cheapest robust signal) and fit an independent ridge model inside each cluster.
Clusters that are too small to fit reliably fall back to a single global model
trained on every priced card.

Each per-cluster model:
  * standardises its features (z-score: ``(x - mean) / std``),
  * fits ridge regression predicting ``log(market_price)``,
  * via the closed-form normal equations ``w = (XtX + alpha*R)^-1 Xt y`` where
    ``R`` is the identity with the intercept term zeroed out, so the bias is
    *not* shrunk toward zero.

Because the features are standardised, the exported coefficients live on a
common scale, and the browser can recompute a card's expected price live as a
user drags sliders:

    expected = exp(intercept + Σ coef_i * ((x_i - mean_i) / std_i))

Only the standard library and numpy are used.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

from . import config


# ---------------------------------------------------------------------------
# Low-level ridge fit
# ---------------------------------------------------------------------------
class _ClusterModel:
    """A single standardised ridge model fit on one cluster of cards.

    Attributes mirror exactly what ``export`` serialises so the frontend can
    reproduce predictions:
      features  : ordered feature names
      means     : per-feature training mean (for standardisation)
      stds      : per-feature training std  (guarded so it is never 0)
      coef      : per-feature ridge coefficient (on the standardised scale)
      intercept : bias term (unregularised)
    """

    def __init__(self, features: Sequence[str]):
        self.features: List[str] = list(features)
        self.means: np.ndarray = np.zeros(len(features))
        self.stds: np.ndarray = np.ones(len(features))
        self.coef: np.ndarray = np.zeros(len(features))
        self.intercept: float = 0.0
        self.n: int = 0  # number of training rows

    # -- training -----------------------------------------------------------
    def fit(self, X: np.ndarray, y: np.ndarray, alpha: float) -> "_ClusterModel":
        """Fit ridge on raw feature matrix ``X`` against target ``y``.

        ``X`` is (n_samples, n_features) of *raw* feature values; ``y`` is the
        target (here ``log(market_price)``). Features are standardised here so
        the stored means/stds describe the exact transform the frontend repeats.
        """
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        self.n = X.shape[0]

        # Standardise. Guard against a zero (or numerically tiny) std — a
        # constant feature would otherwise blow up to inf/nan. We clamp the std
        # to 1.0 in that case, which makes the standardised column identically
        # zero (x - mean == 0), so the feature contributes nothing. The ridge
        # penalty then drives its coefficient to ~0, which is the desired
        # "ignore this constant feature" behaviour.
        self.means = X.mean(axis=0)
        stds = X.std(axis=0)
        stds = np.where(stds < 1e-12, 1.0, stds)
        self.stds = stds
        Xz = (X - self.means) / self.stds

        # Augment with an intercept column of 1s at position 0.
        n_samples = Xz.shape[0]
        Xa = np.hstack([np.ones((n_samples, 1)), Xz])

        # Regularisation matrix: alpha * I, but DO NOT penalise the intercept
        # (top-left entry zeroed). w = (XtX + alpha*R)^-1 Xt y.
        n_aug = Xa.shape[1]
        R = np.eye(n_aug)
        R[0, 0] = 0.0
        XtX = Xa.T @ Xa
        Xty = Xa.T @ y
        w = np.linalg.solve(XtX + alpha * R, Xty)

        self.intercept = float(w[0])
        self.coef = w[1:]
        return self

    # -- prediction ---------------------------------------------------------
    def _standardize(self, X: np.ndarray) -> np.ndarray:
        return (np.asarray(X, dtype=float) - self.means) / self.stds

    def predict_log(self, X: np.ndarray) -> np.ndarray:
        """Predicted ``log(price)`` for a raw feature matrix ``X``."""
        Xz = self._standardize(X)
        return self.intercept + Xz @ self.coef

    def contributions(self, x: np.ndarray) -> Dict[str, float]:
        """Per-feature additive contribution (in log space) for one card.

        contribution_i = coef_i * ((x_i - mean_i) / std_i). The sum of these
        plus the intercept is the predicted log-price.
        """
        xz = self._standardize(np.asarray(x, dtype=float).reshape(1, -1))[0]
        return {f: float(self.coef[i] * xz[i]) for i, f in enumerate(self.features)}

    # -- serialisation ------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "features": list(self.features),
            "means": [float(v) for v in self.means],
            "stds": [float(v) for v in self.stds],
            "coef": [float(v) for v in self.coef],
            "intercept": float(self.intercept),
            "n": int(self.n),
        }


# ---------------------------------------------------------------------------
# Per-card prediction record
# ---------------------------------------------------------------------------
class CardPrediction:
    """Per-card output of the model.

    Attributes:
      card_id       : the card's id
      cluster       : the cluster key whose model produced this prediction
      market_price  : the observed market price (the regression target source)
      expected_price: exp(predicted log-price)
      residual_pct  : (market - expected) / expected  (negative => underpriced)
      contributions : {feature: additive log-space contribution}
    """

    __slots__ = (
        "card_id",
        "cluster",
        "market_price",
        "expected_price",
        "residual_pct",
        "contributions",
    )

    def __init__(
        self,
        card_id: str,
        cluster: str,
        market_price: Optional[float],
        expected_price: float,
        residual_pct: Optional[float],
        contributions: Dict[str, float],
    ):
        self.card_id = card_id
        self.cluster = cluster
        self.market_price = market_price
        self.expected_price = expected_price
        self.residual_pct = residual_pct
        self.contributions = contributions

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "cluster": self.cluster,
            "market_price": self.market_price,
            "expected_price": self.expected_price,
            "residual_pct": self.residual_pct,
            "contributions": self.contributions,
        }


# ---------------------------------------------------------------------------
# Model result container
# ---------------------------------------------------------------------------
class ModelResult:
    """Result of :func:`fit`.

    Holds the fitted cluster models, a global fallback model, and a per-card
    prediction map. Supports ``export(path)`` to serialise everything the
    frontend needs into ``model.json``.
    """

    GLOBAL_KEY = "__global__"

    def __init__(
        self,
        features: Sequence[str],
        cluster_models: Dict[str, _ClusterModel],
        global_model: _ClusterModel,
        predictions: Dict[str, CardPrediction],
    ):
        self.features: List[str] = list(features)
        self.cluster_models = cluster_models
        self.global_model = global_model
        self.predictions = predictions

    # -- convenience accessors ---------------------------------------------
    def __getitem__(self, card_id: str) -> CardPrediction:
        return self.predictions[card_id]

    def get(self, card_id: str) -> Optional[CardPrediction]:
        return self.predictions.get(card_id)

    def r2_log(self) -> float:
        """R^2 in log space = squared correlation of expected vs actual log-price.

        Computed only over cards with a real market price.
        """
        actual, pred = [], []
        for p in self.predictions.values():
            if p.market_price is not None and p.market_price > 0 and p.expected_price > 0:
                actual.append(math.log(p.market_price))
                pred.append(math.log(p.expected_price))
        if len(actual) < 2:
            return float("nan")
        a = np.asarray(actual)
        b = np.asarray(pred)
        if a.std() < 1e-12 or b.std() < 1e-12:
            return float("nan")
        r = np.corrcoef(a, b)[0, 1]
        return float(r * r)

    def most_underpriced(self, n: int = 3) -> List[CardPrediction]:
        """Cards with the most-negative residual_pct (market far below expected)."""
        scored = [
            p for p in self.predictions.values() if p.residual_pct is not None
        ]
        scored.sort(key=lambda p: p.residual_pct)
        return scored[:n]

    # -- export -------------------------------------------------------------
    def export(self, path) -> dict:
        """Write ``model.json`` and return the serialised dict.

        Structure::

            {
              "features": [ ...ordered feature names... ],
              "feature_meta": { name: {label,status,min,max}, ... },  # display
              "clusters": {
                 "<rarity tier>": {features,means,stds,coef,intercept,n},
                 ...
              },
              "global": {features,means,stds,coef,intercept,n}
            }

        The frontend recomputes, for a card in cluster C:
            expected = exp(intercept + Σ coef_i * ((x_i - mean_i) / std_i))
        falling back to ``global`` when the card's cluster is absent.
        """
        payload = {
            "features": list(self.features),
            # FEATURES display metadata straight from config (label/status/min/max)
            # so sliders in the browser know their ranges and labels.
            "feature_meta": {f: config.FEATURES[f] for f in self.features},
            "clusters": {
                key: m.to_dict() for key, m in self.cluster_models.items()
            },
            "global": self.global_model.to_dict(),
        }
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2))
        return payload


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def _cluster_key(card: dict) -> str:
    """Cluster a card by its rarity tier (falling back to 'Unknown')."""
    return card.get("rarity") or "Unknown"


def _build_matrix(
    cards: Sequence[dict],
    features: Dict[str, Dict[str, float]],
    feature_names: Sequence[str],
):
    """Build (X, y, ids) for the priced cards among ``cards``.

    ``features`` maps card_id -> {feature: value}. Missing feature values
    default to 0.0. Only cards with a positive market price are used for
    training (target is ``log(market_price)``).
    """
    X, y, ids = [], [], []
    for c in cards:
        cid = c["id"]
        mp = c.get("market_price")
        if mp is None or mp <= 0:
            continue
        fv = features.get(cid)
        if fv is None:
            continue
        row = [float(fv.get(name, 0.0) or 0.0) for name in feature_names]
        X.append(row)
        y.append(math.log(mp))
        ids.append(cid)
    if not X:
        return np.empty((0, len(feature_names))), np.empty((0,)), []
    return np.asarray(X, dtype=float), np.asarray(y, dtype=float), ids


def fit(
    cards: Sequence[dict],
    features: Dict[str, Dict[str, float]],
    feature_names: Optional[Sequence[str]] = None,
    min_cluster_size: int = config.MIN_CLUSTER_SIZE,
    alpha: float = config.RIDGE_ALPHA,
) -> ModelResult:
    """Fit the clustered ridge price model.

    Args:
      cards: list of NormalizedCard dicts (see CONTRACT.md).
      features: {card_id: {feature_name: value}} as produced by signals.py.
      feature_names: which features to use, in order. Defaults to the keys of
        ``config.FEATURES`` (the contract's feature set).
      min_cluster_size: clusters with fewer priced cards than this fall back to
        the global model. Defaults to ``config.MIN_CLUSTER_SIZE``.
      alpha: ridge L2 strength. Defaults to ``config.RIDGE_ALPHA``.

    Returns:
      ModelResult with per-card predictions, the fitted cluster models, and a
      global fallback model.

    Every priced card receives a prediction. A card whose own cluster is too
    small (or which is unpriced) is still scored — using the global model — so
    the frontend always has an ``expected_price`` to show.
    """
    if feature_names is None:
        feature_names = list(config.FEATURES.keys())
    feature_names = list(feature_names)

    # --- global model (always fit; used as the universal fallback) ---------
    Xg, yg, _ = _build_matrix(cards, features, feature_names)
    global_model = _ClusterModel(feature_names)
    if Xg.shape[0] >= 1:
        global_model.fit(Xg, yg, alpha)

    # --- group cards by cluster (rarity tier) ------------------------------
    clusters: Dict[str, List[dict]] = {}
    for c in cards:
        clusters.setdefault(_cluster_key(c), []).append(c)

    cluster_models: Dict[str, _ClusterModel] = {}
    # which model each cluster's cards are scored with (its own or the global)
    model_for_cluster: Dict[str, _ClusterModel] = {}

    for key, group in clusters.items():
        Xc, yc, _ = _build_matrix(group, features, feature_names)
        if Xc.shape[0] >= min_cluster_size:
            m = _ClusterModel(feature_names).fit(Xc, yc, alpha)
            cluster_models[key] = m
            model_for_cluster[key] = m
        else:
            # Too small to fit on its own -> use the global model.
            model_for_cluster[key] = global_model

    # --- per-card predictions ---------------------------------------------
    predictions: Dict[str, CardPrediction] = {}
    for c in cards:
        cid = c["id"]
        key = _cluster_key(c)
        model = model_for_cluster.get(key, global_model)
        fv = features.get(cid)
        if fv is None:
            continue  # cannot score a card with no features
        x = np.asarray(
            [float(fv.get(name, 0.0) or 0.0) for name in feature_names], dtype=float
        )
        pred_log = float(model.predict_log(x.reshape(1, -1))[0])
        expected = math.exp(pred_log)
        mp = c.get("market_price")
        if mp is not None and expected > 0:
            residual_pct = (mp - expected) / expected
        else:
            residual_pct = None
        predictions[cid] = CardPrediction(
            card_id=cid,
            cluster=key,
            market_price=mp,
            expected_price=expected,
            residual_pct=residual_pct,
            contributions=model.contributions(x),
        )

    return ModelResult(
        features=feature_names,
        cluster_models=cluster_models,
        global_model=global_model,
        predictions=predictions,
    )


def export(result: ModelResult, path) -> dict:
    """Module-level convenience wrapper around :meth:`ModelResult.export`."""
    return result.export(path)


# ---------------------------------------------------------------------------
# Self-test  (python -m pipeline.model)
# ---------------------------------------------------------------------------
# Exercises the math end to end on the cached real data. Per the task brief:
#   * use the LIVE features from signals.py when it exists, otherwise compute a
#     faithful fallback inline (signals.py is owned by another module and may
#     not be built yet);
#   * ADD a synthetic ``pull_cost`` = log(market_price) as a stand-in, purely to
#     exercise the model math (real pull_cost needs pullrates + pack prices);
#   * fit on the cached cards, print R^2 (corr of expected vs actual in log
#     space) and the 3 most-underpriced cards by residual_pct.
def _load_cards() -> List[dict]:
    return json.loads((config.NORMALIZED / "cards.json").read_text())


def _months_since(release_date: Optional[str], today: "object" = None) -> float:
    """Whole-ish months from release_date (YYYY-MM-DD) to today."""
    import datetime as _dt

    if not release_date:
        return 0.0
    today = today or _dt.date.today()
    try:
        y, m, d = (int(x) for x in release_date.split("-"))
        rel = _dt.date(y, m, d)
    except Exception:
        return 0.0
    return max(0.0, (today - rel).days / 30.4375)


def _fallback_live_features(cards: List[dict]) -> Dict[str, Dict[str, float]]:
    """Compute the *live* features inline, faithful to CONTRACT.md signals.

    Used only by the self-test when signals.py is unavailable. Produces:
    char_premium (0-10), scarcity (0-10), months_since_release, set_rank (0-1),
    and the three neutral-mid stubs (demand_pressure, grading_intensity,
    universal_appeal). ``pull_cost`` is added separately as a synthetic stand-in.
    """
    # --- char_premium: percentile of a base_name's mean price, scaled 0-10 ---
    by_base: Dict[str, List[float]] = {}
    for c in cards:
        mp = c.get("market_price")
        if mp is not None and mp > 0:
            by_base.setdefault(c.get("base_name") or c["name"], []).append(mp)
    base_mean = {b: float(np.mean(v)) for b, v in by_base.items()}
    bases = sorted(base_mean, key=lambda b: base_mean[b])
    base_pct = {b: (i / (len(bases) - 1) if len(bases) > 1 else 0.5)
                for i, b in enumerate(bases)}

    # --- set_rank: market-price percentile within the card's set -------------
    by_set: Dict[str, List[tuple]] = {}
    for c in cards:
        mp = c.get("market_price")
        if mp is not None and mp > 0:
            by_set.setdefault(c["set_id"], []).append((c["id"], mp))
    set_rank: Dict[str, float] = {}
    for sid, rows in by_set.items():
        rows.sort(key=lambda r: r[1])
        n = len(rows)
        for i, (cid, _mp) in enumerate(rows):
            set_rank[cid] = i / (n - 1) if n > 1 else 0.5

    # --- scarcity: blend rarity tier scarcity with age (out-of-print) --------
    # Rarer tier (lower TIER_PROB) -> higher scarcity; older -> higher.
    tier_prob = {
        "Common": 1.0, "Uncommon": 1.0, "Rare": 1.0, "ACE SPEC Rare": 0.083,
        "Double Rare": 0.125, "Ultra Rare": 0.083, "Illustration Rare": 0.167,
        "Special Illustration Rare": 0.025, "Hyper Rare": 0.02,
        "Shiny Rare": 0.20, "Shiny Ultra Rare": 0.033, "Unknown": 0.05,
    }
    ages = [_months_since(c.get("release_date")) for c in cards]
    max_age = max(ages) if ages else 1.0

    out: Dict[str, Dict[str, float]] = {}
    for c in cards:
        cid = c["id"]
        base = c.get("base_name") or c["name"]
        rarity = c.get("rarity") or "Unknown"
        # rarity scarcity: invert per-pack prob into 0-1, then blend with age.
        prob = tier_prob.get(rarity, 0.05)
        rarity_scarcity = 1.0 - prob  # rarer -> closer to 1
        age = _months_since(c.get("release_date"))
        age_norm = (age / max_age) if max_age > 0 else 0.0
        scarcity = 10.0 * (0.7 * rarity_scarcity + 0.3 * age_norm)
        out[cid] = {
            "char_premium": 10.0 * base_pct.get(base, 0.5),
            "scarcity": scarcity,
            "months_since_release": age,
            "set_rank": set_rank.get(cid, 0.5),
            # neutral-mid stubs (awaiting their feeds)
            "demand_pressure": 10.0,
            "grading_intensity": 5.0,
            "universal_appeal": 5.0,
        }
    return out


def _self_test() -> None:
    cards = _load_cards()
    priced = [c for c in cards if c.get("market_price") is not None]
    print(f"Loaded {len(cards)} cards ({len(priced)} priced) from cache.")

    # 1) Live features: prefer signals.py, else faithful inline fallback.
    try:
        from . import signals  # type: ignore

        feats = signals.compute_features(cards)
        src = "signals.compute_features"
    except Exception as exc:  # ModuleNotFoundError or anything signals raises
        feats = _fallback_live_features(cards)
        src = f"inline fallback ({type(exc).__name__})"
    print(f"Live features from: {src}")

    # 2) Synthetic pull_cost stand-in = log(market_price) just to exercise math.
    #    (Real pull_cost = pack_price / pull_rate, owned by pullrates.py.)
    for c in cards:
        mp = c.get("market_price")
        feats.setdefault(c["id"], {})["pull_cost"] = (
            math.log(mp) if (mp is not None and mp > 0) else 0.0
        )

    # 3) Fit the clustered ridge model on the cached data.
    result = fit(cards, feats)

    fitted = sorted(result.cluster_models.keys())
    print(
        f"Fit {len(result.cluster_models)} per-cluster models "
        f"(MIN_CLUSTER_SIZE={config.MIN_CLUSTER_SIZE}, RIDGE_ALPHA={config.RIDGE_ALPHA})."
    )
    print(f"  Clusters with own model: {fitted}")
    small = sorted(
        k for k in {(_cluster_key(c)) for c in cards}
        if k not in result.cluster_models
    )
    if small:
        print(f"  Clusters using global fallback: {small}")

    # 4) Report R^2 in log space.
    r2 = result.r2_log()
    print(f"\nR^2 (corr of expected vs actual, log space): {r2:.4f}")

    # 5) Three most-underpriced cards by residual_pct (most negative first).
    print("\n3 most-underpriced cards (market far below expected):")
    by_id = {c["id"]: c for c in cards}
    for p in result.most_underpriced(3):
        c = by_id[p.card_id]
        print(
            f"  {c['name']:<28} [{c['rarity']:<24}] {c['set_name']:<20} "
            f"market=${p.market_price:>8.2f}  expected=${p.expected_price:>8.2f}  "
            f"residual={p.residual_pct * 100:+7.1f}%"
        )

    # 6) Export model.json and round-trip verify one prediction client-side.
    out_path = config.SITE_DATA / "model.json"
    payload = result.export(out_path)
    print(f"\nExported model -> {out_path}")
    print(
        f"  clusters in model.json: {len(payload['clusters'])} "
        f"(+ global), features: {payload['features']}"
    )

    # Verify the browser formula reproduces our prediction for a sample card.
    sample = result.most_underpriced(1)[0]
    c = by_id[sample.card_id]
    cl = payload["clusters"].get(sample.cluster, payload["global"])
    fn = cl["features"]
    fvals = feats[sample.card_id]
    recomputed = cl["intercept"] + sum(
        cl["coef"][i] * ((float(fvals.get(fn[i], 0.0) or 0.0) - cl["means"][i]) / cl["stds"][i])
        for i in range(len(fn))
    )
    recomputed = math.exp(recomputed)
    print(
        f"  client-formula check on '{c['name']}': "
        f"expected=${sample.expected_price:.4f} vs recomputed=${recomputed:.4f} "
        f"(match={abs(recomputed - sample.expected_price) < 1e-6})"
    )


if __name__ == "__main__":
    _self_test()
