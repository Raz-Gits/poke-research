"""TCGplayer sealed-product price history -> trend signal for the Watchlists tab.

TCGplayer's "market price" is sales-derived, so its movement over time is a clean
realized-price TREND: is a set cooling or heating, am I buying into a downtrend or
catching a dip. We track a handful of sealed ETBs (``data/sealed_products.json``):

  * ``--backfill`` — weekly history extracted from the LOCAL tcgcsv archives
    (``data/tcgcsv_archive/*.ppmd.7z``) we already keep for the card backtest.
    Run once locally to seed the series (the archives aren't in CI).
  * default (append) — one current point per run from the live tcgcsv prices
    endpoint; run daily by the refresh Action so the trend keeps growing.

Both MERGE into the existing series (idempotent, dedup by date), then recompute
30-/90-day percent change. Output ``docs/data/sealed_trend.json``::

    {"updated": "<date>", "products": {"<productId>": {
        "label", "group", "latest", "trend_30d", "trend_90d",
        "series": [{"date", "market"}, ...]}}}

Clean source only: TCGplayer's own price API via the tcgcsv mirror — aggregate
market price, no listing scraping. ``User-Agent`` header is required (tcgcsv 401s
the default urllib UA).
"""
from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

try:
    from pipeline.config import DATA, SITE_DATA
except Exception:  # pragma: no cover - keep runnable in isolation
    _ROOT = Path(__file__).resolve().parent.parent
    DATA, SITE_DATA = _ROOT / "data", _ROOT / "docs" / "data"

BASE = "https://tcgcsv.com"
CATEGORY = 3  # Pokémon
UA = "poke-research/1.0"
ARCHIVE_DIR = DATA / "tcgcsv_archive"
PRODUCTS_PATH = DATA / "sealed_products.json"
OUT_PATH = SITE_DATA / "sealed_trend.json"


def load_products() -> Dict[str, dict]:
    """{productId(str): {label, group}} from the curated config."""
    raw = json.loads(PRODUCTS_PATH.read_text())
    return raw.get("products", raw)


def _archive_dates() -> List[date]:
    out: List[date] = []
    for p in ARCHIVE_DIR.glob("prices-*.ppmd.7z"):
        try:
            out.append(datetime.strptime(p.name.split("prices-")[1].split(".")[0],
                                         "%Y-%m-%d").date())
        except (IndexError, ValueError):
            pass
    return sorted(out)


def _from_archive(d: date, groups, pids) -> Dict[str, float]:
    """Extract {productId: marketPrice} for date ``d`` from the cached archive."""
    import py7zr  # local import so the module loads without it

    arc = ARCHIVE_DIR / f"prices-{d.isoformat()}.ppmd.7z"
    if not arc.exists():
        return {}
    tmp = ARCHIVE_DIR / f"_sx_{d.isoformat()}"
    try:
        with py7zr.SevenZipFile(arc, "r") as z:
            names = set(z.getnames())
            targets = [f"{d.isoformat()}/{CATEGORY}/{g}/prices" for g in groups
                       if f"{d.isoformat()}/{CATEGORY}/{g}/prices" in names]
            if not targets:
                return {}
            z.extract(path=tmp, targets=targets)
        out: Dict[str, float] = {}
        for g in groups:
            f = tmp / f"{d.isoformat()}/{CATEGORY}/{g}/prices"
            if f.exists():
                for r in json.loads(f.read_text()).get("results", []):
                    pid = str(r.get("productId"))
                    if pid in pids and r.get("marketPrice") is not None:
                        out[pid] = round(float(r["marketPrice"]), 2)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _from_live(groups, pids) -> Dict[str, float]:
    """Extract {productId: marketPrice} from the live tcgcsv prices endpoint."""
    out: Dict[str, float] = {}
    for g in groups:
        url = f"{BASE}/tcgplayer/{CATEGORY}/{g}/prices"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            print(f"  live tcgcsv fetch failed for group {g}: {type(e).__name__}")
            continue
        for rr in data.get("results", []):
            pid = str(rr.get("productId"))
            if pid in pids and rr.get("marketPrice") is not None:
                out[pid] = round(float(rr["marketPrice"]), 2)
    return out


