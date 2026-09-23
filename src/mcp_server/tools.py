"""Tool registry and implementations exposed by the MCP server.

Each tool is a plain Python callable with:

- a JSON-schema for its arguments (so we can pass it straight to the
  LLM `tools=` parameter),
- a short description used by both the LLM and the MCP protocol,
- a category (the agent role(s) typically allowed to call it).

Tools never read or mutate global state directly — they receive the
`RunStore` as their first argument, which is what the MCP server
threads through.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd


# ---------------------------------------------------------------------------
# Filename → human-readable title.
#
# The uploaded filename is rarely a good display title. We strip the
# extension, replace separators with spaces, split camelCase /
# PascalCase boundaries, and title-case the result.
#
#   AnalystAssistantHiringProcess_Assessment_V01.csv
#     -> "Analyst Assistant Hiring Process Assessment V01"
#   sales-2024_q4.xlsx                  -> "Sales 2024 Q4"
#   patients.csv                        -> "Patients"
# ---------------------------------------------------------------------------

_KNOWN_EXTS = (".csv", ".xlsx", ".xls", ".json", ".tsv", ".txt", ".parquet")

# Known acronyms / brand-cased terms that need explicit fixups. The keys
# are lowercase; the values are how they should render in titles. This
# is intentionally small — only common BI / data-domain terms.
_ACRONYM_FIXUPS: dict[str, str] = {
    "kpi": "KPI", "kpis": "KPIs", "iot": "IoT", "api": "API", "apis": "APIs",
    "url": "URL", "uri": "URI", "sku": "SKU", "skus": "SKUs", "uuid": "UUID",
    "guid": "GUID", "bi": "BI", "roi": "ROI", "ci": "CI", "cd": "CD",
    "ui": "UI", "ux": "UX", "csv": "CSV", "json": "JSON", "xml": "XML",
    "html": "HTML", "css": "CSS", "sql": "SQL", "etl": "ETL", "elt": "ELT",
    "ml": "ML", "ai": "AI", "nlp": "NLP", "llm": "LLM", "llms": "LLMs",
    "http": "HTTP", "https": "HTTPS", "tcp": "TCP", "udp": "UDP",
    "tls": "TLS", "ssl": "SSL", "gpu": "GPU", "cpu": "CPU", "ram": "RAM",
    "ssd": "SSD", "vpn": "VPN", "saas": "SaaS", "paas": "PaaS", "iaas": "IaaS",
    "crm": "CRM", "erp": "ERP", "id": "ID", "ids": "IDs", "qa": "QA",
    "po": "PO", "us": "US", "uk": "UK", "eu": "EU", "rfp": "RFP", "rfq": "RFQ",
}


def humanize_filename(name: str) -> str:
    """Convert a filename into a clean display title."""
    if not name:
        return ""
    stem = name
    # Strip the (last) known extension.
    for suffix in _KNOWN_EXTS:
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    # Replace common separators with spaces.
    stem = stem.replace("_", " ").replace("-", " ").replace(".", " ")
    # Conservative camelCase split:
    #   "HiringProcess" -> "Hiring Process"  (2+ lowercase before cap)
    #   "URLPath"       -> "URL Path"        (caps followed by cap+lower run)
    #   "2024Q1"        -> "2024 Q1"         (digit before cap)
    # But intentionally NOT "IoT" -> "Io T" (only one lowercase between caps).
    stem = re.sub(r"([a-z]{2,})([A-Z])", r"\1 \2", stem)
    stem = re.sub(r"([A-Z]+)([A-Z][a-z]{2,})", r"\1 \2", stem)
    stem = re.sub(r"([0-9])([A-Z])", r"\1 \2", stem)
    stem = re.sub(r"\s+", " ", stem).strip()

    parts: list[str] = []
    for tok in stem.split(" "):
        if not tok:
            continue
        low = tok.lower()
        if low in _ACRONYM_FIXUPS:
            parts.append(_ACRONYM_FIXUPS[low])
        elif tok.isupper():
            parts.append(tok)  # GDP, ABC -> as-is
        elif len(tok) <= 4 and any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok):
            parts.append(tok.upper())  # v01 -> V01, q4 -> Q4, p10 -> P10
        else:
            parts.append(tok[0].upper() + tok[1:])
    return " ".join(parts)

from ..core import (
    build_dashboard_html,
    build_chart,
    compute_kpis,
    compare_segments,
    detect_anomalies,
    profile_dataframe,
    suggest_charts,
    suggest_kpis,
    validate_findings,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ToolError(Exception):
    """Raised when a tool call fails for a known reason. The agent loop
    surfaces the message back to the LLM so it can adjust."""


class PermissionDenied(ToolError):
    pass


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema
    handler: Callable[..., Any]

    def to_openai_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Holds all tools and enforces per-agent permissions."""

    def __init__(self, permissions: dict[str, list[str]]):
        self._tools: dict[str, Tool] = {}
        # role -> set of tool names
        self._permissions: dict[str, set[str]] = {
            role: set(names) for role, names in permissions.items()
        }

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def list_for(self, role: str) -> list[Tool]:
        allowed = self._permissions.get(role, set())
        return [t for n, t in self._tools.items() if n in allowed]

    def openai_specs_for(self, role: str) -> list[dict[str, Any]]:
        return [t.to_openai_spec() for t in self.list_for(role)]

    def call(self, role: str, name: str, arguments: dict[str, Any], store: "RunStore") -> Any:
        if name not in self._tools:
            raise ToolError(f"Unknown tool: {name!r}")
        if name not in self._permissions.get(role, set()):
            raise PermissionDenied(
                f"Agent role {role!r} is not permitted to call tool {name!r}. "
                f"Allowed for this role: {sorted(self._permissions.get(role, set()))}"
            )
        return self._tools[name].handler(store, **arguments)


