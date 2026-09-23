"""Deterministic analytical insights: anomalies and segment comparison.

Mirrors the style of `kpi_engine.py` — pure functions that take a
DataFrame + the dataset profile and return JSON-friendly result dicts.
The LLM later narrates these; it never computes them.

- `detect_anomalies` flags abnormal numeric values using a robust,
  MAD-based modified z-score (resistant to the very outliers we're
  hunting), with an IQR fallback. It also flags spike *periods* when a
  datetime + measure exist.
- `compare_segments` compares a measure across the groups of a
  low-cardinality dimension and surfaces the largest gaps.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .profiler import DatasetProfile


# ---------------------------------------------------------------------------
# Anomalies
# ---------------------------------------------------------------------------


def _modified_z(values: np.ndarray) -> np.ndarray | None:
    """Robust modified z-score using the median absolute deviation.

    z = 0.6745 * (x - median) / MAD. Returns None when MAD is 0 (no
    spread) so the caller can fall back to IQR.
    """
    median = np.median(values)
    mad = np.median(np.abs(values - median))
    if mad == 0:
        return None
    return 0.6745 * (values - median) / mad


def detect_anomalies(
    df: pd.DataFrame,
    profile: DatasetProfile,
    *,
    z_threshold: float = 3.5,
    max_measures: int = 4,
    max_examples: int = 5,
) -> list[dict[str, Any]]:
    """Flag outlier values per measure (and spike periods over time)."""
    results: list[dict[str, Any]] = []

    for m in profile.measures[:max_measures]:
        s = pd.to_numeric(df[m], errors="coerce").dropna()
        if len(s) < 12:
            continue
        values = s.to_numpy(dtype=float)
        z = _modified_z(values)
        method = "modified_z"
        if z is None:
            # No spread for MAD — fall back to IQR fences.
            q1, q3 = np.percentile(values, [25, 75])
            iqr = q3 - q1
            if iqr == 0:
                continue
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            mask = (values < lo) | (values > hi)
            method = "iqr"
            scores = np.where(values > hi, (values - hi) / iqr,
                              np.where(values < lo, (lo - values) / iqr, 0.0))
        else:
            mask = np.abs(z) >= z_threshold
            scores = z

        idx = np.where(mask)[0]
        if idx.size == 0:
            continue
        # Strongest outliers first.
        order = idx[np.argsort(-np.abs(scores[idx]))][:max_examples]
        examples = []
        s_index = s.index.to_numpy()
        for i in order:
            examples.append({
                "value": round(float(values[i]), 4),
                "score": round(float(scores[i]), 2),
                "row_label": _row_label(df, int(s_index[i]), profile),
            })
        results.append({
            "measure": m,
            "kind": "value_outlier",
            "method": method,
            "count": int(idx.size),
            "threshold": z_threshold if method == "modified_z" else 1.5,
            "examples": examples,
        })

    # Time spikes: total measure per period that deviates strongly.
    if profile.datetimes and profile.measures:
        dt = profile.datetimes[0]
        m = profile.measures[0]
        d = pd.to_datetime(df[dt], errors="coerce")
        v = pd.to_numeric(df[m], errors="coerce")
        ok = d.notna() & v.notna()
        if ok.sum() >= 24:
            bucket = pd.DataFrame({"d": d[ok], "v": v[ok]})
            for freq in ("YE", "QE", "ME"):
                try:
                    periods = bucket.set_index("d")["v"].resample(freq).sum()
                except Exception:
                    continue
                if len(periods) >= 6:
                    break
            else:
                periods = None
            if periods is not None and len(periods) >= 6:
                pv = periods.to_numpy(dtype=float)
                z = _modified_z(pv)
                if z is not None:
                    sp = np.where(np.abs(z) >= z_threshold)[0]
                    if sp.size:
                        order = sp[np.argsort(-np.abs(z[sp]))][:max_examples]
                        examples = [{
                            "period": str(periods.index[i].date()) if hasattr(periods.index[i], "date") else str(periods.index[i]),
                            "value": round(float(pv[i]), 2),
                            "score": round(float(z[i]), 2),
                        } for i in order]
                        results.append({
                            "measure": m,
                            "kind": "time_spike",
                            "method": "modified_z",
                            "count": int(sp.size),
                            "threshold": z_threshold,
                            "examples": examples,
                        })

    return results


def _row_label(df: pd.DataFrame, idx: int, profile: DatasetProfile) -> str:
    """Build a short human label for an outlier row from its dimensions /
    geo / datetime, so the report can say *which* record was abnormal."""
    parts: list[str] = []
    label_cols = (profile.geos[:2] or profile.dimensions[:2]) + profile.datetimes[:1]
    for c in label_cols[:3]:
        try:
            val = df.at[idx, c]
        except Exception:
            continue
        if pd.isna(val):
            continue
        parts.append(str(val)[:30])
    return " · ".join(parts) if parts else f"row {idx}"


# ---------------------------------------------------------------------------
# Segment comparison
# ---------------------------------------------------------------------------


def compare_segments(
    df: pd.DataFrame,
    profile: DatasetProfile,
    *,
    min_group_size: int = 20,
    max_dim_cardinality: int = 30,
    max_measures: int = 3,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Compare each measure across the groups of low-cardinality
    dimensions; return the comparisons with the largest top-vs-bottom gap."""
    out: list[dict[str, Any]] = []

    # Candidate dimensions: low-cardinality categoricals (skip geo/high-card
    # so we compare meaningful segments, not 200 national teams).
    geo_set = set(profile.geos)
    candidate_dims = []
    for c in profile.columns:
        if c.name in geo_set:
            continue
        if c.role.value in ("dimension", "boolean") and 2 <= c.cardinality <= max_dim_cardinality:
            candidate_dims.append(c.name)

    for dim in candidate_dims:
        for m in profile.measures[:max_measures]:
            s = pd.to_numeric(df[m], errors="coerce")
            grp = s.groupby(df[dim].astype(str))
            stats = grp.agg(["mean", "count"]).dropna()
            stats = stats[stats["count"] >= min_group_size]
            if len(stats) < 2:
                continue
            stats = stats.sort_values("mean", ascending=False)
            top_label, top = stats.index[0], stats.iloc[0]
            bot_label, bot = stats.index[-1], stats.iloc[-1]
            top_mean, bot_mean = float(top["mean"]), float(bot["mean"])
            if top_mean == bot_mean:
                continue
            denom = abs(bot_mean) if bot_mean != 0 else (abs(top_mean) or 1.0)
            rel_gap = abs(top_mean - bot_mean) / denom
            out.append({
                "dimension": dim,
                "measure": m,
                "metric": "mean",
                "top": {"label": str(top_label), "mean": round(top_mean, 4), "count": int(top["count"])},
                "bottom": {"label": str(bot_label), "mean": round(bot_mean, 4), "count": int(bot["count"])},
                "ratio": round(top_mean / bot_mean, 3) if bot_mean else None,
                "rel_gap": round(rel_gap, 4),
                "group_count": int(len(stats)),
            })

    out.sort(key=lambda x: x["rel_gap"], reverse=True)
    return out[:max_results]
