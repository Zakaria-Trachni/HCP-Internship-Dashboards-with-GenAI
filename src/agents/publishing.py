"""Publishing agent.

Assembles the curated KPIs + built charts into a self-contained
interactive dashboard.html, then snapshots the full run state.
"""
from __future__ import annotations

from typing import Any

from ..mcp_server import RunStore
from .base import Agent


SYSTEM_PROMPT = """You are the Publishing Agent.

Your job:
  1) Call `build_dashboard(title=...)` to assemble the interactive
     dashboard. Choose a concise, professional title that references the
     dataset (the source filename is available in run state).
  2) Call `publish_artifacts()` to snapshot the full run state.
  3) Reply with a one-sentence confirmation including the dashboard's
     output path.
"""


class PublishingAgent(Agent):
    role = "publishing"
    system_prompt = SYSTEM_PROMPT

    def task_message(self, store: RunStore, **kwargs: Any) -> str:
        src_name = store.get("source_name") or "dataset"
        return (
            f"Build the dashboard and publish all artifacts. The source "
            f"file is {src_name!r}; pick a clean title that references it."
        )