# ---------------------------------------------------------------------------
# RunStore — opaque to tools other than as a kwarg
# ---------------------------------------------------------------------------
# Imported lazily to avoid circular imports.

from .server import RunStore  # noqa: E402


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
# All handlers take `store: RunStore` as their first argument. Their JSON
# schemas omit that argument — the MCP server injects it.


# --- ingestion -------------------------------------------------------------


def _t_load_dataset(store: RunStore, path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise ToolError(f"File not found: {path}")
    suffix = p.suffix.lower()
    try:
        if suffix == ".csv":
            df = pd.read_csv(p)
        elif suffix in (".xlsx", ".xls"):
            df = pd.read_excel(p)
        elif suffix == ".json":
            df = pd.read_json(p)
        elif suffix in (".tsv", ".txt"):
            df = pd.read_csv(p, sep="\t")
        else:
            raise ToolError(f"Unsupported file type: {suffix}")
    except Exception as e:
        raise ToolError(f"Failed to read {p.name}: {type(e).__name__}: {e}") from e

    if df.empty:
        raise ToolError("Dataset is empty (0 rows).")

    store.set_dataframe(df)
    store.set("source_file", str(p))
    # If the file was routed through the UI uploader, its name carries a
    # `<10-hex>__` prefix to avoid collisions. Strip that for display so
    # the dashboard/report show the user's original filename.
    display_name = p.name
    if "__" in display_name:
        prefix, _, rest = display_name.partition("__")
        if len(prefix) == 10 and all(c in "0123456789abcdef" for c in prefix):
            display_name = rest
    store.set("source_name", display_name)
    # Humanized version used for dashboard / report TITLES (not for the
    # "File" row in the Data Source table, which keeps the raw name).
    store.set("source_display_name", humanize_filename(display_name))
    return {
        "dataset_id": "current",
        "row_count": int(len(df)),
        "column_count": int(df.shape[1]),
        "columns": [str(c) for c in df.columns],
    }


def _t_validate_dataset(store: RunStore) -> dict[str, Any]:
    df = store.require_dataframe()
    issues: list[str] = []
    # Duplicate column names
    dup_cols = df.columns[df.columns.duplicated()].tolist()
    if dup_cols:
        issues.append(f"Duplicate column names: {dup_cols}")
    # All-null columns
    all_null = [c for c in df.columns if df[c].isna().all()]
    if all_null:
        issues.append(f"Columns with 100% nulls: {all_null}")
    # Very low row count
    if len(df) < 5:
        issues.append(f"Very few rows ({len(df)}); analysis will be unreliable.")
    # Duplicate rows
    dups = int(df.duplicated().sum())
    if dups:
        issues.append(f"{dups} duplicate rows present.")

    report = {
        "ok": len(issues) == 0,
        "issues": issues,
        "row_count": int(len(df)),
        "column_count": int(df.shape[1]),
        "duplicate_rows": dups,
    }
    store.set("validation", report)
    return report


# --- data prep -------------------------------------------------------------


def _t_profile_dataset(store: RunStore) -> dict[str, Any]:
    df = store.require_dataframe()
    cfg = store.engine_cfg
    profile = profile_dataframe(
        df,
        numeric_id_cardinality_threshold=cfg["numeric_id_cardinality_threshold"],
        categorical_max_cardinality=cfg["categorical_max_cardinality"],
        datetime_parse_threshold=cfg["datetime_parse_threshold"],
        correlation_report_threshold=cfg["correlation_report_threshold"],
        geo_match_threshold=cfg.get("geo_match_threshold", 0.6),
    )
    profile_dict = profile.to_dict()
    store.set("profile", profile_dict)
    return profile_dict


def _t_clean_dataset(store: RunStore, operations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Apply a list of cleaning operations. Each operation is:
      {"op": "drop_duplicates"} |
      {"op": "drop_all_null_columns"} |
      {"op": "fillna", "column": "X", "value": 0 | "mean" | "median" | "mode"} |
      {"op": "to_datetime", "column": "X"} |
      {"op": "strip_strings", "column": "X"} |
      {"op": "drop_column", "column": "X"}
    """
    df = store.require_dataframe()
    operations = operations or []
    applied: list[str] = []
    skipped: list[dict[str, Any]] = []

    for op in operations:
        kind = op.get("op")
        try:
            if kind == "drop_duplicates":
                before = len(df)
                df = df.drop_duplicates().reset_index(drop=True)
                applied.append(f"drop_duplicates: removed {before - len(df)} rows")
            elif kind == "drop_all_null_columns":
                null_cols = [c for c in df.columns if df[c].isna().all()]
                df = df.drop(columns=null_cols)
                applied.append(f"drop_all_null_columns: removed {null_cols}")
            elif kind == "fillna":
                c = op["column"]
                v = op["value"]
                if v == "mean":
                    v = pd.to_numeric(df[c], errors="coerce").mean()
                elif v == "median":
                    v = pd.to_numeric(df[c], errors="coerce").median()
                elif v == "mode":
                    mode = df[c].mode(dropna=True)
                    v = mode.iloc[0] if not mode.empty else None
                df[c] = df[c].fillna(v)
                applied.append(f"fillna({c}={v!r})")
            elif kind == "to_datetime":
                c = op["column"]
                df[c] = pd.to_datetime(df[c], errors="coerce")
                applied.append(f"to_datetime({c})")
            elif kind == "strip_strings":
                c = op["column"]
                if df[c].dtype == object:
                    df[c] = df[c].astype(str).str.strip()
                    applied.append(f"strip_strings({c})")
            elif kind == "drop_column":
                c = op["column"]
                if c in df.columns:
                    df = df.drop(columns=[c])
                    applied.append(f"drop_column({c})")
            else:
                skipped.append({"op": op, "reason": f"unknown op: {kind!r}"})
        except Exception as e:
            skipped.append({"op": op, "reason": f"{type(e).__name__}: {e}"})

    store.set_dataframe(df)
    store.set("cleaning_log", {"applied": applied, "skipped": skipped})
    return {
        "applied": applied,
        "skipped": skipped,
        "row_count": int(len(df)),
        "column_count": int(df.shape[1]),
    }


# --- KPI -------------------------------------------------------------------


def _t_suggest_kpis(store: RunStore) -> dict[str, Any]:
    df = store.require_dataframe()
    cfg = store.engine_cfg
    profile = profile_dataframe(
        df,
        numeric_id_cardinality_threshold=cfg["numeric_id_cardinality_threshold"],
        categorical_max_cardinality=cfg["categorical_max_cardinality"],
        datetime_parse_threshold=cfg["datetime_parse_threshold"],
        correlation_report_threshold=cfg["correlation_report_threshold"],
        geo_match_threshold=cfg.get("geo_match_threshold", 0.6),
    )
    specs = suggest_kpis(profile, top_n=cfg["top_n"], max_kpis=20)
    store.set("kpi_candidates", specs)
    return {"count": len(specs), "kpis": specs}


def _t_compute_kpis(store: RunStore, kpi_ids: list[str] | None = None) -> dict[str, Any]:
    """Compute the curated KPI list. If `kpi_ids` is None, compute all
    candidates."""
    df = store.require_dataframe()
    candidates: list[dict[str, Any]] = store.get("kpi_candidates") or []
    if not candidates:
        # Auto-suggest if the agent skipped that step.
        _t_suggest_kpis(store)
        candidates = store.get("kpi_candidates") or []

    if kpi_ids:
        chosen = [k for k in candidates if k["id"] in kpi_ids]
        # Preserve the order the LLM requested.
        order = {kid: i for i, kid in enumerate(kpi_ids)}
        chosen.sort(key=lambda k: order.get(k["id"], 1_000_000))
    else:
        chosen = candidates

    computed = compute_kpis(df, chosen)
    store.set("kpis", computed)
    return {"count": len(computed), "kpis": computed}


# --- Insights (anomalies + segments) ---------------------------------------


def _profile_obj(store: RunStore):
    """Re-profile the current dataframe into a DatasetProfile object
    (same boilerplate the KPI/chart tools use)."""
    df = store.require_dataframe()
    cfg = store.engine_cfg
    return df, profile_dataframe(
        df,
        numeric_id_cardinality_threshold=cfg["numeric_id_cardinality_threshold"],
        categorical_max_cardinality=cfg["categorical_max_cardinality"],
        datetime_parse_threshold=cfg["datetime_parse_threshold"],
        correlation_report_threshold=cfg["correlation_report_threshold"],
        geo_match_threshold=cfg.get("geo_match_threshold", 0.6),
    )


def _t_detect_anomalies(store: RunStore) -> dict[str, Any]:
    df, profile = _profile_obj(store)
    cfg = store.engine_cfg
    anomalies = detect_anomalies(
        df, profile, z_threshold=cfg.get("anomaly_z_threshold", 3.5)
    )
    store.set("anomalies", anomalies)
    return {"count": len(anomalies), "anomalies": anomalies}


def _t_compare_segments(store: RunStore) -> dict[str, Any]:
    df, profile = _profile_obj(store)
    cfg = store.engine_cfg
    segments = compare_segments(
        df, profile, min_group_size=cfg.get("segment_min_group_size", 20)
    )
    store.set("segments", segments)
    return {"count": len(segments), "segments": segments}


# --- Dashboard -------------------------------------------------------------


def _t_suggest_charts(store: RunStore) -> dict[str, Any]:
    df = store.require_dataframe()
    cfg = store.engine_cfg
    profile = profile_dataframe(
        df,
        numeric_id_cardinality_threshold=cfg["numeric_id_cardinality_threshold"],
        categorical_max_cardinality=cfg["categorical_max_cardinality"],
        datetime_parse_threshold=cfg["datetime_parse_threshold"],
        correlation_report_threshold=cfg["correlation_report_threshold"],
        geo_match_threshold=cfg.get("geo_match_threshold", 0.6),
    )
    specs = suggest_charts(profile, top_n=cfg["top_n"], max_charts=15)
    store.set("chart_candidates", specs)
    return {"count": len(specs), "charts": specs}


def _t_build_chart(store: RunStore, chart_id: str) -> dict[str, Any]:
    df = store.require_dataframe()
    candidates: list[dict[str, Any]] = store.get("chart_candidates") or []
    spec = next((c for c in candidates if c["id"] == chart_id), None)
    if spec is None:
        raise ToolError(
            f"chart_id {chart_id!r} not in candidates. "
            f"Available: {[c['id'] for c in candidates]}"
        )
    html = build_chart(df, spec)
    built = store.get("charts") or []
    built.append({**spec, "html": html})
    store.set("charts", built)
    return {"id": chart_id, "ok": True}


# --- Publishing ------------------------------------------------------------


def _t_build_dashboard(store: RunStore, title: str | None = None) -> dict[str, Any]:
    kpis: list[dict[str, Any]] = store.get("kpis") or []
    charts: list[dict[str, Any]] = store.get("charts") or []
    if not charts and not kpis:
        raise ToolError("Nothing to publish: no KPIs or charts have been built.")

    src_name = store.get("source_name") or "dataset"
    display = store.get("source_display_name") or humanize_filename(src_name) or src_name
    dash_title = title or f"BI Dashboard — {display}"
    subtitle = (
        f"Auto-generated from {src_name} • {len(kpis)} KPIs • {len(charts)} charts"
    )
    html = build_dashboard_html(
        title=dash_title,
        subtitle=subtitle,
        kpis=kpis,
        charts_html=charts,
    )
    out_path = store.artifact_path("dashboard.html")
    out_path.write_text(html, encoding="utf-8")
    store.register_artifact("dashboard", str(out_path))
    return {"path": str(out_path), "bytes": len(html.encode("utf-8"))}


def _t_publish_artifacts(store: RunStore) -> dict[str, Any]:
    """Snapshot the current run state to disk (state.json) and return the
    full artifact manifest."""
    state = store.snapshot()
    state_path = store.artifact_path("state.json")
    state_path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    store.register_artifact("state", str(state_path))
    return store.manifest()


# --- Reporter --------------------------------------------------------------


def _t_generate_report(
    store: RunStore,
    executive_summary: str,
    methodology: str,
    findings: list[str],
    recommendations: list[str] | None = None,
) -> dict[str, Any]:
    """Render the final BI report as a self-contained HTML page using
    the prose blocks the Reporter agent has written."""
    from ..ui.render import render_report_html  # local import to break cycle

    src_name = store.get("source_name") or "dataset"
    display = store.get("source_display_name") or humanize_filename(src_name) or src_name
    profile = store.get("profile") or {}
    kpis = store.get("kpis") or []
    charts = store.get("charts") or []
    validation = store.get("validation") or {}
    cleaning_log = store.get("cleaning_log") or {}
    anomalies = store.get("anomalies") or []
    segments = store.get("segments") or []

    # Ground the narrative: verify every number in the findings against the
    # KPIs/profile the engine actually computed. Flagged (not blocked) so we
    # never loop the agent — the verdict is shown in the report + run view.
    findings_validation = validate_findings(findings or [], kpis, profile, anomalies, segments)
    store.set("findings_validation", findings_validation)

    html = render_report_html(
        run_id=store.run_id,
        source_name=src_name,
        source_display_name=display,
        profile=profile,
        kpis=kpis,
        charts=charts,
        validation=validation,
        cleaning_log=cleaning_log,
        executive_summary=executive_summary,
        methodology=methodology,
        findings=findings,
        recommendations=recommendations or [],
        findings_validation=findings_validation,
        anomalies=anomalies,
        segments=segments,
    )
    out_path = store.artifact_path("report.html")
    out_path.write_text(html, encoding="utf-8")
    store.register_artifact("report", str(out_path))
    return {
        "path": str(out_path),
        "bytes": len(html.encode("utf-8")),
        "findings_validation": findings_validation,
    }


# --- Orchestrator helpers --------------------------------------------------


def _t_list_agents(store: RunStore) -> dict[str, Any]:
    return {"agents": list(store.agent_permissions.keys())}


def _t_get_run_state(store: RunStore) -> dict[str, Any]:
    """Lightweight snapshot for the orchestrator / reporter — excludes
    the DataFrame and chart HTML to keep tokens manageable."""
    snap = store.snapshot()
    # Strip heavyweight bits.
    snap.pop("dataframe_head", None)
    charts = snap.get("charts") or []
    snap["charts"] = [
        {k: v for k, v in c.items() if k != "html"} for c in charts
    ]
    return snap


def _t_set_run_state(store: RunStore, key: str, value: Any) -> dict[str, Any]:
    """Set an arbitrary scratch value on the run state (orchestrator only)."""
    store.set(key, value)
    return {"ok": True, "key": key}


# ---------------------------------------------------------------------------
# Default registry
# ---------------------------------------------------------------------------


def build_default_registry(permissions: dict[str, list[str]]) -> ToolRegistry:
    """Build the registry containing every BI tool, gated by `permissions`."""
    reg = ToolRegistry(permissions=permissions)

    reg.register(Tool(
        name="load_dataset",
        description="Load a raw dataset (CSV, Excel, JSON, TSV) from a local path and register it as the current dataset.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Filesystem path to the dataset file."},
            },
            "required": ["path"],
        },
        handler=_t_load_dataset,
    ))

    reg.register(Tool(
        name="validate_dataset",
        description="Run structural validation on the current dataset and return any issues found.",
        parameters={"type": "object", "properties": {}},
        handler=_t_validate_dataset,
    ))

    reg.register(Tool(
        name="profile_dataset",
        description="Profile the current dataset: per-column role (measure/dimension/datetime/identifier), cardinality, missingness, stats, and inter-measure correlations.",
        parameters={"type": "object", "properties": {}},
        handler=_t_profile_dataset,
    ))

    reg.register(Tool(
        name="clean_dataset",
        description=(
            "Apply a list of cleaning operations. Each operation has shape "
            "{op: 'drop_duplicates'|'drop_all_null_columns'|'fillna'|'to_datetime'|'strip_strings'|'drop_column', ...}. "
            "For fillna, supply 'column' and 'value' (value can be a literal or 'mean'/'median'/'mode')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Ordered list of cleaning operations.",
                }
            },
        },
        handler=_t_clean_dataset,
    ))

    reg.register(Tool(
        name="suggest_kpis",
        description="Produce a generous shortlist of candidate KPIs derived adaptively from the current dataset's profile.",
        parameters={"type": "object", "properties": {}},
        handler=_t_suggest_kpis,
    ))

    reg.register(Tool(
        name="compute_kpis",
        description=(
            "Compute and store KPI values. Pass kpi_ids (a subset of the suggested "
            "candidate ids) to curate; omit to compute all."
        ),
        parameters={
            "type": "object",
            "properties": {
                "kpi_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered list of candidate KPI ids to compute (most important first).",
                }
            },
        },
        handler=_t_compute_kpis,
    ))

    reg.register(Tool(
        name="detect_anomalies",
        description="Detect outlier values per measure (robust modified z-score) and spike periods over time. Stores results for the report.",
        parameters={"type": "object", "properties": {}},
        handler=_t_detect_anomalies,
    ))

    reg.register(Tool(
        name="compare_segments",
        description="Compare each measure across the groups of low-cardinality dimensions and surface the largest top-vs-bottom gaps. Stores results for the report.",
        parameters={"type": "object", "properties": {}},
        handler=_t_compare_segments,
    ))

    reg.register(Tool(
        name="suggest_charts",
        description="Produce a shortlist of candidate chart specs adaptively from the current dataset's profile.",
        parameters={"type": "object", "properties": {}},
        handler=_t_suggest_charts,
    ))

    reg.register(Tool(
        name="build_chart",
        description="Render one candidate chart (by id) as a Plotly figure and add it to the dashboard's chart list.",
        parameters={
            "type": "object",
            "properties": {
                "chart_id": {"type": "string", "description": "Id of the chart from suggest_charts."},
            },
            "required": ["chart_id"],
        },
        handler=_t_build_chart,
    ))

    reg.register(Tool(
        name="build_dashboard",
        description="Assemble the curated KPIs + built charts into a single interactive HTML dashboard and write it to the artifact store.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Optional dashboard title."},
            },
        },
        handler=_t_build_dashboard,
    ))

    reg.register(Tool(
        name="publish_artifacts",
        description="Snapshot the current run state to disk and return the full artifact manifest.",
        parameters={"type": "object", "properties": {}},
        handler=_t_publish_artifacts,
    ))

    reg.register(Tool(
        name="generate_report",
        description=(
            "Render the final BI report as an HTML page. You must supply: executive_summary (3-5 sentences), "
            "methodology (2-4 sentences), findings (3-6 bullet strings, each a concrete observation grounded in the KPIs/charts), "
            "and optional recommendations (1-4 actionable bullets)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "executive_summary": {"type": "string"},
                "methodology": {"type": "string"},
                "findings": {"type": "array", "items": {"type": "string"}},
                "recommendations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["executive_summary", "methodology", "findings"],
        },
        handler=_t_generate_report,
    ))

    reg.register(Tool(
        name="list_agents",
        description="List all agent roles registered in the run.",
        parameters={"type": "object", "properties": {}},
        handler=_t_list_agents,
    ))

    reg.register(Tool(
        name="get_run_state",
        description="Return a lightweight snapshot of the current run state (profile, KPIs, chart specs, artifacts) — excludes raw data and chart HTML.",
        parameters={"type": "object", "properties": {}},
        handler=_t_get_run_state,
    ))

    reg.register(Tool(
        name="set_run_state",
        description="Store an arbitrary value on the run state under the given key. Use for cross-agent coordination notes.",
        parameters={
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {},
            },
            "required": ["key", "value"],
        },
        handler=_t_set_run_state,
    ))

    return reg
