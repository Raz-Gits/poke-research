"""Known gaps the site now discloses, pinned so the caveat and the code move together.

Codex review, finding 6: the Track Record's "surfaced" backtest applies only the
mature mid-price gate, while the live site (build._edge) also hides mature
chase-premium cards. The site and README now say so instead of calling it
"what users actually see".

When backtest._is_surfaced learns the chase-premium gate, this test fails on
purpose: remove the caveat in docs/app.js (viewTrackRecord) and the README,
then update this test.

Run: pytest tests/test_known_gaps.py
"""
from pipeline import backtest, build


def test_backtest_gate_does_not_apply_chase_premium_gate_yet():
    # A mature card (two years old) trading at 5x the model estimate.
    card = {"market_price": 500.0, "expected_price": 100.0, "features": {"months_since_release": 24}}

    has_edge, reason = build._edge(card)
    assert has_edge is False and "chase" in reason       # hidden on the live site

    assert backtest._is_surfaced(24 * 30, 500.0) is True  # still counted by the backtest
