"""eBay request errors must read as unknown, never as zero listings.

Codex review, finding 2: a timeout, a 5xx, a non-429 HTTP error or a malformed
body used to become ``active_listings = 0`` with an empty ``item_ids`` list.
Diffed against yesterday, every listing then looked "ended" and 35 to 85% of
them were counted as sold, which is a made-up demand spike.

These tests pin the fixed behavior with no network access:
  * any failed or malformed request gives an unknown row (None, no item_ids);
  * an unknown row is never diffed into ended listings or inferred sales;
  * a valid response with no results still records a real zero;
  * the normal gross and net diffs give exactly the numbers they gave before.

Run: pytest tests/test_ebay_errors.py
"""
import json
import urllib.error
from datetime import date

import pytest

from collectors import ebay


def _card(cid, name):
    return {"id": cid, "name": name, "set_name": "Test Set", "number": "1", "market_price": 50.0}


def _page(ids, price=50.0):
    """A valid Browse search page with one plain listing per id."""
    return {
        "total": len(ids),
        "itemSummaries": [
            {"itemId": i, "title": "Test card", "price": {"value": str(price), "currency": "USD"}}
            for i in ids
        ],
    }


class _Resp:
    """Minimal stand-in for the object urllib.request.urlopen returns."""

    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(ebay, "REQUEST_PAUSE_S", 0)
    monkeypatch.setattr(ebay.time, "sleep", lambda _s: None)


# ---------------------------------------------------------------------------
# _browse_request: every failure mode returns None
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.HTTPError("https://x", 500, "Server Error", None, None),
        urllib.error.HTTPError("https://x", 503, "Unavailable", None, None),
        urllib.error.HTTPError("https://x", 400, "Bad Request", None, None),
        TimeoutError("timed out"),
        urllib.error.URLError("connection refused"),
    ],
    ids=["http500", "http503", "http400", "timeout", "urlerror"],
)
def test_browse_request_returns_none_on_errors(monkeypatch, failure):
    def boom(*_a, **_k):
        raise failure

    monkeypatch.setattr(ebay.urllib.request, "urlopen", boom)
    assert ebay._browse_request("tok", "q", 0) is None


def test_browse_request_returns_none_on_bad_json(monkeypatch):
    monkeypatch.setattr(ebay.urllib.request, "urlopen", lambda *_a, **_k: _Resp(b"<html>oops</html>"))
    assert ebay._browse_request("tok", "q", 0) is None


def test_browse_request_retries_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError("https://x", 429, "Too Many", None, None)
        return _Resp(json.dumps(_page(["a"])).encode())

    monkeypatch.setattr(ebay.urllib.request, "urlopen", flaky)
    assert ebay._browse_request("tok", "q", 0) == _page(["a"])
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# _fetch_card_market: unknown on error or malformed page, real zero on empty
# ---------------------------------------------------------------------------
def test_error_gives_unknown_row(monkeypatch):
    monkeypatch.setattr(ebay, "_browse_request", lambda *_a, **_k: None)
    row = ebay._fetch_card_market(_card("c1", "Pikachu"), "tok")
    assert row["active_listings"] is None
    assert row["avg_price"] is None
    assert "item_ids" not in row


@pytest.mark.parametrize(
    "body",
    [
        {},
        [],
        "not a dict",
        {"errors": [{"errorId": 12001, "message": "System error"}]},
        {"total": 5},                       # results claimed but no itemSummaries
        {"itemSummaries": "oops"},          # wrong type
        {"itemSummaries": [1, 2, 3]},       # items that are not objects
    ],
    ids=["empty-dict", "list", "string", "error-body", "total-without-items", "items-not-list", "items-not-objects"],
)
def test_malformed_page_gives_unknown_row(monkeypatch, body):
    monkeypatch.setattr(ebay, "_browse_request", lambda *_a, **_k: body)
    row = ebay._fetch_card_market(_card("c1", "Pikachu"), "tok")
    assert row["active_listings"] is None
    assert "item_ids" not in row


@pytest.mark.parametrize(
    "body",
    [{"href": "https://x", "total": 0, "limit": 200, "offset": 0}, {"total": 0, "itemSummaries": []}],
    ids=["no-items-key", "empty-items-list"],
)
def test_real_empty_result_is_zero(monkeypatch, body):
    monkeypatch.setattr(ebay, "_browse_request", lambda *_a, **_k: body)
    row = ebay._fetch_card_market(_card("c1", "Pikachu"), "tok")
    assert row["active_listings"] == 0
    assert row["item_ids"] == []


