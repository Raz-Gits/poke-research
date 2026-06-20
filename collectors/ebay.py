"""eBay market collector — daily per-card snapshots of live listings.

We make *demand pressure* and *supply saturation* real the only way eBay's
free API allows: the Browse API exposes **ACTIVE listings only** (there is no
public sold/completed endpoint), so we store one snapshot of active listings
per card per day and **infer sold-vs-delisted by diffing day-over-day**, with
outlier cleaning. Three code paths live here:

1. ``collect_snapshot(cards, out_dir, snapshot_date)`` — the daily collector.
   * **LIVE** when ``EBAY_APP_ID`` (+ ``EBAY_CERT_ID``) env vars are set: gets an
     OAuth client-credentials *application* token and queries the Browse API
     (``GET /buy/browse/v1/item_summary/search``) per card, parsing active item
     summaries into ``active_listings`` + ``avg_price``. Prices are first passed
     through a **market-anchored band** (drop listings <50% / >4x the card's
     TCGplayer ``market_price``) so same-name mismatches — a chase Illustration
     Rare query also returning the $2 base print — can't collapse the average,
     then IQR-cleaned.
   * **NO-OP** (graceful) when no key is set: it writes a fully-formed snapshot
     of neutral rows and logs clearly, so the build never breaks.
   The live collector records ONLY ``active_listings`` + ``avg_price`` per card;
   the flow fields (new/ended/est_sold/est_unsold) are derived afterward by
   :func:`diff_snapshots` against yesterday's file.

2. ``diff_snapshots(prev, curr)`` — diffs two consecutive daily snapshots into
   ``new_listings``, ``ended_listings`` and an ``est_sold`` / ``est_unsold``
   split (ended listings whose price sat at/below market are more likely sold),
   cleaning outliers.

3. ``simulate_history(cards, days, out_dir, end_date)`` — writes ``days``
   deterministic synthetic snapshots so the whole market-dynamics stack is
   demonstrable offline, *before* a key or real history exists. ~15% of cards
   get a clear tightening/loosening trend; active-listing counts scale
   inversely with rarity/price so the movers board has genuine signal.

Snapshot file: ``data/snapshots/ebay-<YYYY-MM-DD>.json`` ::

    {
      "<card_id>": {
        "active_listings": int | None,   # live BIN+auction count today (cleaned)
        "new_listings":    int | None,   # appeared since yesterday
        "ended_listings":  int | None,   # gone since yesterday
        "est_sold":        int | None,   # of the ended ones, estimated SOLD
        "est_unsold":      int | None,   # of the ended ones, relisted/expired
        "avg_price":       float | None  # outlier-cleaned mean active BIN price
      },
      ...
    }

Downstream, ``pipeline/market_dynamics.compute()`` reads a *history* of these
files and produces:
  * ``demand_pressure``  = est_sold(recent) / (active + est_sold)   as a %
  * ``supply_saturation`` = mean(active, 7d) / mean(active, 30d)
    ( >1 loosening/cooling, <1 tightening/heating ).
With <2 days of history it returns the neutral ``awaiting_data`` fallback.

Hygiene: cache the OAuth token (~2h life), exponential backoff on 429, page
politely, and respect the ~5k calls/day free quota (2143 cards fits one full
sweep/day). This collector only *reads* public active listings — it never
scrapes, evades bot protection, or attempts checkout.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from pipeline.config import SNAPSHOTS
except Exception:  # pragma: no cover - keep collector runnable in isolation
    SNAPSHOTS = Path(__file__).resolve().parent.parent / "data" / "snapshots"

log = logging.getLogger("collectors.ebay")
if not log.handlers:  # make standalone runs (python collectors/ebay.py) chatty
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# ---------------------------------------------------------------------------
# eBay Browse API constants
# ---------------------------------------------------------------------------
EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
EBAY_SCOPE = "https://api.ebay.com/oauth/api_scope"
EBAY_MARKETPLACE = "EBAY_US"
# Trading Card Singles category (eBay US). Narrows the search to real singles.
TRADING_CARD_CATEGORY = "183454"
PAGE_LIMIT = 200          # max itemSummaries per Browse page
MAX_PAGES_PER_CARD = 1    # 1 page (200 listings) is plenty for a demand signal;
                          # 2 pages at 50ms pacing tripped eBay's per-second rate
                          # limit -> 429 storm -> 65-min backoff crawl. Keep it 1.
DAILY_CALL_BUDGET = 4800  # stay under the ~5k/day free Browse quota
REQUEST_PAUSE_S = 0.25    # ~4 req/s — under eBay's burst limit (was 0.05 = 20/s)
SWEEP_TIME_BUDGET_S = 420 # hard wall-clock cap (7 min): if rate-limiting drags the
                          # sweep past this, stop and write what we have. A sweep
                          # must NEVER hang for an hour again.
MAX_CONSECUTIVE_FAILS = 30  # if this many cards in a row come back empty (likely
                          # quota/rate exhaustion), abort early — don't grind.

# Price-sanity band, anchored to the card's TCGplayer market_price.
# eBay free-text search matches same-name printings: a chase Illustration Rare
# query ($198 market) also returns the $2 base version, and since the cheap
# copies dominate the distribution, IQR cleaning can't save it — avg_price
# collapses to ~$5. So we drop listings implausibly far from THIS card's market
# price BEFORE cleaning. This also tightens active_listings to the count of
# plausible real listings (a better demand signal) instead of every same-name hit.
PRICE_BAND_LOW = 0.5      # ignore listings priced below 50% of market (the main
                         # failure mode: chase card matched to cheap base versions)
PRICE_BAND_HIGH = 4.0    # ignore listings above 4x market (lots/bundles/slabs that
                         # slipped the graded filter); loose — IQR handles the rest
PRICE_BAND_MIN_ANCHOR = 2.0  # only band when market_price is a meaningful anchor;
                         # below this, fall back to IQR-only (cheap-card shipping noise)


# ---------------------------------------------------------------------------
# Snapshot row schema
# ---------------------------------------------------------------------------
ROW_KEYS = (
    "active_listings",
    "new_listings",
    "ended_listings",
    "est_sold",
    "est_unsold",
    "avg_price",
)


def _empty_row() -> Dict[str, Optional[float]]:
    """A correctly-shaped, value-free row — 'awaiting data', not fabricated."""
    return {k: None for k in ROW_KEYS}


# ---------------------------------------------------------------------------
# Price cleaning (shared by live parse, diff, and simulation)
# ---------------------------------------------------------------------------
def _clean_prices(prices: List[float]) -> List[float]:
    """Drop statistical outliers via a 1.5*IQR fence. Pure stdlib.

    eBay active listings are noisy: graded slabs, lots, and aspirational
    BIN prices all inflate the tail. With few points we keep everything; with
    enough we trim values outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR].
    """
    vals = sorted(p for p in prices if p is not None and p > 0)
    if len(vals) < 4:
        return vals

    def _quantile(s: List[float], q: float) -> float:
        idx = q * (len(s) - 1)
        lo = int(idx)
        hi = min(lo + 1, len(s) - 1)
        frac = idx - lo
        return s[lo] * (1 - frac) + s[hi] * frac

    q1, q3 = _quantile(vals, 0.25), _quantile(vals, 0.75)
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    cleaned = [v for v in vals if lo <= v <= hi]
    return cleaned or vals


def _mean(vals: List[float]) -> Optional[float]:
    return round(sum(vals) / len(vals), 2) if vals else None


def _apply_price_band(
    prices: List[float], market_price: Optional[float]
) -> Tuple[List[float], int]:
    """Drop listings implausibly far from the card's TCGplayer market price.

    Returns ``(kept, n_dropped)``. No-op (keeps everything) when there's no
    usable anchor — ``market_price`` missing or below ``PRICE_BAND_MIN_ANCHOR`` —
    so cheap/unpriced cards fall back to IQR-only cleaning. The low fence is the
    important one (kills cheap same-name mismatches); the high fence is a loose
    backstop for lots/slabs the keyword filter missed.
    """
    if not market_price or market_price < PRICE_BAND_MIN_ANCHOR:
        return prices, 0
    lo = market_price * PRICE_BAND_LOW
    hi = market_price * PRICE_BAND_HIGH
    kept = [p for p in prices if lo <= p <= hi]
    return kept, len(prices) - len(kept)


# ---------------------------------------------------------------------------
# (1) LIVE path — OAuth + Browse API
# ---------------------------------------------------------------------------
def _ebay_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Return (app_id, cert_id) from env, or (None, None) if not configured."""
    return os.environ.get("EBAY_APP_ID"), os.environ.get("EBAY_CERT_ID")


