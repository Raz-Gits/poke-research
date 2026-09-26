"""meta.json's eBay source line comes from the snapshots on disk.

Codex review, finding 15: build.py hard-coded the eBay source as "stub
(awaiting Browse API key)" while the daily sweep was writing live snapshots.
It is now derived from the newest snapshot with real listing data, with its date.

Run: pytest tests/test_source_status.py
"""
import json
from datetime import date

from pipeline import build

TODAY = date(2026, 9, 26)
LIVE = {"c1": {"active_listings": 12, "avg_price": 40.0}}
NEUTRAL = {"c1": {"active_listings": None, "avg_price": None}}


def _snap(d, day, rows):
    (d / f"ebay-{day}.json").write_text(json.dumps(rows))


def test_no_snapshots(tmp_path):
    text, latest = build._ebay_source_status(tmp_path, TODAY)
    assert latest is None and "no live eBay snapshot" in text


def test_neutral_snapshots_do_not_count(tmp_path):
    _snap(tmp_path, "2026-09-26", NEUTRAL)
    text, latest = build._ebay_source_status(tmp_path, TODAY)
    assert latest is None and "no live eBay snapshot" in text


def test_recent_live_snapshot(tmp_path):
    _snap(tmp_path, "2026-09-24", LIVE)
    _snap(tmp_path, "2026-09-25", LIVE)
    text, latest = build._ebay_source_status(tmp_path, TODAY)
    assert latest == "2026-09-25"
    assert text == "eBay Browse API active listings (latest snapshot 2026-09-25)"


def test_old_live_snapshot_says_how_old(tmp_path):
    _snap(tmp_path, "2026-09-10", LIVE)
    _snap(tmp_path, "2026-09-26", NEUTRAL)   # today's sweep had no key -> not live
    text, latest = build._ebay_source_status(tmp_path, TODAY)
    assert latest == "2026-09-10"
    assert "16 days old" in text


def test_future_dated_file_is_ignored(tmp_path):
    _snap(tmp_path, "2026-09-25", LIVE)
    _snap(tmp_path, "2026-10-30", LIVE)
    _, latest = build._ebay_source_status(tmp_path, TODAY)
    assert latest == "2026-09-25"
