"""Dashboard Designer agent.

Picks a coherent set of charts from the engine's candidate list and
builds each one. Aims for a balanced dashboard: a trend, a comparison,
a distribution, a composition — not five bar charts.
"""
from __future__ import annotations

import os
from typing import Any

from ..mcp_server import RunStore
from .base import Agent


SYSTEM_PROMPT = """You are the Dashboard Designer Agent.

Your job:
  1) Call `profile_dataset()` if you need to refresh context.
  2) Call `suggest_charts()` to fetch candidate chart specs (each has
     an `id`, `title`, `kind`, and `description`).
  3) Curate a balanced selection of up to {max_charts} charts. Aim for
     diversity of chart kinds:
       - 1-2 line charts (trends), if time exists
       - 2-3 bar charts (top-N by dimension)
       - 1 distribution (histogram or box) per important measure
       - 1 composition (pie) if a low-cardinality dimension exists
       - 1 scatter / heatmap for relationships, if applicable
     Order them so the most informative is first.
  4) For EACH chart you keep, call `build_chart(chart_id=...)` exactly
     once.
  5) Reply with a short summary (2-4 sentences) explaining the
     dashboard's story.

Do not invent chart ids. Do not call `build_chart` more than once per id.
"""


class DashboardAgent(Agent):
    role = "dashboard"

    @property
    def system_prompt(self) -> str:  # type: ignore[override]
        return SYSTEM_PROMPT.format(max_charts=os.getenv("MAX_CHARTS", "10"))

    def task_message(self, store: RunStore, **kwargs: Any) -> str:
        return (
            "Fetch candidate charts, curate a balanced set, build each one, and summarize."
        )