def _get_app_token(app_id: str, cert_id: str) -> Optional[str]:
    """OAuth2 client-credentials flow -> short-lived application access token.

    eBay tokens last ~2h. The caller caches the returned token for the run.
    Returns None on failure (so the collector degrades to a no-op snapshot).
    """
    basic = base64.b64encode(f"{app_id}:{cert_id}".encode()).decode()
    body = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "scope": EBAY_SCOPE}
    ).encode()
    req = urllib.request.Request(
        EBAY_OAUTH_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
        token = payload.get("access_token")
        if token:
            log.info("eBay OAuth token acquired (expires_in=%ss)", payload.get("expires_in"))
        return token
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        log.error("eBay OAuth failed: %s", exc)
        return None


def _build_query(card: dict) -> str:
    """Tight free-text query: name + set_name + 'pokemon' + number.

    Number disambiguates same-name printings; set_name pins the print run.
    """
    parts = [
        str(card.get("name") or card.get("base_name") or "").strip(),
        str(card.get("set_name") or "").strip(),
        "pokemon",
        str(card.get("number") or "").strip(),
    ]
    return " ".join(p for p in parts if p)


def _browse_request(token: str, q: str, offset: int) -> Optional[dict]:
    """One Browse item_summary/search call, with 429 backoff. None on error."""
    params = urllib.parse.urlencode(
        {
            "q": q,
            "category_ids": TRADING_CARD_CATEGORY,
            "filter": "buyingOptions:{FIXED_PRICE|AUCTION}",
            "limit": PAGE_LIMIT,
            "offset": offset,
        }
    )
    req = urllib.request.Request(
        f"{EBAY_BROWSE_URL}?{params}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE,
            "Content-Type": "application/json",
        },
        method="GET",
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 429:  # rate limited -> exponential backoff
                wait = 2 ** attempt
                log.warning("eBay 429; backing off %ss", wait)
                time.sleep(wait)
                continue
            log.error("eBay Browse HTTP %s for q=%r", exc.code, q)
            return None
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            log.error("eBay Browse error for q=%r: %s", q, exc)
            return None
    return None


def _is_graded(title: str) -> bool:
    """Heuristic: drop graded slabs so avg_price reflects raw singles."""
    t = title.lower()
    return any(g in t for g in (" psa ", " cgc ", " bgs ", " sgc ", "graded"))


def _fetch_card_market(card: dict, token: str) -> Dict[str, Optional[float]]:
    """Query the live Browse API for ONE card -> active_listings + avg_price.

    Records only the two directly-observable fields; flow fields stay None and
    are filled later by :func:`diff_snapshots` against yesterday's file.
    """
    q = _build_query(card)
    prices: List[float] = []
    for page in range(MAX_PAGES_PER_CARD):
        data = _browse_request(token, q, offset=page * PAGE_LIMIT)
        time.sleep(REQUEST_PAUSE_S)
        if not data:
            break
        summaries = data.get("itemSummaries") or []
        for it in summaries:
            title = str(it.get("title") or "")
            if _is_graded(f" {title} "):
                continue
            price = it.get("price") or {}
            if str(price.get("currency")) != "USD":
                continue
            try:
                val = float(price.get("value"))
            except (TypeError, ValueError):
                continue
            prices.append(val)
        # Stop early if we've consumed all results.
        if len(summaries) < PAGE_LIMIT:
            break

    # Anchor to TCGplayer market first (kills cheap same-name mismatches), then
    # IQR-clean the survivors. Band BEFORE clean so the cheap copies can't skew
    # the IQR fence itself.
    banded, n_dropped = _apply_price_band(prices, card.get("market_price"))
    cleaned = _clean_prices(banded)
    row = _empty_row()
    row["active_listings"] = len(cleaned)
    row["avg_price"] = _mean(cleaned)
    # Visibility: log cards where the band removed a big share — these are the
    # match-noise cases we're fixing (and a watchlist if the band is too tight).
    if prices and n_dropped / len(prices) >= 0.5:
        log.info(
            "band: %s kept %s/%s listings near $%.2f market (q=%r)",
            card.get("id"), len(banded), len(prices),
            card.get("market_price") or 0.0, q,
        )
    return row


# ---------------------------------------------------------------------------
# (2) Day-over-day diff -> new / ended / est_sold / est_unsold
# ---------------------------------------------------------------------------
def diff_row(prev_row: Optional[dict], curr_row: dict) -> dict:
    """Diff ONE card's two consecutive daily rows into a filled flow row.

    This is the per-card kernel of :func:`diff_snapshots`. Given yesterday's and
    today's row for a single card (each at least an ``active_listings`` and
    optional ``avg_price``), it returns a fully-shaped row carrying today's
    ``active_listings``/``avg_price`` plus the inferred
    ``new_listings``/``ended_listings``/``est_sold``/``est_unsold``.

    ``prev_row`` may be ``None`` (the first day of history) — then there is no
    diff to take and the flow fields stay neutral. This is the function the
    market-dynamics history loader uses to backfill counts-only snapshots.
    """
    row = _empty_row()
    cur_active = curr_row.get("active_listings")
    row["active_listings"] = cur_active
    row["avg_price"] = curr_row.get("avg_price")

    prev_row = prev_row or {}
    prev_active = prev_row.get("active_listings")
    if cur_active is None or prev_active is None:
        return row  # no usable diff yet -> neutral flow

    delta = int(cur_active) - int(prev_active)
    row["new_listings"] = max(delta, 0)
    ended = max(-delta, 0)
    row["ended_listings"] = ended

    if ended == 0:
        row["est_sold"] = 0
        row["est_unsold"] = 0
        return row

    # Sold share from price drift: a steady/falling avg ask means the cheap
    # (likely-sold) copies cleared; a rising ask means weak listings expired.
    sold_share = 0.6  # neutral prior: most ended fixed-price listings sell
    prev_price, cur_price = prev_row.get("avg_price"), curr_row.get("avg_price")
    if prev_price and cur_price and prev_price > 0:
        drift = (cur_price - prev_price) / prev_price
        # drift <= 0 -> push toward sold (cap 0.85); drift > 0 -> toward unsold (floor 0.35)
        sold_share = max(0.35, min(0.85, 0.6 - 1.5 * drift))

    est_sold = int(round(ended * sold_share))
    row["est_sold"] = est_sold
    row["est_unsold"] = ended - est_sold
    return row


def diff_snapshots(prev: dict, curr: dict) -> dict:
    """Diff two consecutive daily snapshots into per-card flow fields.

    The Browse API hands us active listings only, so flow is *inferred*:

    * ``new_listings``   = how many more active listings than yesterday (net inflow).
    * ``ended_listings`` = how many fewer (net outflow) — the only demand window.
    * ``est_sold`` / ``est_unsold`` split the ended count: an ended listing is
      more likely SOLD when the card's price is at/below the prevailing market
      (cheap copies clear), and more likely RELISTED/EXPIRED (unsold) when it
      sat above market. We size the sold share by where ``curr.avg_price`` sits
      relative to ``prev.avg_price`` (a falling/steady ask => buyers cleared the
      cheap end => higher sold share).

    Parameters
    ----------
    prev, curr:
        ``{card_id: row}`` snapshots for two consecutive days. Rows need at
        least ``active_listings`` and (ideally) ``avg_price``.

    Returns
    -------
    dict
        ``{card_id: row}`` for every card in ``curr``, with
        ``active_listings``/``avg_price`` carried from ``curr`` and
        ``new_listings``/``ended_listings``/``est_sold``/``est_unsold`` filled.
        Cards whose active count is unknown stay neutral (awaiting data).
    """
    out: Dict[str, dict] = {}
    for cid, crow in curr.items():
        out[cid] = diff_row(prev.get(cid), crow)
    return out


# ---------------------------------------------------------------------------
# collect_snapshot — LIVE if keyed, graceful no-op otherwise
# ---------------------------------------------------------------------------
def collect_snapshot(
    cards: List[dict],
    out_dir: Optional[Path] = None,
    snapshot_date: Optional[date] = None,
) -> Path:
    """Write today's eBay snapshot for every card and return the file path.

    LIVE when ``EBAY_APP_ID`` (+ ``EBAY_CERT_ID``) are set: OAuth, then query the
    Browse API per card for ``active_listings`` + ``avg_price``, then fill the
    flow fields by diffing against yesterday's file (if present). Respects the
    daily call budget. With NO key it writes a neutral snapshot and logs that
    it's awaiting credentials — the build keeps working either way.
    """
    out_dir = Path(out_dir) if out_dir is not None else Path(SNAPSHOTS)
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_date = snapshot_date or date.today()
    out_path = out_dir / f"ebay-{snapshot_date.isoformat()}.json"

    app_id, cert_id = _ebay_credentials()
    if not (app_id and cert_id):
        # No key -> graceful no-op. But never CLOBBER an existing richer snapshot
        # for this date (e.g. one written by simulate_history): overwriting it
        # with neutral rows would wipe the est_sold/demand_pressure signal the
        # build is about to consume. Only write a fresh neutral file if none
        # exists, so the history loader always has a file and the build is safe.
        if out_path.exists():
            log.warning(
                "EBAY_APP_ID/EBAY_CERT_ID not set -> keeping existing %s "
                "(likely simulated); not overwriting with neutral rows.",
                out_path.name,
            )
            return out_path
        log.warning(
            "EBAY_APP_ID/EBAY_CERT_ID not set -> writing NEUTRAL snapshot "
            "(awaiting Browse API key). Run simulate_history() to demo offline."
        )
        snapshot = {c["id"]: _empty_row() for c in cards}
        out_path.write_text(json.dumps(snapshot, indent=2))
        return out_path

    token = _get_app_token(app_id, cert_id)
    if not token:
        log.error("Could not obtain eBay token -> writing NEUTRAL snapshot.")
        out_path.write_text(json.dumps({c["id"]: _empty_row() for c in cards}, indent=2))
        return out_path

    # LIVE sweep. Each card costs <= MAX_PAGES_PER_CARD calls; stay in budget.
    # Two circuit-breakers guarantee it can NEVER hang for an hour again:
    #   * wall-clock: stop after SWEEP_TIME_BUDGET_S regardless of progress.
    #   * consecutive-fail: if MAX_CONSECUTIVE_FAILS cards in a row come back
    #     empty (quota/rate exhaustion), abort — grinding won't help today.
    # Cards not reached are left as neutral rows so the history loader is happy.
    snapshot: Dict[str, dict] = {}
    calls = 0
    consec_fail = 0
    start = time.monotonic()
    aborted = False
    for card in cards:
        if (
            calls + MAX_PAGES_PER_CARD > DAILY_CALL_BUDGET
            or time.monotonic() - start > SWEEP_TIME_BUDGET_S
            or consec_fail >= MAX_CONSECUTIVE_FAILS
        ):
            if not aborted:
                log.warning(
                    "Sweep stopping early at %s cards (calls=%s, elapsed=%.0fs, "
                    "consec_fail=%s); remainder neutral.",
                    len(snapshot), calls, time.monotonic() - start, consec_fail,
                )
                aborted = True
            snapshot[card["id"]] = _empty_row()
            continue
        row = _fetch_card_market(card, token)
        snapshot[card["id"]] = row
        calls += MAX_PAGES_PER_CARD
        consec_fail = 0 if row.get("active_listings") else consec_fail + 1

    # Fill flow fields by diffing yesterday's snapshot, if we have one.
    prev_path = out_dir / f"ebay-{(snapshot_date - timedelta(days=1)).isoformat()}.json"
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text())
            snapshot = diff_snapshots(prev, snapshot)
            log.info("Diffed against %s for sold/unsold inference.", prev_path.name)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not diff against %s: %s", prev_path.name, exc)

    out_path.write_text(json.dumps(snapshot, indent=2))
    log.info("LIVE eBay snapshot written: %s (%s cards, %s API calls)", out_path, len(snapshot), calls)
    return out_path


