"""Honesty guards for the plain-language market-signal labels.

These pin the rules a reader relies on:
  * with no eBay feed for a card we NEVER invent a flow story -> 'price_only' (or
    'none'), never a demand/supply claim;
  * a LOW demand level alone never produces a "cooling" verdict (low sell-through
    is the noisy default, not a measured cooldown);
  * the canonical money label (price dip + firm demand = opportunity) fires;
  * price move / labels are AS-OF safe (a future snapshot can't change a past label).

Run: ./.venv/bin/python -m tests.test_signal_labels   (or pytest tests/)
"""
import json
import tempfile
from datetime import date
from pathlib import Path

from pipeline import signal_labels as sl


def _ok(dp, sat=1.0):
    return {"status": "ok", "demand_pressure": dp, "supply_saturation": sat}


def test_no_feed_is_price_only_never_a_flow_claim():
    s = sl.compute_signal({"pct": 6.0, "days": 7}, {"status": "awaiting_data"})
    assert s["confidence"] == "price_only"
    assert s["basis"]["market_state"] == "unknown"
    # No demand/supply numbers leaked into the detail line.
    assert "sell-through" not in s["detail"] and "supply" not in s["detail"]


def test_low_demand_alone_is_not_cooling():
    # Price flat, sell-through low, supply flat -> "quiet", NOT "cooling".
    s = sl.compute_signal({"pct": 0.4, "days": 7}, _ok(1.0, 1.0))
    assert s["tone"] == "neutral"
    assert "cool" not in s["label"].lower()
    # Falling price + low demand is "Easing"/"Falling", still not a demand-cooling claim.
    s2 = sl.compute_signal({"pct": -6.0, "days": 7}, _ok(1.0, 1.0))
    assert s2["basis"]["market_state"] == "steady"


def test_opportunity_label_fires():
    s = sl.compute_signal({"pct": -6.0, "days": 7}, _ok(30.0))
    assert s["tone"] == "opportunity"
    assert "Opportunity" in s["label"]


def test_cooling_requires_real_supply_build():
    # Real supply loosening (sat > LOOSEN) + falling price -> cooling.
    s = sl.compute_signal({"pct": -5.0, "days": 9}, _ok(2.0, 1.10))
    assert s["tone"] == "cold"
    assert s["basis"]["market_state"] == "loosening"


def test_nothing_is_awaiting_data():
    s = sl.compute_signal(None, {"status": "awaiting_data"})
    assert s["confidence"] == "none" and s["label"] == "Awaiting data"


def test_price_move_is_asof_safe():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "snapshot-2026-06-10.json").write_text(json.dumps({"c1": 100.0}))
        (d / "snapshot-2026-06-12.json").write_text(json.dumps({"c1": 110.0}))
        h_before = sl.load_price_history(d, as_of=date(2026, 6, 12))
        pm_before = sl.price_move(h_before.get("c1"), as_of=date(2026, 6, 12))
        # A future snapshot lands; recomputing AS-OF 2026-06-12 must be identical.
        (d / "snapshot-2026-06-15.json").write_text(json.dumps({"c1": 50.0}))
        h_after = sl.load_price_history(d, as_of=date(2026, 6, 12))
        pm_after = sl.price_move(h_after.get("c1"), as_of=date(2026, 6, 12))
        assert pm_before == pm_after, "price_move leaked a future snapshot"
        assert pm_before["pct"] == 10.0


if __name__ == "__main__":
    for fn in (
        test_no_feed_is_price_only_never_a_flow_claim,
        test_low_demand_alone_is_not_cooling,
        test_opportunity_label_fires,
        test_cooling_requires_real_supply_build,
        test_nothing_is_awaiting_data,
        test_price_move_is_asof_safe,
    ):
        fn()
        print(f"PASS: {fn.__name__}")
    print("All signal-label honesty guards passed.")
