"""Tests for the richer-analytics features: geo detection + choropleth,
anomaly detection, and segment comparison. All LLM-free."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.core import (
    build_chart,
    compare_segments,
    detect_anomalies,
    profile_dataframe,
    suggest_charts,
)
from src.core.profiler import ColumnRole


# ---------------------------------------------------------------------------
# Geo detection + choropleth
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def geo_df() -> pd.DataFrame:
    countries = ["France", "Brazil", "Japan", "Germany", "Nigeria", "Canada"]
    rng = np.random.default_rng(0)
    n = 120
    return pd.DataFrame({
        "country": [countries[i % len(countries)] for i in range(n)],
        "revenue": rng.gamma(2.0, 50.0, n).round(2),
        "segment": (["A", "B"] * (n // 2)),
    })


def test_geo_detection(geo_df):
    p = profile_dataframe(geo_df)
    roles = {c.name: c.role for c in p.columns}
    assert roles["country"] == ColumnRole.GEO
    assert "country" in p.geos
    # Geo columns remain usable as dimensions too.
    assert "country" in p.dimensions


def test_choropleth_spec_and_render(geo_df):
    p = profile_dataframe(geo_df)
    specs = suggest_charts(p)
    maps = [c for c in specs if c["kind"] == "choropleth"]
    assert maps, "expected a choropleth when a geo column + measure exist"
    html = build_chart(geo_df, maps[0])
    assert "chart-error" not in html
    assert "<div" in html


def test_non_geo_categorical_not_flagged():
    # A plain category column must NOT be detected as geo.
    df = pd.DataFrame({
        "category": (["Electronics", "Apparel", "Books"] * 40),
        "sales": list(range(120)),
    })
    p = profile_dataframe(df)
    assert p.geos == []
    roles = {c.name: c.role for c in p.columns}
    assert roles["category"] == ColumnRole.DIMENSION


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------


def test_detect_anomalies_flags_extreme_value():
    # 199 continuous values clustered near 50 + one huge spike. Continuous
    # (high-cardinality) so the profiler treats `amount` as a measure.
    rng = np.random.default_rng(3)
    vals = list(rng.normal(50.0, 5.0, 199)) + [9999.0]
    df = pd.DataFrame({"amount": vals})
    p = profile_dataframe(df)
    assert "amount" in p.measures
    res = detect_anomalies(df, p, z_threshold=3.5)
    assert res, "expected at least one anomaly group"
    amt = next(a for a in res if a["measure"] == "amount")
    assert amt["count"] >= 1
    # The 9999 spike is the most extreme example.
    assert any(abs(ex["value"] - 9999.0) < 1e-6 for ex in amt["examples"])


def test_detect_anomalies_quiet_on_uniform_data():
    df = pd.DataFrame({"x": [5.0] * 100})
    p = profile_dataframe(df)
    # No spread -> MAD 0 and IQR 0 -> nothing flagged, no crash.
    assert detect_anomalies(df, p) == []


# ---------------------------------------------------------------------------
# Segment comparison
# ---------------------------------------------------------------------------


def test_compare_segments_reports_gap():
    # Group "high" averages ~100, group "low" averages ~10.
    rng = np.random.default_rng(1)
    n = 100
    df = pd.DataFrame({
        "grp": (["high"] * n + ["low"] * n),
        "value": np.concatenate([rng.normal(100, 5, n), rng.normal(10, 5, n)]),
    })
    p = profile_dataframe(df)
    res = compare_segments(df, p, min_group_size=20)
    assert res, "expected a segment comparison"
    top = res[0]
    assert top["dimension"] == "grp"
    assert top["top"]["label"] == "high"
    assert top["bottom"]["label"] == "low"
    assert top["rel_gap"] > 1  # ~9x gap


def test_compare_segments_respects_min_group_size():
    df = pd.DataFrame({
        "grp": (["a"] * 5 + ["b"] * 5),  # groups too small
        "value": list(range(10)),
    })
    p = profile_dataframe(df)
    assert compare_segments(df, p, min_group_size=20) == []
