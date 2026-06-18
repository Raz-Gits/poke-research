"""Google Trends 'Universal Appeal' collector — a real, free demand signal.

Mainstream search interest per Pokémon character (Google Trends, via pytrends —
free, no key). This is one of the reference site's three demand signals
("Universal Appeal"). Unlike eBay/PSA, Trends exposes HISTORY, so the resulting
feature is BACKTESTABLE: we store weekly interest per character and can read the
value as-of any past date.

Cross-query comparability: Trends rescales each query 0-100 by its own max, so
scores from different batches aren't directly comparable. We include a fixed
ANCHOR term in every batch and divide by it, making every character's interest a
ratio to the same reference (Pikachu) — comparable across batches and over time.

Output: ``data/trends.json`` ::

    {
      "anchor": "Pikachu",
      "as_of": "<date passed in by caller>",
      "characters": {
        "Charizard": {"score": 8.7, "weekly": {"2024-02-04": 0.93, ...}},
        ...
      }
    }

``score`` is a 0-10 'universal appeal' from the recent anchor-ratio (log-shaped).
This collector only reads public aggregate search interest.
"""
from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Dict, List, Optional

try:
    from pipeline.config import DATA, NORMALIZED
except Exception:  # pragma: no cover
    DATA = Path(__file__).resolve().parent.parent / "data"
    NORMALIZED = DATA / "normalized"

log = logging.getLogger("collectors.trends")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

OUT_PATH = DATA / "trends.json"
ANCHOR = "Pikachu"          # ubiquitous reference term in every batch
BATCH = 4                   # 4 characters + anchor = 5 (Trends max per query)
TIMEFRAME = "today 5-y"     # weekly granularity, long enough to backtest
GEO = "US"
MAX_CHARACTERS = 160        # cap the fetch (rate limits); top-N by card value


def _characters(limit: int = MAX_CHARACTERS) -> List[str]:
    """Distinct Pokémon character names worth tracking, richest cards first."""
    cards = json.loads((NORMALIZED / "cards.json").read_text())
    best: Dict[str, float] = {}
    for c in cards:
        if c.get("supertype") != "Pokémon":
            continue
        name = c.get("base_name") or c.get("name")
        if not name:
            continue
        best[name] = max(best.get(name, 0.0), c.get("market_price") or 0.0)
    ranked = sorted(best, key=lambda n: -best[n])
    ranked = [n for n in ranked if n != ANCHOR]
    return ranked[:limit]


def fetch(limit: int = MAX_CHARACTERS, as_of: Optional[str] = None,
          pause: float = 2.0) -> dict:
    """Fetch anchor-normalized weekly Trends interest for each character.

    Resumable: merges into an existing ``data/trends.json`` so a 429 mid-run
    doesn't lose progress (re-run to fill the rest).
    """
    from pytrends.request import TrendReq

    chars = _characters(limit)
    out = {"anchor": ANCHOR, "as_of": as_of, "characters": {}}
    if OUT_PATH.exists():
        try:
            prev = json.loads(OUT_PATH.read_text())
            out["characters"] = prev.get("characters", {})
        except Exception:  # pragma: no cover
            pass

    todo = [c for c in chars if c not in out["characters"]]
    log.info("trends: %d characters to fetch (%d cached)", len(todo), len(chars) - len(todo))
    pytrends = TrendReq(hl="en-US", tz=360)

    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        terms = [ANCHOR] + batch
        for attempt in range(4):
            try:
                pytrends.build_payload(terms, timeframe=TIMEFRAME, geo=GEO)
                df = pytrends.interest_over_time()
                break
            except Exception as e:  # pragma: no cover - network/429
                wait = pause * (2 ** attempt)
                log.warning("batch %s failed (%s); retry in %.0fs", batch, type(e).__name__, wait)
                time.sleep(wait)
        else:
            log.warning("giving up on batch %s", batch)
            continue
        if df is None or df.empty or ANCHOR not in df:
            continue
        anchor_series = df[ANCHOR].replace(0, math.nan)
        for name in batch:
            if name not in df:
                continue
            ratio = (df[name] / anchor_series).dropna()       # interest relative to Pikachu
            weekly = {d.strftime("%Y-%m-%d"): round(float(v), 4) for d, v in ratio.items()}
            recent = list(ratio.tail(8))                       # last ~2 months
            mean_recent = sum(recent) / len(recent) if recent else 0.0
            out["characters"][name] = {"score": _to_score(mean_recent), "weekly": weekly}
        out["characters"][ANCHOR] = {"score": 10.0, "weekly": {}}  # anchor = top by definition
        OUT_PATH.write_text(json.dumps(out))                   # checkpoint each batch
        log.info("  fetched %s (%d/%d done)", batch, len(out["characters"]), len(chars) + 1)
        time.sleep(pause)

    out["as_of"] = as_of
    OUT_PATH.write_text(json.dumps(out))
    log.info("trends: wrote %d characters -> %s", len(out["characters"]), OUT_PATH)
    return out


def _to_score(ratio: float) -> float:
    """Anchor-ratio -> 0-10 universal-appeal score (log-shaped, Pikachu≈10)."""
    if ratio <= 0:
        return 0.0
    # ratio 1.0 (== Pikachu) -> 10; 0.1 -> ~6; 0.01 -> ~2. log10 mapping.
    return round(max(0.0, min(10.0, 10.0 + 4.0 * math.log10(ratio))), 3)


if __name__ == "__main__":  # pragma: no cover
    import sys
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else MAX_CHARACTERS
    res = fetch(limit=lim)
    cs = res["characters"]
    top = sorted(cs, key=lambda n: -cs[n]["score"])[:15]
    print(f"fetched {len(cs)} characters. Top universal-appeal scores:")
    for n in top:
        print(f"  {n:20s} {cs[n]['score']}")
