"""Deterministic, dataset-agnostic engine.

The "intelligence" of a generalist BI system can't live entirely in the
LLM — given a 50-column dataset, the model would hallucinate column
names and miss obvious aggregations. Instead, this package produces a
rich, adaptive baseline (profile, KPI specs, chart specs) directly from
the data, and the LLM agents curate, prioritize, and narrate that
baseline.
"""
from .profiler import profile_dataframe, ColumnRole
from .kpi_engine import suggest_kpis, compute_kpis
from .dashboard_builder import suggest_charts, build_chart, build_dashboard_html
from .validation import validate_findings
from .insights import detect_anomalies, compare_segments

__all__ = [
    "profile_dataframe",
    "ColumnRole",
    "suggest_kpis",
    "compute_kpis",
    "suggest_charts",
    "build_chart",
    "build_dashboard_html",
    "validate_findings",
    "detect_anomalies",
    "compare_segments",
]
