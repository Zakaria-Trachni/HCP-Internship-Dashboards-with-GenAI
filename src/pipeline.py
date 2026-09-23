"""End-to-end pipeline orchestrator.

Wires the MCP server, the LLM client, and all seven agents together
into a single `run_pipeline(path)` call. Deterministic order; each
agent gets one run.

This is what the FastAPI UI invokes per upload. It is also the entry
point for `scripts/run_demo.sh`.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agents import (
    DashboardAgent,
    DataPrepAgent,
    IngestionAgent,
    KPIAgent,
    OrchestratorAgent,
    PublishingAgent,
    ReporterAgent,
)
from .llm import get_llm_client
from .mcp_server import BIMCPServer, RunStore


def _ensure_stage_outputs(
    stage: str,
    server: BIMCPServer,
    store: RunStore,
    *,
    dataset_path: str | None = None,
) -> list[str]:
    """Deterministic safety net.

    LLM agents sometimes skip required tool calls (especially smaller
    models, or models that interpret their prompt as a question to
    answer rather than a workflow to execute). This function runs after
    each LLM agent and fills in any missing state with direct tool
    invocations under the same role's permissions. The result: every
    pipeline run produces complete artifacts even when an agent's LLM
    misbehaves.

    Returns a list of human-readable notes about what was filled in,
    suitable for surfacing in the UI / agent transcript.
    """
    fallbacks: list[str] = []
    max_kpis = int(os.getenv("MAX_KPIS", "12"))
    max_charts = int(os.getenv("MAX_CHARTS", "10"))

    def _safe(role: str, tool: str, args: dict[str, Any]) -> bool:
        try:
            server.call_tool(store, role, tool, args)
            return True
        except Exception as e:
            store.log_event({
                "type": "fallback_error",
                "stage": stage, "tool": tool,
                "error": f"{type(e).__name__}: {e}",
            })
            return False

    if stage == "ingestion":
        # Two independent safety nets. The LLM often calls load_dataset
        # but forgets validate_dataset (or vice versa), so we check each
        # separately rather than gating one on the other.
        if store.get("source_file") is None and dataset_path:
            if _safe("ingestion", "load_dataset", {"path": dataset_path}):
                fallbacks.append("load_dataset (agent skipped)")
        if store.get("validation") is None:
            if _safe("ingestion", "validate_dataset", {}):
                fallbacks.append("validate_dataset (agent skipped)")

    elif stage == "data_prep":
        if not store.get("profile"):
            if _safe("data_prep", "profile_dataset", {}):
                fallbacks.append("profile_dataset (agent skipped)")

    elif stage == "kpi":
        if not store.get("kpis"):
            if not store.get("profile"):
                _safe("kpi", "profile_dataset", {})
            if not store.get("kpi_candidates"):
                _safe("kpi", "suggest_kpis", {})
            candidates = store.get("kpi_candidates") or []
            top_ids = [k["id"] for k in candidates[:max_kpis]]
            if _safe("kpi", "compute_kpis", {"kpi_ids": top_ids}):
                fallbacks.append(f"compute_kpis on top {len(top_ids)} candidates (agent skipped)")
        # Insights are independent of KPIs — ensure each exists.
        if store.get("anomalies") is None:
            if _safe("kpi", "detect_anomalies", {}):
                fallbacks.append("detect_anomalies (agent skipped)")
        if store.get("segments") is None:
            if _safe("kpi", "compare_segments", {}):
                fallbacks.append("compare_segments (agent skipped)")

    elif stage == "dashboard":
        if not store.get("charts"):
            if not store.get("chart_candidates"):
                _safe("dashboard", "suggest_charts", {})
            candidates = store.get("chart_candidates") or []
            built = 0
            for c in candidates[:max_charts]:
                if _safe("dashboard", "build_chart", {"chart_id": c["id"]}):
                    built += 1
            if built:
                fallbacks.append(f"build_chart × {built} (agent skipped)")

    elif stage == "publishing":
        # Must run AFTER KPI + dashboard fallbacks above. By this point
        # there should be at least KPIs to publish.
        if not store.has_artifact("dashboard"):
            if _safe("publishing", "build_dashboard", {}):
                fallbacks.append("build_dashboard (agent skipped)")
        if not store.has_artifact("state"):
            if _safe("publishing", "publish_artifacts", {}):
                fallbacks.append("publish_artifacts (agent skipped)")

    elif stage == "reporter":
        if not store.has_artifact("report"):
            # Build a minimal grounded report from the actual state, so
            # report.html always exists even if the Reporter LLM bailed.
            profile = store.get("profile") or {}
            kpis = store.get("kpis") or []
            charts = store.get("charts") or []
            rows = profile.get("row_count", 0)
            cols = profile.get("column_count", 0)
            measures = profile.get("measures", []) or []
            dims = profile.get("dimensions", []) or []
            dts = profile.get("datetimes", []) or []
            top = kpis[0]["display"] if kpis else "n/a"
            source = store.get("source_name") or "the uploaded dataset"
            args = {
                "executive_summary": (
                    f"Automated BI analysis of {source}. The dataset has {rows:,} rows "
                    f"across {cols} columns: {len(measures)} measure(s), {len(dims)} dimension(s), "
                    f"and {len(dts)} datetime column(s). The pipeline computed {len(kpis)} KPIs "
                    f"and rendered {len(charts)} chart(s)."
                ),
                "methodology": (
                    "The deterministic engine profiled every column into a semantic role "
                    "(measure, dimension, datetime, identifier), then generated adaptive "
                    "KPI and chart specifications from those roles. The Reporter agent did "
                    "not return a narrative; this is the engine's fallback summary."
                ),
                "findings": [
                    f"Total records: {rows:,}.",
                    f"Schema: {len(measures)} measure(s), {len(dims)} dimension(s), {len(dts)} datetime column(s).",
                    f"Headline KPI: {kpis[0]['title']} = {top}." if kpis else "No numeric measures were available, so most KPIs were degenerate.",
                ] + (
                    [f"Notable correlation: {profile['correlations'][0]['a']} ↔ {profile['correlations'][0]['b']} "
                     f"(r={profile['correlations'][0]['pearson']:+.3f})."]
                    if profile.get("correlations") else []
                ),
                "recommendations": [],
            }
            if _safe("reporter", "generate_report", args):
                fallbacks.append("generate_report with engine-grounded fallback prose (agent skipped)")

    if fallbacks:
        store.log_event({"type": "fallbacks_applied", "stage": stage, "fallbacks": fallbacks})
    return fallbacks


@dataclass
class PipelineResult:
    run_id: str
    artifact_dir: str
    artifacts: dict[str, str]
    agent_outputs: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    ok: bool = True
    error: str | None = None


# Deterministic sequence — Orchestrator runs FIRST (to plan/observe)
# and LAST (so it can see the artifacts in a future variant). For now
# we run it once at the start.
PIPELINE_STAGES = [
    ("ingestion", IngestionAgent),
    ("orchestrator", OrchestratorAgent),
    ("data_prep", DataPrepAgent),
    ("kpi", KPIAgent),
    ("dashboard", DashboardAgent),
    ("publishing", PublishingAgent),
    ("reporter", ReporterAgent),
]


def run_pipeline(
    dataset_path: str | Path,
    *,
    config_path: str | Path = "./config.yaml",
    artifact_root: str | Path | None = None,
    progress_cb: Any = None,
) -> PipelineResult:
    """Run the full pipeline on a single dataset.

    Args:
        dataset_path: Path to the raw file.
        config_path: Path to config.yaml.
        artifact_root: Where to write per-run artifact directories.
            Defaults to env ARTIFACT_ROOT or ./runs.
        progress_cb: Optional callable(stage_name: str, status: str,
            payload: dict) for streaming UI updates.

    Returns:
        PipelineResult with run_id, artifact paths, per-agent outputs.
    """
    artifact_root = Path(artifact_root or os.getenv("ARTIFACT_ROOT", "./runs"))

    server = BIMCPServer(config_path)
    llm = get_llm_client()
    store = server.new_run(artifact_root=artifact_root)

    if progress_cb:
        progress_cb("run", "started", {"run_id": store.run_id, "dataset": str(dataset_path)})

    agent_outputs: list[dict[str, Any]] = []
    result = PipelineResult(
        run_id=store.run_id,
        artifact_dir=str(store.artifact_dir),
        artifacts={},
    )

    for stage, AgentCls in PIPELINE_STAGES:
        if progress_cb:
            progress_cb(stage, "started", {})
        agent = AgentCls(llm=llm, server=server)
        try:
            if stage == "ingestion":
                out = agent.run(store, path=str(dataset_path))
            else:
                out = agent.run(store)
        except Exception as e:
            result.ok = False
            result.error = f"{stage}: {type(e).__name__}: {e}"
            store.log_event({"type": "pipeline_error", "stage": stage, "error": result.error})
            if progress_cb:
                progress_cb(stage, "failed", {"error": result.error})
            break

        # Safety net: ensure the stage's expected outputs exist, calling
        # the missing tools directly under the agent's role permissions
        # if the LLM skipped them.
        try:
            fallbacks = _ensure_stage_outputs(
                stage, server, store, dataset_path=str(dataset_path),
            )
        except Exception as e:
            fallbacks = []
            store.log_event({
                "type": "fallback_unhandled_error",
                "stage": stage, "error": f"{type(e).__name__}: {e}",
            })

        summary = out.final_text or ""
        if fallbacks:
            summary = (
                f"[fallback applied: {', '.join(fallbacks)}]"
                + ("\n" + summary if summary else "")
            )

        agent_outputs.append({
            "stage": stage,
            "role": out.role,
            "final_text": summary,
            "tool_calls": out.tool_calls,
            "steps": out.steps,
            "finished": out.finished,
            "fallbacks": fallbacks,
            "nudges_used": out.nudges_used,
            "usage": out.usage,
        })
        if progress_cb:
            progress_cb(stage, "completed", {
                "summary": summary[:300],
                "tool_calls": len(out.tool_calls),
                "steps": out.steps,
                "fallbacks": fallbacks,
                "nudges_used": out.nudges_used,
                "usage": out.usage,
            })

    result.agent_outputs = agent_outputs
    result.artifacts = dict(store.manifest()["artifacts"])
    result.events = store.events()

    # Run-level usage total (sum across all agent stages).
    usage_total = _sum_usage(a.get("usage") for a in agent_outputs)
    store.set("usage_total", usage_total)

    # Refresh the on-disk snapshot so state.json captures values set AFTER
    # the publishing stage wrote its first snapshot — the reporter's
    # findings_validation and the run-level usage total.
    try:
        state_path = store.artifact_path("state.json")
        if state_path.exists():
            state_path.write_text(
                json.dumps(store.snapshot(), indent=2, default=str), encoding="utf-8"
            )
    except Exception as e:
        store.log_event({"type": "state_refresh_error", "error": f"{type(e).__name__}: {e}"})

    if progress_cb:
        progress_cb("run", "completed" if result.ok else "failed", {
            "artifacts": result.artifacts,
            "error": result.error,
            "usage_total": usage_total,
            "findings_validation": store.get("findings_validation"),
        })
    return result


def _sum_usage(usages) -> dict[str, Any]:
    """Aggregate a sequence of per-agent usage dicts into a run total."""
    total = {
        "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
        "llm_calls": 0, "latency_ms": 0, "est_cost_usd": 0.0,
    }
    for u in usages:
        if not u:
            continue
        for k in ("input_tokens", "output_tokens", "total_tokens", "llm_calls", "latency_ms"):
            total[k] += int(u.get(k, 0) or 0)
        total["est_cost_usd"] += float(u.get("est_cost_usd", 0.0) or 0.0)
    total["est_cost_usd"] = round(total["est_cost_usd"], 6)
    return total


def main() -> None:
    import argparse
    import json

    p = argparse.ArgumentParser(description="Run the full BI pipeline on one dataset.")
    p.add_argument("dataset", help="Path to a CSV / Excel / JSON file.")
    p.add_argument("--config", default="./config.yaml")
    p.add_argument("--artifact-root", default=None)
    args = p.parse_args()

    def cb(stage: str, status: str, payload: dict[str, Any]) -> None:
        print(f"[{stage:>14}] {status:<10} {json.dumps(payload, default=str)[:200]}")

    result = run_pipeline(
        args.dataset,
        config_path=args.config,
        artifact_root=args.artifact_root,
        progress_cb=cb,
    )
    print()
    print("=" * 70)
    print(f"RUN ID         : {result.run_id}")
    print(f"ARTIFACT DIR   : {result.artifact_dir}")
    print(f"STATUS         : {'OK' if result.ok else 'FAILED — ' + (result.error or '')}")
    print(f"ARTIFACTS      :")
    for k, v in result.artifacts.items():
        print(f"  - {k:<12} {v}")


if __name__ == "__main__":
    main()