def test_valid_page_is_counted(monkeypatch):
    monkeypatch.setattr(ebay, "_browse_request", lambda *_a, **_k: _page(["b", "a", "c"]))
    row = ebay._fetch_card_market(_card("c1", "Pikachu"), "tok")
    assert row["active_listings"] == 3
    assert row["avg_price"] == 50.0
    assert row["item_ids"] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# diff_row: an unknown day never produces ended listings or sales
# ---------------------------------------------------------------------------
YESTERDAY = {"active_listings": 3, "avg_price": 50.0, "item_ids": ["a", "b", "c"]}


def test_unknown_today_is_not_diffed():
    out = ebay.diff_row(YESTERDAY, ebay._empty_row())
    assert out["active_listings"] is None
    for key in ("new_listings", "ended_listings", "est_sold", "est_unsold"):
        assert out[key] is None, key


def test_day_after_unknown_is_not_diffed():
    """Tomorrow must not read the unknown day as zero and invent new listings."""
    today = {"active_listings": 3, "avg_price": 50.0, "item_ids": ["a", "b", "c"]}
    out = ebay.diff_row(ebay._empty_row(), today)
    assert out["active_listings"] == 3
    assert out["new_listings"] is None and out["ended_listings"] is None
    assert out["item_ids"] == ["a", "b", "c"]  # still carried for the next diff


def test_real_empty_today_still_counts_as_ended():
    """A valid empty response is a real observation, so the normal diff applies."""
    out = ebay.diff_row(YESTERDAY, {"active_listings": 0, "avg_price": None, "item_ids": []})
    assert out["active_listings"] == 0
    assert out["ended_listings"] == 3
    assert out["est_sold"] == 2 and out["est_unsold"] == 1  # neutral 0.6 share, unchanged


def test_normal_gross_diff_unchanged():
    prev = {"active_listings": 4, "avg_price": 50.0, "item_ids": ["a", "b", "c", "d"]}
    curr = {"active_listings": 3, "avg_price": 50.0, "item_ids": ["c", "d", "e"]}
    out = ebay.diff_row(prev, curr)
    assert (out["new_listings"], out["ended_listings"]) == (1, 2)
    assert (out["est_sold"], out["est_unsold"]) == (1, 1)


def test_normal_net_diff_unchanged():
    prev = {"active_listings": 10, "avg_price": 100.0}
    curr = {"active_listings": 7, "avg_price": 90.0}   # 10% cheaper ask -> sold share 0.75
    out = ebay.diff_row(prev, curr)
    assert (out["new_listings"], out["ended_listings"]) == (0, 3)
    assert (out["est_sold"], out["est_unsold"]) == (2, 1)


# ---------------------------------------------------------------------------
# collect_snapshot end to end (no network): error, real empty, and normal cards
# ---------------------------------------------------------------------------
def test_collect_snapshot_error_is_unknown_end_to_end(monkeypatch, tmp_path):
    yday = {
        "c1": {"active_listings": 3, "avg_price": 50.0, "item_ids": ["a", "b", "c"]},
        "c2": {"active_listings": 2, "avg_price": 50.0, "item_ids": ["x", "y"]},
        "c3": {"active_listings": 2, "avg_price": 50.0, "item_ids": ["p", "q"]},
    }
    (tmp_path / "ebay-2026-09-25.json").write_text(json.dumps(yday))

    responses = {
        "Erroring": None,                                  # request failed
        "Empty": {"href": "https://x", "total": 0},        # valid, no listings
        "Normal": _page(["q", "r"]),                       # valid, one ended one new
    }

    def fake_browse(_token, q, offset):
        return next(v for k, v in responses.items() if q.startswith(k))

    monkeypatch.setattr(ebay, "_ebay_credentials", lambda: ("app", "cert"))
    monkeypatch.setattr(ebay, "_get_app_token", lambda *_a: "tok")
    monkeypatch.setattr(ebay, "_browse_request", fake_browse)

    cards = [_card("c1", "Erroring"), _card("c2", "Empty"), _card("c3", "Normal")]
    path = ebay.collect_snapshot(cards, out_dir=tmp_path, snapshot_date=date(2026, 9, 26))
    snap = json.loads(path.read_text())

    c1 = snap["c1"]
    assert c1["active_listings"] is None
    assert c1["ended_listings"] is None and c1["est_sold"] is None and c1["est_unsold"] is None

    c2 = snap["c2"]
    assert c2["active_listings"] == 0 and c2["ended_listings"] == 2

    c3 = snap["c3"]
    assert c3["active_listings"] == 2
    assert (c3["new_listings"], c3["ended_listings"]) == (1, 1)
