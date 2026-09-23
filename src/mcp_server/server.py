"""MCP server + RunStore.

`RunStore` holds the per-run state (current DataFrame, profile, KPIs,
charts, artifact manifest, run-scoped scratch values). It also knows
the artifact directory layout.

`BIMCPServer` wires a `ToolRegistry` to either:

  1. An in-process call interface (used by the FastAPI pipeline), or
  2. An MCP stdio server (so external MCP clients — Claude Desktop,
     the `mcp` CLI — can drive the same tools).

The MCP stdio server is started by `python -m src.mcp_server.server`.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


# ---------------------------------------------------------------------------
# RunStore
# ---------------------------------------------------------------------------


class RunStore:
    """Per-run, in-memory state. Backed by an artifact directory on disk
    that tools write into."""

    def __init__(
        self,
        run_id: str,
        artifact_dir: Path,
        agent_permissions: dict[str, list[str]],
        engine_cfg: dict[str, Any],
    ):
        self.run_id = run_id
        self.artifact_dir = artifact_dir
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.agent_permissions = agent_permissions
        self.engine_cfg = engine_cfg
        self._df: pd.DataFrame | None = None
        self._state: dict[str, Any] = {}
        self._artifacts: dict[str, str] = {}
        self._created_at = datetime.now(timezone.utc).isoformat()
        self._events: list[dict[str, Any]] = []

    # ----- DataFrame -------------------------------------------------------

    def set_dataframe(self, df: pd.DataFrame) -> None:
        self._df = df

    def require_dataframe(self) -> pd.DataFrame:
        if self._df is None:
            from .tools import ToolError
            raise ToolError("No dataset loaded. Call `load_dataset` first.")
        return self._df

    # ----- Generic state ---------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        self._state[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._state.get(key, default)

    # ----- Artifacts -------------------------------------------------------

    def artifact_path(self, name: str) -> Path:
        return self.artifact_dir / name

    def register_artifact(self, key: str, path: str) -> None:
        self._artifacts[key] = path

    def has_artifact(self, key: str) -> bool:
        return key in self._artifacts

    def manifest(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "artifact_dir": str(self.artifact_dir),
            "artifacts": dict(self._artifacts),
            "created_at": self._created_at,
        }

    # ----- Events (for the UI to stream) -----------------------------------

    def log_event(self, event: dict[str, Any]) -> None:
        event = dict(event)
        event["ts"] = datetime.now(timezone.utc).isoformat()
        self._events.append(event)

    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    # ----- Snapshot --------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        head = None
        if self._df is not None:
            head = self._df.head(5).to_dict(orient="records")
        return {
            "run_id": self.run_id,
            "created_at": self._created_at,
            "artifacts": dict(self._artifacts),
            "state": {k: v for k, v in self._state.items() if k not in ("charts",)},
            # charts excluded from full state.json copy because the HTML is huge;
            # they live in dashboard.html instead.
            "dataframe_head": head,
            "agent_permissions": self.agent_permissions,
        }


# ---------------------------------------------------------------------------
# BIMCPServer
# ---------------------------------------------------------------------------


class BIMCPServer:
    """The MCP server façade. Wraps a `ToolRegistry` and a `RunStore`."""

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise FileNotFoundError(f"config.yaml not found at {self.config_path}")
        with self.config_path.open("r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.agent_permissions: dict[str, list[str]] = {
            role: cfg["tools"] for role, cfg in self.config["agents"].items()
        }
        self.engine_cfg: dict[str, Any] = self.config["engine"]

        # Lazy: we don't build the registry until we know the run.
        from .tools import build_default_registry
        self.registry = build_default_registry(self.agent_permissions)

    # ----- in-process API --------------------------------------------------

    def new_run(self, artifact_root: str | Path) -> RunStore:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        artifact_dir = Path(artifact_root) / run_id
        return RunStore(
            run_id=run_id,
            artifact_dir=artifact_dir,
            agent_permissions=self.agent_permissions,
            engine_cfg=self.engine_cfg,
        )

    def call_tool(
        self,
        store: RunStore,
        role: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """In-process tool call. Enforces per-agent permissions."""
        start = time.perf_counter()
        store.log_event({"type": "tool_call", "role": role, "tool": tool_name, "arguments": _redact(arguments)})
        try:
            result = self.registry.call(role=role, name=tool_name, arguments=arguments, store=store)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            store.log_event({
                "type": "tool_result",
                "role": role,
                "tool": tool_name,
                "ok": True,
                "elapsed_ms": elapsed_ms,
                "summary": _summarize_result(result),
            })
            return result
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            store.log_event({
                "type": "tool_result",
                "role": role,
                "tool": tool_name,
                "ok": False,
                "elapsed_ms": elapsed_ms,
                "error": f"{type(e).__name__}: {e}",
            })
            raise

    def tools_for(self, role: str) -> list[dict[str, Any]]:
        return self.registry.openai_specs_for(role)

    # ----- MCP stdio server ------------------------------------------------

    async def serve_stdio(self) -> None:
        """Expose the registry over the MCP protocol via stdio.

        Each tool is registered with a synthetic prefix indicating the
        role: e.g. `kpi__compute_kpis`. The role is derived from the
        tool name on each call. This keeps the protocol simple while
        still letting external clients discover what each agent can do.
        """
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import Tool as MCPTool, TextContent

        app = Server("mcp-bi-ecosystem")

        # Single global store for the stdio session (one run per process).
        store = self.new_run(artifact_root=os.getenv("ARTIFACT_ROOT", "./runs"))

        # Flatten role -> tools into role__tool pseudo-tools so any
        # client can see exactly which agent each call belongs to.
        flat: list[MCPTool] = []
        flat_handlers: dict[str, tuple[str, str]] = {}  # tool_name -> (role, real_name)
        for role, names in self.agent_permissions.items():
            for n in names:
                tool = self.registry._tools.get(n)
                if tool is None:
                    continue
                flat_name = f"{role}__{n}"
                flat.append(MCPTool(
                    name=flat_name,
                    description=f"[{role}] {tool.description}",
                    inputSchema=tool.parameters,
                ))
                flat_handlers[flat_name] = (role, n)

        @app.list_tools()
        async def list_tools() -> list[MCPTool]:
            return flat

        @app.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            if name not in flat_handlers:
                return [TextContent(type="text", text=json.dumps({"error": f"unknown tool {name}"}))]
            role, real_name = flat_handlers[name]
            try:
                result = self.call_tool(store, role, real_name, arguments or {})
                return [TextContent(type="text", text=json.dumps(result, default=str, indent=2))]
            except Exception as e:
                return [TextContent(type="text", text=json.dumps({"error": f"{type(e).__name__}: {e}"}))]

        async with stdio_server() as (read, write):
            await app.run(read, write, app.create_initialization_options())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _redact(args: dict[str, Any]) -> dict[str, Any]:
    """Trim arguments for event log readability."""
    out = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 200:
            out[k] = v[:200] + "…"
        elif isinstance(v, list) and len(v) > 12:
            out[k] = v[:12] + [f"… (+{len(v)-12} more)"]
        else:
            out[k] = v
    return out


def _summarize_result(result: Any) -> Any:
    """Compress tool results for the event log."""
    if isinstance(result, dict):
        out = {}
        for k, v in result.items():
            if isinstance(v, list) and len(v) > 5:
                out[k] = f"<list len={len(v)}>"
            elif isinstance(v, str) and len(v) > 200:
                out[k] = v[:200] + "…"
            else:
                out[k] = v
        return out
    return result


# ---------------------------------------------------------------------------
# Stdio entry point
# ---------------------------------------------------------------------------


def _stdio_main() -> None:
    cfg = os.getenv("BI_CONFIG", "./config.yaml")
    server = BIMCPServer(cfg)
    asyncio.run(server.serve_stdio())


if __name__ == "__main__":
    _stdio_main()
