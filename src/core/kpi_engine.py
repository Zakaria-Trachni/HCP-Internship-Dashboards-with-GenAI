"""Adaptive KPI engine.

`suggest_kpis(profile)` returns a list of generic KPI specs derived
purely from the profile's roles. The KPI agent's LLM call later
prunes/reorders this list using business judgment, but every KPI here
is computable on *any* dataset that has the relevant roles.

`compute_kpis(df, specs)` executes those specs and returns concrete
values.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .profiler import DatasetProfile


# KPI spec shape (dict, JSON-friendly so it crosses the MCP boundary cleanly):
# {
#   "id": "stable_slug",
#   "title": "Human-readable title",
#   "kind": "row_count" | "measure_agg" | "measure_per_dim" | "distinct_count"
#           | "share_of_total" | "trend_delta",
#   "measure": "<col>" (when applicable),
#   "agg": "sum" | "mean" | "median" | "min" | "max" (when applicable),
#   "dimension": "<col>" (when applicable),
#   "datetime": "<col>" (when applicable),
#   "format": "number" | "currency_like" | "percent" | "duration",
#   "description": "..."
# }


def _fmt_for(measure_name: str) -> str:
    """Very light heuristic — only used for display formatting, never
    for the math. If column name contains hints, format accordingly."""
    n = measure_name.lower()
    if any(k in n for k in ("price", "revenue", "sales", "amount", "cost", "profit", "spend", "$")):
        return "currency_like"
    if any(k in n for k in ("rate", "pct", "percent", "%", "ratio")):
        return "percent"
    return "number"


def suggest_kpis(profile: DatasetProfile, *, top_n: int = 15, max_kpis: int = 20) -> list[dict[str, Any]]:
    """Generate a generous shortlist of candidate KPIs. The KPI agent
    later narrows this with business judgment."""
    kpis: list[dict[str, Any]] = []

    # Always include row count.
    kpis.append({
        "id": "total_records",
        "title": "Total records",
        "kind": "row_count",
        "format": "number",
        "description": "Total number of rows in the dataset.",
    })

    # For each measure: sum, mean, max.
    for m in profile.measures:
        fmt = _fmt_for(m)
        kpis.extend([
            {
                "id": f"sum_{_slug(m)}",
                "title": f"Total {m}",
                "kind": "measure_agg",
                "measure": m,
                "agg": "sum",
                "format": fmt,
                "description": f"Sum of {m} across all records.",
            },
            {
                "id": f"avg_{_slug(m)}",
                "title": f"Average {m}",
                "kind": "measure_agg",
                "measure": m,
                "agg": "mean",
                "format": fmt,
                "description": f"Mean of {m} across all records.",
            },
            {
                "id": f"max_{_slug(m)}",
                "title": f"Max {m}",
                "kind": "measure_agg",
                "measure": m,
                "agg": "max",
                "format": fmt,
                "description": f"Largest single {m} value.",
            },
        ])

    # Distinct counts for low-cardinality dimensions (limit a few).
    for d in profile.dimensions[:4]:
        kpis.append({
            "id": f"distinct_{_slug(d)}",
            "title": f"Distinct {d}",
            "kind": "distinct_count",
            "dimension": d,
            "format": "number",
            "description": f"Number of unique values of {d}.",
        })

    # If we have a datetime and a measure, propose a period-over-period
    # delta on the first measure (latest period vs prior period).
    if profile.datetimes and profile.measures:
        dt = profile.datetimes[0]
        m = profile.measures[0]
        kpis.append({
            "id": f"trend_{_slug(m)}_by_{_slug(dt)}",
            "title": f"{m} latest vs prior period",
            "kind": "trend_delta",
            "measure": m,
            "agg": "sum",
            "datetime": dt,
            "format": _fmt_for(m),
            "description": (
                f"Percentage change in total {m} between the most recent "
                f"complete period and the period before it (auto-bucketed)."
            ),
        })

    # If a dimension + measure exists, propose "share of top category".
    if profile.dimensions and profile.measures:
        d = profile.dimensions[0]
        m = profile.measures[0]
        kpis.append({
            "id": f"top_{_slug(d)}_share_{_slug(m)}",
            "title": f"Top {d} share of {m}",
            "kind": "share_of_total",
            "dimension": d,
            "measure": m,
            "agg": "sum",
            "format": "percent",
            "description": (
                f"Share of total {m} contributed by the single largest "
                f"value of {d}."
            ),
        })

    return kpis[:max_kpis]


def compute_kpis(df: pd.DataFrame, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Execute KPI specs against the DataFrame. Each result merges the
    original spec with `value` (raw) and `display` (formatted string)."""
    results: list[dict[str, Any]] = []
    for spec in specs:
        try:
            value, display = _compute_one(df, spec)
        except Exception as e:
            value, display = None, f"n/a ({type(e).__name__})"
        out = dict(spec)
        out["value"] = value
        out["display"] = display
        results.append(out)
    return results


def _compute_one(df: pd.DataFrame, spec: dict[str, Any]) -> tuple[Any, str]:
    kind = spec["kind"]
    fmt = spec.get("format", "number")

    if kind == "row_count":
        v = int(len(df))
        return v, _format(v, "number")

    if kind == "distinct_count":
        col = spec["dimension"]
        v = int(df[col].nunique(dropna=True))
        return v, _format(v, "number")

    if kind == "measure_agg":
        col = spec["measure"]
        agg = spec["agg"]
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            return None, "n/a"
        v = float(getattr(s, agg)())
        return v, _format(v, fmt)

    if kind == "share_of_total":
        d = spec["dimension"]
        m = spec["measure"]
        s = pd.to_numeric(df[m], errors="coerce")
        grouped = s.groupby(df[d]).sum().sort_values(ascending=False)
        if grouped.empty:
            return None, "n/a"
        top_val = float(grouped.iloc[0])
        total = float(grouped.sum())
        if total == 0:
            return None, "n/a"
        share = top_val / total
        top_label = str(grouped.index[0])
        return share, f"{_format(share*100, 'number')}% ({top_label})"

    if kind == "trend_delta":
        dt = spec["datetime"]
        m = spec["measure"]
        s = pd.to_numeric(df[m], errors="coerce")
        d = pd.to_datetime(df[dt], errors="coerce")
        ok = d.notna() & s.notna()
        if ok.sum() < 4:
            return None, "n/a"
        df2 = pd.DataFrame({"d": d[ok], "v": s[ok]}).sort_values("d")
        # Auto-bucket: pick a granularity that gives >= 4 buckets.
        for freq in ("D", "W", "M", "Q", "Y"):
            bucketed = df2.groupby(df2["d"].dt.to_period(freq))["v"].sum()
            if len(bucketed) >= 4:
                break
        else:
            return None, "n/a"
        latest, prior = float(bucketed.iloc[-1]), float(bucketed.iloc[-2])
        if prior == 0:
            return None, "n/a"
        delta = (latest - prior) / prior
        return delta, f"{delta*100:+.1f}%"

    return None, "n/a"


def _format(v: float | int | None, fmt: str) -> str:
    if v is None:
        return "n/a"
    if fmt == "currency_like":
        return f"{v:,.2f}"
    if fmt == "percent":
        return f"{v*100:.1f}%" if abs(v) <= 1 else f"{v:.1f}%"
    if isinstance(v, float):
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        return f"{v:,.2f}"
    return f"{v:,}"


def _slug(s: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in s).strip("_")
