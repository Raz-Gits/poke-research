"""No live eBay signal without a current valid observation.

Codex verification, follow-up 2: when today's active_listings was unknown,
market_dynamics.compute() still returned status "ok" from older rows, the
signal label then claimed full confidence, and the card could be ranked as a
Mover. Now a card needs a valid row for the current date; otherwise it is
"awaiting_data" with basis.reason = "no_current_observation".

Also pins that stored all-null rows (as written for unknown days, and by the
2026-09-14 data correction) are skipped by the loader and never produce flow.

Run: pytest tests/test_dynamics_current.py
"""
import json
from datetime import date

from pipeline import build, market_dynamics as md, signal_labels as sl

NULL_ROW = {k: None for k in ("active_listings", "new_listings", "ended_listings",
                              "est_sold", "est_unsold", "avg_price")}


def _hist(rows_by_date):
    """{date: row} for card c1 -> history in load_history's shape (with flow backfilled)."""
    raw = {"c1": [dict(r, date=d) for d, r in sorted(rows_by_date.items())]}
    return md._backfill_inline(raw)


# A loosening series: saturation clearly above 1 when every day is valid.
DAYS = {f"2026-09-{d:02d}": {"active_listings": 100 + 5 * i, "avg_price": 10.0}
        for i, d in enumerate(range(1, 13))}


def test_valid_latest_is_live():
    r = md.compute("c1", _hist(DAYS), current_date=date(2026, 9, 12))
    assert r["status"] == "ok" and r["supply_saturation"] > 1.03


def test_unknown_latest_is_awaiting_data():
    days = dict(DAYS)
    days["2026-09-13"] = dict(NULL_ROW)            # today's request failed
    r = md.compute("c1", _hist(days), current_date=date(2026, 9, 13))
    assert r["status"] == "awaiting_data"
    assert r["demand_pressure"] is None and r["supply_saturation"] == 1.0
    assert r["active_listings"] is None
    assert r["basis"]["reason"] == "no_current_observation"
    assert r["basis"]["last_observed"] == "2026-09-12"


def test_unknown_latest_is_awaiting_even_without_current_date():
    days = dict(DAYS)
    days["2026-09-13"] = dict(NULL_ROW)
    assert md.compute("c1", _hist(days))["status"] == "awaiting_data"


def test_card_missing_from_todays_sweep_is_awaiting_data():
    r = md.compute("c1", _hist(DAYS), current_date=date(2026, 9, 13))  # no row for the 13th
    assert r["status"] == "awaiting_data"
    assert r["basis"]["last_observed"] == "2026-09-12"


def test_one_row_stale_card_gets_the_reason_and_no_stale_count():
    """Codex verification 2, follow-up 2: the gate runs before the short-history fallback."""
    hist = _hist({"2026-09-10": {"active_listings": 42, "avg_price": 10.0}})
    r = md.compute("c1", hist, current_date=date(2026, 9, 13))
    assert r["status"] == "awaiting_data"
    assert r["active_listings"] is None                 # not the stale 42
    assert r["basis"]["reason"] == "no_current_observation"
    assert r["basis"]["last_observed"] == "2026-09-10"


def test_one_row_current_card_keeps_its_count():
    hist = _hist({"2026-09-13": {"active_listings": 42, "avg_price": 10.0}})
    r = md.compute("c1", hist, current_date=date(2026, 9, 13))
    assert r["status"] == "awaiting_data" and r["active_listings"] == 42  # too short for flow, but current
    assert "reason" not in r["basis"]


def test_future_dated_row_is_not_current():
    """Only a row dated exactly current_date counts; a later row is ignored."""
    days = dict(DAYS)                                    # valid rows up to 2026-09-12
    days["2026-09-20"] = {"active_listings": 999, "avg_price": 10.0}
    r = md.compute("c1", _hist(days), current_date=date(2026, 9, 13))
    assert r["status"] == "awaiting_data"
    assert r["basis"]["last_observed"] == "2026-09-12"   # the future row was not used
    r_today = md.compute("c1", _hist(days), current_date=date(2026, 9, 12))
    assert r_today["status"] == "ok" and r_today["active_listings"] == 100 + 5 * 11


def test_no_history_keeps_the_plain_fallback():
    r = md.compute("c1", {}, current_date=date(2026, 9, 13))
    assert r["status"] == "awaiting_data" and "reason" not in r["basis"]


def test_awaiting_card_never_gets_full_confidence():
    days = dict(DAYS)
    days["2026-09-13"] = dict(NULL_ROW)
    dyn = md.compute("c1", _hist(days), current_date=date(2026, 9, 13))
    sig = sl.compute_signal({"pct": 5.0, "days": 7}, dyn)
    assert sig["confidence"] == "price_only"
    assert sig["basis"]["market_state"] == "unknown"


def test_stored_null_rows_are_skipped_and_make_no_flow(tmp_path):
    """The shape of the 2026-09-14 correction: a null day, then a day with null flow."""
    files = {
        "2026-09-13": {"c1": {"active_listings": 170, "avg_price": 8.0}},
        "2026-09-14": {"c1": dict(NULL_ROW)},
        "2026-09-15": {"c1": {"active_listings": 169, "avg_price": 8.1,
                              "new_listings": None, "ended_listings": None,
                              "est_sold": None, "est_unsold": None}},
    }
    for d, rows in files.items():
        (tmp_path / f"ebay-{d}.json").write_text(json.dumps(rows))
    rows = md.load_history(tmp_path)["c1"]
    by_date = {r["date"]: r for r in rows}
    assert by_date["2026-09-14"]["active_listings"] is None
    for key in ("ended_listings", "est_sold", "new_listings"):
        assert by_date["2026-09-14"][key] is None      # no sales invented on the null day
        assert by_date["2026-09-15"][key] is None      # and no diff against it the day after
    # The supply means use only the two valid days; a stored null is not a zero.
    assert md._window_active_mean(rows, 30) == (170 + 169) / 2
    r = md.compute("c1", {"c1": rows}, current_date=date(2026, 9, 15))
    assert r["active_listings"] == 169 and r["sold_7d"] is None


def _record(cid, dyn):
    return {"id": cid, "name": cid, "set_name": "S", "set_id": "s", "rarity": "Rare",
            "market_price": 10.0, "expected_price": 12.0, "residual_pct": -0.17,
            "edge": True, "dynamics": dyn}


def test_movers_rank_only_current_observations():
    live = {"status": "ok", "supply_saturation": 1.10, "demand_pressure": 5.0}
    live_small = {"status": "ok", "supply_saturation": 0.98, "demand_pressure": 1.0}
    stale_big = {"status": "awaiting_data", "supply_saturation": 1.60, "demand_pressure": None}
    board = build.build_leaderboard([_record("a", live), _record("b", stale_big), _record("c", live_small)])
    assert board["movers_basis"] == "saturation_shift"
    assert [m["id"] for m in board["movers"]] == ["a", "c"]


def test_build_dynamics_passes_current_date():
    days = {d: {"c1": r} for d, r in DAYS.items()}
    hist = _hist({d: r["c1"] for d, r in days.items()})
    cards = [{"id": "c1"}]
    assert build.build_dynamics(cards, hist, current_date=date(2026, 9, 12))["c1"]["status"] == "ok"
    assert build.build_dynamics(cards, hist, current_date=date(2026, 9, 13))["c1"]["status"] == "awaiting_data"
