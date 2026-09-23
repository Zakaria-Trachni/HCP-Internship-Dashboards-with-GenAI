"""Smoke tests for the LLM-free parts of the system.

These exercise the entire deterministic pipeline (profile -> KPI ->
chart -> dashboard HTML) without requiring an LLM provider, so CI and
contributors can validate the core engine in seconds.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.core import (
    build_chart,
    build_dashboard_html,
    compute_kpis,
    profile_dataframe,
    suggest_charts,
    suggest_kpis,
)
from src.core.profiler import ColumnRole
from src.mcp_server import BIMCPServer


@pytest.fixture(scope="module")
def sample_df() -> pd.DataFrame:
    # Build a tiny dataset that hits every column role.
    return pd.DataFrame({
        "order_date": pd.date_range("2024-01-01", periods=120, freq="D"),
        "region": (["North", "South", "East", "West"] * 30),
        "product_id": [f"SKU-{i % 50}" for i in range(120)],
        "quantity": list(range(1, 121)),
        "revenue": [10.5 * i for i in range(1, 121)],
        "is_returning": [i % 2 == 0 for i in range(120)],
        "notes": ["" for _ in range(120)],
    })


def test_profile_roles(sample_df: pd.DataFrame) -> None:
    p = profile_dataframe(sample_df)
    roles = {c.name: c.role for c in p.columns}
    assert roles["order_date"] == ColumnRole.DATETIME
    assert roles["region"] == ColumnRole.DIMENSION
    assert roles["product_id"] == ColumnRole.IDENTIFIER
    assert roles["quantity"] == ColumnRole.MEASURE
    assert roles["revenue"] == ColumnRole.MEASURE
    assert roles["is_returning"] == ColumnRole.BOOLEAN


def test_suggest_and_compute_kpis(sample_df: pd.DataFrame) -> None:
    p = profile_dataframe(sample_df)
    specs = suggest_kpis(p)
    assert len(specs) >= 5
    # Every spec must declare an id and a kind.
    for s in specs:
        assert "id" in s and "kind" in s
    computed = compute_kpis(sample_df, specs)
    # Total records is always computable.
    total_records = next(c for c in computed if c["id"] == "total_records")
    assert total_records["value"] == 120


def test_suggest_and_build_charts(sample_df: pd.DataFrame) -> None:
    p = profile_dataframe(sample_df)
    charts = suggest_charts(p)
    assert charts, "expected at least one chart suggestion"
    # Build the first three and confirm we get an HTML <div> back.
    for spec in charts[:3]:
        html = build_chart(sample_df, spec)
        assert "<div" in html or "chart-error" in html


def test_dashboard_html_assembles(sample_df: pd.DataFrame) -> None:
    p = profile_dataframe(sample_df)
    kpis = compute_kpis(sample_df, suggest_kpis(p)[:5])
    chart_specs = suggest_charts(p)[:3]
    charts_html = [
        {**spec, "html": build_chart(sample_df, spec)} for spec in chart_specs
    ]
    html = build_dashboard_html(
        title="Test",
        subtitle="smoke",
        kpis=kpis,
        charts_html=charts_html,
    )
    assert "<html" in html
    assert "kpi-grid" in html
    assert "plotly" in html.lower()


def test_mcp_server_permissions(tmp_path: Path) -> None:
    """Roles must only be able to call their declared tools."""
    cfg = Path(__file__).resolve().parent.parent / "config.yaml"
    server = BIMCPServer(cfg)
    store = server.new_run(artifact_root=tmp_path)

    # Ingestion can load.
    res = server.call_tool(
        store, "ingestion", "load_dataset",
        {"path": _write_tiny_csv(tmp_path)},
    )
    assert res["row_count"] > 0

    # KPI agent is NOT allowed to call clean_dataset.
    from src.mcp_server.tools import PermissionDenied
    with pytest.raises(PermissionDenied):
        server.call_tool(store, "kpi", "clean_dataset", {"operations": []})


def _write_tiny_csv(tmp_path: Path) -> str:
    p = tmp_path / "tiny.csv"
    p.write_text("a,b\n1,x\n2,y\n3,z\n4,x\n5,y\n", encoding="utf-8")
    return str(p)
