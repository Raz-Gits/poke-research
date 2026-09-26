"""What the published fit number actually measures.

Codex review, finding 10: meta.json ``model_r2_log`` was shown as "R²(log)",
but ModelResult.r2_log() returns corr(log actual, log predicted)^2. That is
not the coefficient of determination: a model whose every prediction is double
the real price scores a perfect 1.0. The site and README now call it "squared
log correlation, in-sample". This test pins the difference so the label and
the math cannot drift apart unnoticed.

Run: pytest tests/test_fit_metric.py
"""
import math

from pipeline.model import CardPrediction, ModelResult


def test_r2_log_is_squared_correlation_not_r2():
    market = [1.0, 2.0, 5.0, 10.0, 50.0]
    preds = {
        f"c{i}": CardPrediction(f"c{i}", "k", p, 2 * p, (p - 2 * p) / (2 * p), {})
        for i, p in enumerate(market)  # every prediction is 100% too high
    }
    res = ModelResult(features=[], cluster_models={}, global_model=None, predictions=preds)

    assert abs(res.r2_log() - 1.0) < 1e-12  # perfectly correlated in log space

    actual = [math.log(p) for p in market]
    predicted = [math.log(2 * p) for p in market]
    mean = sum(actual) / len(actual)
    sse = sum((a - b) ** 2 for a, b in zip(actual, predicted))
    sst = sum((a - mean) ** 2 for a in actual)
    assert 1 - sse / sst < 0.8  # the standard R² on the same numbers is much lower