# ---------------------------------------------------------------------------
# (3) SIMULATION — deterministic synthetic history for offline demo
# ---------------------------------------------------------------------------
# Inverse-supply anchor by rarity: rarer cards have far fewer active listings.
_RARITY_SUPPLY = {
    "Common": 320,
    "Uncommon": 240,
    "Rare": 150,
    "ACE SPEC Rare": 70,
    "Double Rare": 90,
    "Ultra Rare": 55,
    "Illustration Rare": 60,
    "Special Illustration Rare": 28,
    "Shiny Rare": 45,
    "Shiny Ultra Rare": 22,
    "Hyper Rare": 18,
    "MEGA_ATTACK_RARE": 16,
    "Mega Hyper Rare": 10,
    "Unknown": 80,
}
SIM_SEED = 20260617  # fixed -> fully deterministic output


def _base_supply(card: dict, rng: random.Random) -> int:
    """Plausible baseline active-listing count: scales inversely with rarity
    and price (expensive/rare cards have thin supply; commons are everywhere)."""
    base = _RARITY_SUPPLY.get(card.get("rarity"), _RARITY_SUPPLY["Unknown"])
    price = card.get("market_price") or 1.0
    # Price damps supply: a $200 card lists far less than a $0.30 bulk common.
    price_factor = 1.0 / (1.0 + max(price, 0.0) / 12.0)
    supply = base * (0.4 + 0.6 * price_factor)
    supply *= rng.uniform(0.8, 1.2)  # per-card idiosyncrasy
    return max(3, int(round(supply)))


