"""prices_as_of: when prices were really fetched, separate from the build time.

Codex review, finding 1: a failed price pull still produced a build stamped with
the current time, and the site read that as "Prices refreshed Today". fetch.py
now records prices_as_of, which only moves forward when every configured set
came back live with prices, and build.py publishes it next to built_at.

These tests run fetch.main() with the network calls replaced, against a temp
directory, so nothing real is fetched or overwritten.

Run: pytest tests/test_prices_as_of.py
"""
import json

import pytest

from pipeline import build, config, fetch, pricing_tcgdex


def _raw_set(set_id, priced=True):
    price = {"tcgplayer": {"prices": {"holofoil": {"market": 5.0}}, "updatedAt": "2026/09/26"}} if priced else {}
    return [dict({"id": f"{set_id}-1", "name": "Pikachu", "number": "1", "rarity": "Rare",
                  "set": {"id": set_id, "name": set_id, "series": "Test", "releaseDate": "2025/01/01"}},
                 **price)]


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point every path fetch.py writes at a temp dir and use two fake sets."""
    for name in ("RAW", "NORMALIZED", "SNAPSHOTS"):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(config, name, d)
    monkeypatch.setattr(config, "PRICE_FETCH_STATUS", tmp_path / "normalized" / "price_fetch.json")
    monkeypatch.setattr(config, "SETS", {
        "setA": {"name": "Set A", "pack_price": 5.0},
        "setB": {"name": "Set B", "pack_price": 5.0},
    })
    monkeypatch.setattr(pricing_tcgdex, "SET_ID_MAP", {})  # never call TCGdex
    return tmp_path


def _run(monkeypatch, now, behavior):
    """Run fetch.main() at time ``now``; ``behavior[set_id]`` is 'ok', 'fail' or 'unpriced'."""
    def fake_fetch(set_id):
        mode = behavior[set_id]
        if mode == "fail":
            raise TimeoutError("upstream down")
        return _raw_set(set_id, priced=(mode == "ok"))

    monkeypatch.setattr(fetch, "fetch_set_cards", fake_fetch)
    monkeypatch.setattr(fetch, "_utc_now_iso", lambda: now)
    fetch.main()
    return json.loads(config.PRICE_FETCH_STATUS.read_text())


# ---------------------------------------------------------------------------
# The pure rule
# ---------------------------------------------------------------------------
def test_full_success_advances():
    s = fetch.next_price_status({"prices_as_of": "OLD"}, "NOW", ["a", "b"], [])
    assert s["prices_as_of"] == "NOW" and s["last_attempt_ok"] is True


def test_partial_failure_carries_forward():
    s = fetch.next_price_status({"prices_as_of": "OLD"}, "NOW", ["a"], ["b"])
    assert s["prices_as_of"] == "OLD" and s["last_attempt_ok"] is False
    assert s["last_attempt_at"] == "NOW" and s["sets_not_live"] == ["b"]


def test_total_failure_carries_forward():
    s = fetch.next_price_status({"prices_as_of": "OLD"}, "NOW", [], ["a", "b"])
    assert s["prices_as_of"] == "OLD"


def test_no_history_and_failure_is_unknown():
    assert fetch.next_price_status(None, "NOW", [], ["a"])["prices_as_of"] is None
    assert fetch.next_price_status("garbage", "NOW", [], ["a"])["prices_as_of"] is None


# ---------------------------------------------------------------------------
# fetch.main() end to end, no network
# ---------------------------------------------------------------------------
def test_fetch_main_sequence(sandbox, monkeypatch):
    t1, t2, t3, t4, t5 = (f"2026-09-2{i}T14:00:00+00:00" for i in range(1, 6))

    s = _run(monkeypatch, t1, {"setA": "ok", "setB": "ok"})
    assert s["prices_as_of"] == t1

    # One set times out and is carried from cache -> prices_as_of does not move.
    s = _run(monkeypatch, t2, {"setA": "ok", "setB": "fail"})
    assert s["prices_as_of"] == t1 and s["last_attempt_at"] == t2
    assert s["sets_not_live"] == ["setB"]

    # A set that comes back with no prices at all is not a live price either.
    s = _run(monkeypatch, t3, {"setA": "ok", "setB": "unpriced"})
    assert s["prices_as_of"] == t1

    # Total outage: only cached data is used -> carried forward, cache untouched.
    cards_before = (config.NORMALIZED / "cards.json").read_text()
    s = _run(monkeypatch, t4, {"setA": "fail", "setB": "fail"})
    assert s["prices_as_of"] == t1 and s["last_attempt_ok"] is False
    assert (config.NORMALIZED / "cards.json").read_text() == cards_before

    # Everything live again -> advances.
    s = _run(monkeypatch, t5, {"setA": "ok", "setB": "ok"})
    assert s["prices_as_of"] == t5 and s["last_attempt_ok"] is True


def test_first_run_total_failure_publishes_no_date(sandbox, monkeypatch):
    """No cache and nothing fetched: no prices_as_of is claimed at all."""
    s = _run(monkeypatch, "2026-09-26T14:00:00+00:00", {"setA": "fail", "setB": "fail"})
    assert s["prices_as_of"] is None and s["last_attempt_ok"] is False
    assert not (config.NORMALIZED / "cards.json").exists()


# ---------------------------------------------------------------------------
# build side: reads the record, tolerates it missing or broken
# ---------------------------------------------------------------------------
def test_build_reads_price_status(tmp_path, monkeypatch):
    p = tmp_path / "price_fetch.json"
    monkeypatch.setattr(config, "PRICE_FETCH_STATUS", p)
    assert build._load_price_status() == {}                    # missing
    p.write_text("{not json")
    assert build._load_price_status() == {}                    # broken
    p.write_text(json.dumps(["not", "a", "dict"]))
    assert build._load_price_status() == {}                    # wrong shape
    p.write_text(json.dumps({"prices_as_of": "2026-09-26T14:00:00+00:00"}))
    assert build._load_price_status()["prices_as_of"] == "2026-09-26T14:00:00+00:00"
