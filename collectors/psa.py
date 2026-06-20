"""PSA grading-intensity collector — population reports via PSA's free Public API.

GRADING INTENSITY is a real per-card DEMAND signal: how many copies of a card
have been graded by PSA, and how many are PSA 10. Heavy grading = intense
collector demand (and a large graded-supply overhang) — exactly the per-card
demand axis the price model lacks on mature blue-chips. A quick check confirmed
it differentiates: our overvalued hype chase cards (Umbreon 19k, Mew 48k graded)
dwarf an undervalued peer (Eevee 8.7k).

The Public API (https://api.psacard.com/publicapi/) returns population ONLY by
PSA "specID" and offers NO card->spec search, so we keep a curated
``data/psa_specs.json`` map (card_id -> specID), seeded by looking specs up on
psacard.com (the specID is the number in a /spec/psa/<id> URL). Pop changes
slowly, so we cache hard and refresh on a long cadence, staying under the
~100 calls/day free tier.

Auth: header ``authorization: bearer <PSA_API_TOKEN>`` (from .env) + a normal
User-Agent — PSA sits behind Cloudflare, which 403s the default urllib UA
(error 1010). This reads PUBLIC aggregate population only; no PII, no scraping.

Output ``data/psa_pop.json``::

    {
      "as_of": "<date>",
      "cards": {
        "sv8pt5-161": {"spec": 12632263, "total": 19307, "psa10": 5761,
                        "psa9": 9638, "psa10_rate": 0.298, "fetched": "<date>"},
        ...
      }
    }
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

try:
    from pipeline.config import DATA
except Exception:  # pragma: no cover
    DATA = Path(__file__).resolve().parent.parent / "data"

log = logging.getLogger("collectors.psa")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

BASE = "https://api.psacard.com/publicapi"
POP_URL = BASE + "/pop/GetPSASpecPopulation/{spec}"
# PSA is behind Cloudflare; the default urllib UA is hard-blocked (error 1010).
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

SPECS_PATH = DATA / "psa_specs.json"   # curated card_id -> specID
OUT_PATH = DATA / "psa_pop.json"       # collected population per card

DAILY_CALL_BUDGET = 80     # free tier is ~100/day; leave headroom
CACHE_TTL_DAYS = 14        # pop moves slowly — don't re-fetch within two weeks
REQUEST_PAUSE_S = 0.3      # gentle pacing


def _token() -> str:
    import os
    return os.environ.get("PSA_API_TOKEN", "")


def load_specs() -> Dict[str, int]:
    """card_id -> PSA specID. Empty if the curated map doesn't exist yet."""
    if not SPECS_PATH.exists():
        return {}
    try:
        raw = json.loads(SPECS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    # tolerate {"cards": {...}} or a flat {card_id: spec} mapping
    m = raw.get("cards", raw) if isinstance(raw, dict) else {}
    return {k: int(v) for k, v in m.items() if str(v).strip().isdigit()}


def fetch_pop(spec: int, token: str) -> Optional[dict]:
    """GET population for one specID. None on any error (caller skips it)."""
    req = urllib.request.Request(
        POP_URL.format(spec=spec),
        headers={"authorization": f"bearer {token}", "User-Agent": UA,
                 "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log.info("spec %s: no population data (404)", spec)
        else:
            log.warning("spec %s: HTTP %s", spec, e.code)
        return None
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:  # pragma: no cover
        log.warning("spec %s: %s", spec, type(e).__name__)
        return None


def intensity(pop_json: dict) -> dict:
    """Reduce a raw PSA pop payload to the grading-intensity fields we store."""
    p = pop_json.get("PSAPop") or {}
    total = int(p.get("Total") or 0)
    g10 = int(p.get("Grade10") or 0)
    g9 = int(p.get("Grade9") or 0)
    return {
        "total": total,
        "psa10": g10,
        "psa9": g9,
        "psa10_rate": round(g10 / total, 4) if total else None,
    }


def collect(max_calls: int = DAILY_CALL_BUDGET) -> dict:
    """Fetch pop for every mapped card (cached/throttled), write data/psa_pop.json.

    Resumable + cache-aware: a card whose pop was fetched within CACHE_TTL_DAYS
    is kept as-is (no API call), so re-runs are cheap and stay under the free
    quota. Most-valuable cards aren't prioritized here — the spec map is small
    and curated — but the budget cap is enforced regardless.
    """
    token = _token()
    if not token or "your-psa" in token:
        log.warning("PSA_API_TOKEN not set -> skipping PSA collection.")
        return {}

    specs = load_specs()
    if not specs:
        log.warning("no curated specs in %s -> nothing to collect.", SPECS_PATH.name)
        return {}

    today = date.today()
    out = {"as_of": today.isoformat(), "cards": {}}
    if OUT_PATH.exists():
        try:
            out["cards"] = json.loads(OUT_PATH.read_text()).get("cards", {})
        except (json.JSONDecodeError, OSError):  # pragma: no cover
            pass

    fresh_cut = today - timedelta(days=CACHE_TTL_DAYS)
    calls = 0
    for card_id, spec in specs.items():
        prev = out["cards"].get(card_id)
        if prev and prev.get("fetched"):
            try:
                if datetime.strptime(prev["fetched"], "%Y-%m-%d").date() >= fresh_cut:
                    continue  # cached & fresh — skip
            except ValueError:  # pragma: no cover
                pass
        if calls >= max_calls:
            log.warning("PSA daily budget (%s) reached; %s cards still stale.",
                        max_calls, len(specs) - len(out["cards"]))
            break
        data = fetch_pop(spec, token)
        calls += 1
        time.sleep(REQUEST_PAUSE_S)
        if not data:
            continue
        row = intensity(data)
        row["spec"] = spec
        row["fetched"] = today.isoformat()
        out["cards"][card_id] = row

    out["as_of"] = today.isoformat()
    OUT_PATH.write_text(json.dumps(out, indent=2))
    log.info("PSA: %s cards in %s (%s API calls this run).",
             len(out["cards"]), OUT_PATH.name, calls)
    return out


if __name__ == "__main__":  # pragma: no cover
    res = collect()
    cards = res.get("cards", {})
    print(f"collected {len(cards)} cards. Highest grading intensity:")
    for cid, r in sorted(cards.items(), key=lambda kv: -(kv[1].get("total") or 0))[:15]:
        print(f"  {cid:14s} total={r.get('total'):>7}  PSA10={r.get('psa10'):>6}  "
              f"10-rate={r.get('psa10_rate')}")