def simulate_history(
    cards: List[dict],
    days: int = 30,
    out_dir: Optional[Path] = None,
    end_date: Optional[date] = None,
) -> List[Path]:
    """Write ``days`` deterministic synthetic ``ebay-<date>.json`` snapshots.

    Purpose: demonstrate the *entire* market-dynamics pipeline offline, before a
    key or real history exists. Output is fully deterministic
    (``random.Random(SIM_SEED)``), so re-running yields identical files.

    Each card gets a realistic baseline active-listing count (inverse to
    rarity/price). ~15% of cards are assigned a clear **tightening** (supply
    shrinking, hot) or **loosening** (supply growing, cooling) trend so the
    saturation movers board has genuine signal; the rest drift on a small
    random walk. ``avg_price`` tracks ``market_price`` with a small trend-linked
    drift, and the flow fields are produced by :func:`diff_snapshots` exactly as
    the live path would — so the simulation exercises the same inference code.

    Parameters
    ----------
    cards:     normalized card list (needs ``id``, ``rarity``, ``market_price``).
    days:      number of daily snapshots to write (oldest..end_date inclusive).
    out_dir:   target dir; defaults to ``data/snapshots``.
    end_date:  most-recent snapshot date; defaults to today.

    Returns
    -------
    list[Path]  written snapshot paths, oldest first.
    """
    out_dir = Path(out_dir) if out_dir is not None else Path(SNAPSHOTS)
    out_dir.mkdir(parents=True, exist_ok=True)
    end_date = end_date or date.today()
    rng = random.Random(SIM_SEED)

    # --- assign per-card trend profiles -----------------------------------
    # slope = active-listings change/day as a fraction of baseline:
    #   <0 tightening (supply leaving faster than it arrives -> hot)
    #   >0 loosening  (supply piling up -> cooling)
    profiles: Dict[str, dict] = {}
    for c in cards:
        base = _base_supply(c, rng)
        roll = rng.random()
        if roll < 0.075:          # ~7.5% clearly tightening
            slope = -rng.uniform(0.012, 0.030)
            kind = "tightening"
        elif roll < 0.15:         # ~7.5% clearly loosening
            slope = rng.uniform(0.012, 0.030)
            kind = "loosening"
        else:                     # the rest: flat-ish noise
            slope = rng.uniform(-0.004, 0.004)
            kind = "flat"
        profiles[c["id"]] = {
            "base": base,
            "slope": slope,
            "kind": kind,
            "noise": rng.uniform(0.04, 0.10),
            "price": c.get("market_price"),
            "rng": random.Random(int(rng.random() * 1e9)),  # per-card noise stream
        }

    # --- generate raw (active_listings + avg_price) snapshots per day ------
    # day index 0 = oldest, days-1 = end_date.
    dates: List[date] = [end_date - timedelta(days=(days - 1 - i)) for i in range(days)]
    raw_by_date: Dict[str, Dict[str, dict]] = {}

    for i, d in enumerate(dates):
        progress = i  # days elapsed from the start of the window
        rows: Dict[str, dict] = {}
        for cid, p in profiles.items():
            prng = p["rng"]
            # Deterministic supply path: baseline * (1 + slope*t) * noise.
            trend_mult = 1.0 + p["slope"] * progress
            noise = 1.0 + prng.uniform(-p["noise"], p["noise"])
            active = max(1, int(round(p["base"] * trend_mult * noise)))

            # Price tracks market with a mild, trend-linked drift + jitter.
            mkt = p["price"]
            if mkt is not None:
                # tightening (slope<0) nudges price up over time; loosening down.
                price_drift = 1.0 - p["slope"] * 4.0 * progress
                avg_price = round(
                    max(0.01, mkt * price_drift * (1.0 + prng.uniform(-0.04, 0.04))), 2
                )
            else:
                avg_price = None

            row = _empty_row()
            row["active_listings"] = active
            row["avg_price"] = avg_price
            rows[cid] = row
        raw_by_date[d.isoformat()] = rows

    # --- diff consecutive days to fill flow fields, then write ------------
    written: List[Path] = []
    prev_rows: Optional[Dict[str, dict]] = None
    for d in dates:
        curr_rows = raw_by_date[d.isoformat()]
        if prev_rows is None:
            snapshot = curr_rows  # first day: active+price only, neutral flow
        else:
            snapshot = diff_snapshots(prev_rows, curr_rows)
        path = out_dir / f"ebay-{d.isoformat()}.json"
        path.write_text(json.dumps(snapshot, indent=2))
        written.append(path)
        prev_rows = curr_rows

    log.info(
        "Simulated %s days of eBay history (%s..%s) for %s cards -> %s files",
        days, dates[0].isoformat(), dates[-1].isoformat(), len(cards), len(written),
    )
    return written


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    # Prefer the site cards.json (richer); fall back to normalized.
    for cand in (root / "docs" / "data" / "cards.json", root / "data" / "normalized" / "cards.json"):
        if cand.exists():
            cards = json.loads(cand.read_text())
            break
    else:  # pragma: no cover
        raise SystemExit("no cards.json found")

    out_dir = root / "data" / "snapshots"
    end = date(2026, 6, 18)
    print(f"Simulating 30 days of eBay history into {out_dir} ...")
    paths = simulate_history(cards, days=30, out_dir=out_dir, end_date=end)
    assert len(paths) == 30, f"expected 30 files, wrote {len(paths)}"
    for p in paths:
        assert p.exists(), f"missing {p}"

    # Validate schema on the latest snapshot.
    latest = json.loads(paths[-1].read_text())
    sample = next(iter(latest.values()))
    assert set(sample) == set(ROW_KEYS), f"row schema mismatch: {set(sample)}"
    print(f"PASS: wrote {len(paths)} files ({paths[0].name} .. {paths[-1].name}), {len(latest)} cards each")

    # --- verify a couple of cards show a clear saturation trend ------------
    # Reload the whole series and compute supply_saturation = 7d avg / 30d avg
    # the same way pipeline/market_dynamics does, to prove real signal exists.
    series: Dict[str, List[int]] = {}
    for p in paths:
        rows = json.loads(p.read_text())
        for cid, row in rows.items():
            av = row.get("active_listings")
            if av is not None:
                series.setdefault(cid, []).append(av)

    def saturation(vals: List[int]) -> float:
        short = vals[-7:]
        long = vals[-30:]
        return (sum(short) / len(short)) / (sum(long) / len(long))

    sats = {cid: saturation(v) for cid, v in series.items() if len(v) >= 30}
    tightening = sorted(sats.items(), key=lambda kv: kv[1])[:3]    # lowest = tightening
    loosening = sorted(sats.items(), key=lambda kv: kv[1])[-3:]    # highest = loosening
    n_tight = sum(1 for v in sats.values() if v < 0.92)
    n_loose = sum(1 for v in sats.values() if v > 1.08)

    print(f"saturation computed for {len(sats)} cards")
    print(f"  clear tightening (sat<0.92): {n_tight} cards | clear loosening (sat>1.08): {n_loose} cards")
    print("  most tightening (hot):")
    for cid, s in tightening:
        print(f"    {cid}: saturation={s:.3f}  (7d avg / 30d avg of active listings)")
    print("  most loosening (cooling):")
    for cid, s in reversed(loosening):
        print(f"    {cid}: saturation={s:.3f}")

    assert tightening[0][1] < 0.95, "expected at least one clearly tightening card"
    assert loosening[-1][1] > 1.05, "expected at least one clearly loosening card"

    # Spot-check demand_pressure is being produced on the latest day.
    with_sold = [r for r in latest.values() if r.get("est_sold")]
    print(f"latest day: {len(with_sold)} cards with est_sold>0 (feeds demand_pressure)")
    assert with_sold, "expected some est_sold>0 on the latest day"
    print("PASS: simulation produces clear saturation trends and sold-flow signal")