def _load_existing() -> Dict[str, Dict[str, float]]:
    """Existing series as {productId: {date: market}} so runs merge, not clobber."""
    series: Dict[str, Dict[str, float]] = {}
    if not OUT_PATH.exists():
        return series
    try:
        prev = json.loads(OUT_PATH.read_text()).get("products", {})
    except (json.JSONDecodeError, OSError):  # pragma: no cover
        return series
    for pid, p in prev.items():
        pts: Dict[str, float] = {}
        for pt in p.get("series", []):       # parse each point defensively —
            d, m = pt.get("date"), pt.get("market")  # one bad point must not
            if d and m is not None:           # drop every product after it
                pts[d] = m
        series[pid] = pts
    return series


def _trend(series: List[dict], days: int):
    """Percent change (fraction) of latest market vs the last point >= ``days`` ago.

    None when there isn't enough history to span ``days`` (don't fake a trend).
    """
    if len(series) < 2:
        return None
    latest = series[-1]
    latest_market = latest.get("market")
    if latest_market is None:
        return None
    cutoff = datetime.strptime(latest["date"], "%Y-%m-%d").date() - timedelta(days=days)
    past = None
    for pt in series:  # ascending; keep the newest point at/before the cutoff
        if datetime.strptime(pt["date"], "%Y-%m-%d").date() <= cutoff:
            past = pt
        else:
            break
    if not past or not past.get("market"):
        return None
    # Guard sparse history: the anchor must sit near the window edge, else a gap
    # (skipped run, holes in backfill) would let a "30d" trend secretly span
    # months under a confident label. Weekly cadence -> 14d tolerance is ample.
    if (cutoff - datetime.strptime(past["date"], "%Y-%m-%d").date()).days > 14:
        return None
    return round((latest_market - past["market"]) / past["market"], 4)


def _write(products: Dict[str, dict], series: Dict[str, Dict[str, float]]) -> None:
    out = {"updated": date.today().isoformat(), "products": {}}
    for pid, meta in products.items():
        pts = [{"date": d, "market": m} for d, m in sorted(series.get(pid, {}).items())]
        out["products"][pid] = {
            "label": meta["label"], "group": meta["group"],
            "latest": pts[-1]["market"] if pts else None,
            "trend_30d": _trend(pts, 30),
            "trend_90d": _trend(pts, 90),
            "series": pts,
        }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    n_pts = sum(len(p["series"]) for p in out["products"].values())
    print(f"wrote {OUT_PATH.name}: {len(out['products'])} products, {n_pts} total points.")


def backfill() -> None:
    """Seed the series from every local weekly archive (merges with existing)."""
    products = load_products()
    groups = {int(v["group"]) for v in products.values()}
    pids = set(products)
    series = _load_existing()
    series.update({pid: series.get(pid, {}) for pid in products})
    dates = _archive_dates()
    if not dates:
        print(f"no local archives in {ARCHIVE_DIR} — nothing to backfill (series unchanged).")
        _write(products, series)
        return
    print(f"backfilling from {len(dates)} local archives "
          f"({dates[0]} .. {dates[-1]}) for {len(pids)} products...")
    for d in dates:
        for pid, mp in _from_archive(d, groups, pids).items():
            series[pid][d.isoformat()] = mp
    _write(products, series)


def append_today() -> None:
    """Append one current point per product from live tcgcsv, then recompute."""
    products = load_products()
    groups = {int(v["group"]) for v in products.values()}
    pids = set(products)
    series = _load_existing()
    series.update({pid: series.get(pid, {}) for pid in products})
    today = date.today().isoformat()
    for pid, mp in _from_live(groups, pids).items():
        series[pid][today] = mp          # dict keyed by date -> today's point dedups
    _write(products, series)


if __name__ == "__main__":  # pragma: no cover
    import sys
    if "--backfill" in sys.argv:
        backfill()
    else:
        append_today()
