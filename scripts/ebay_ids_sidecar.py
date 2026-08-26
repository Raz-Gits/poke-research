#!/usr/bin/env python3
"""Keep eBay item IDs out of git without losing the exact day-over-day diff.

The daily snapshot stores, per card, aggregate counts plus the raw list of eBay
item IDs behind them. The aggregates are derived analytics and belong in the
repo. The ID lists are eBay listing data, they are 70% of the bytes, and this
repository is public, so they must not be committed.

Only one thing needs them: ``collectors.ebay.diff_snapshots`` compares
yesterday's IDs with today's to count new and ended listings exactly. That is a
single day of lookback, so the IDs can live in an Actions cache instead of in
git.

Two modes, both run from the daily workflow:

    restore   before the build. Reads .ebay_ids_cache/latest.json and injects
              those IDs back into the most recent committed snapshot on disk,
              so today's diff sees a complete "yesterday".

    stash     after the build, before `git add`. Pulls today's IDs out of every
              snapshot file into .ebay_ids_cache/latest.json and rewrites the
              files without them.

Both modes are no-ops when there is nothing to do, and neither raises on a
missing file: the workflow guards them with continue-on-error, and the worst
case is that collectors/ebay.py falls back to its existing NET math for one
day, which it is already written to do.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = ROOT / "data" / "snapshots"
CACHE = ROOT / ".ebay_ids_cache"
CACHE_FILE = CACHE / "latest.json"


def _snapshot_files() -> list[Path]:
    return sorted(SNAPSHOTS.glob("ebay-*.json"))


def restore() -> int:
    if not CACHE_FILE.is_file():
        print("restore: no cached IDs, today's diff will use the NET fallback")
        return 0
    files = _snapshot_files()
    if not files:
        print("restore: no snapshots on disk")
        return 0

    cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    ids_by_card = cached.get("item_ids", {})
    target_name = cached.get("snapshot")

    target = SNAPSHOTS / target_name if target_name else files[-1]
    if not target.is_file():
        print(f"restore: cached snapshot {target_name} is gone , skipping")
        return 0

    rows = json.loads(target.read_text(encoding="utf-8"))
    restored = 0
    for card_id, ids in ids_by_card.items():
        row = rows.get(card_id)
        if isinstance(row, dict):
            row["item_ids"] = ids
            restored += 1

    target.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"restore: injected IDs into {restored} rows of {target.name}")
    return 0


def stash() -> int:
    files = _snapshot_files()
    if not files:
        print("stash: no snapshots on disk")
        return 0

    newest = files[-1]
    rows = json.loads(newest.read_text(encoding="utf-8"))
    ids_by_card = {
        card_id: row["item_ids"]
        for card_id, row in rows.items()
        if isinstance(row, dict) and row.get("item_ids")
    }

    CACHE.mkdir(exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps({"snapshot": newest.name, "item_ids": ids_by_card}),
        encoding="utf-8",
    )

    stripped_rows = 0
    stripped_files = 0
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        touched = 0
        for row in data.values():
            if isinstance(row, dict) and "item_ids" in row:
                del row["item_ids"]
                touched += 1
        if touched:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            stripped_rows += touched
            stripped_files += 1

    print(
        f"stash: cached IDs for {len(ids_by_card)} cards from {newest.name}; "
        f"stripped {stripped_rows} rows across {stripped_files} files"
    )
    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "restore":
        raise SystemExit(restore())
    if mode == "stash":
        raise SystemExit(stash())
    print(__doc__)
    raise SystemExit(2)
