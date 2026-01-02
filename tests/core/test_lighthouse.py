"""Tests for Lighthouse metrics extraction."""

import json

from app.core.lighthouse import _extract_metrics  # type: ignore


def test_extract_metrics_from_fixture():
    with open("tests/fixtures/lighthouse.json") as f:
        data = json.load(f)

    metrics = _extract_metrics(data)

    assert metrics.categories.performance is not None
    assert metrics.vitals.cls is not None
    assert isinstance(metrics.opportunities, list)
