"""Leakage guard for the demand feed.

Before ``demand_pressure`` / ``supply_saturation`` can become model features, the
backtest must be able to recompute them AS-OF a historical date T without ever
reading a snapshot from after T. This test pins that invariant: adding a FUTURE
snapshot must not change ``load_history(as_of=T)`` or ``compute(as_of=T)``.

Run: ./.venv/bin/python -m tests.test_demand_asof   (or pytest tests/)
"""
import json
import tempfile
from datetime import date
from pathlib import Path

from pipeline import market_dynamics as md


def _write_snap(d: Path, datestr: str, rows: dict) -> None:
    (d / f"ebay-{datestr}.json").write_text(json.dumps(rows))


def test_asof_blocks_future_snapshots():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        _write_snap(d, "2026-06-01", {"c1": {"active_listings": 100, "avg_price": 10.0}})
        _write_snap(d, "2026-06-02", {"c1": {"active_listings": 80, "avg_price": 10.0}})

        # Compute as-of 2026-06-02 (only the first two days exist).
        h_before = md.load_history(d, as_of=date(2026, 6, 2))
        r_before = md.compute("c1", h_before, as_of=date(2026, 6, 2))

        # A FUTURE snapshot lands. Recomputing AS-OF 2026-06-02 must be identical —
        # the future day cannot leak backward.
        _write_snap(d, "2026-06-03", {"c1": {"active_listings": 5, "avg_price": 99.0}})
        h_after = md.load_history(d, as_of=date(2026, 6, 2))
        r_after = md.compute("c1", h_after, as_of=date(2026, 6, 2))

        assert h_before == h_after, "load_history(as_of=T) leaked a future snapshot"
        assert r_before == r_after, "compute(as_of=T) leaked a future snapshot"

        # Sanity: the gate is actually doing something — ungated load sees all 3 days,
        # and gating to the same as_of via compute on the full history matches.
        h_all = md.load_history(d)  # no gate
        assert len(h_all["c1"]) == 3 and len(h_before["c1"]) == 2
        r_gated_from_full = md.compute("c1", h_all, as_of=date(2026, 6, 2))
        assert r_gated_from_full == r_before, "compute(as_of) on full history must match the gated load"

    print("PASS: demand as-of gate blocks future snapshots (no look-ahead).")


if __name__ == "__main__":
    test_asof_blocks_future_snapshots()
