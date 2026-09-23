"""KPI agent.

Inspects the dataset profile, asks for the deterministic engine's KPI
shortlist, then uses business judgment to pick the most meaningful
subset. Finally computes the curated list.
"""
from __future__ import annotations

import os
from typing import Any

from ..mcp_server import RunStore
from .base import Agent


SYSTEM_PROMPT = """You are the KPI Agent.

Your job:
  1) Call `profile_dataset()` to see the dataset's roles.
  2) Call `suggest_kpis()` to fetch the engine's candidate KPIs (each
     has an `id`, `title`, and `description`).
  3) Curate: pick the SUBSET that would actually be useful in a real
     BI dashboard for THIS dataset, ordered by importance (most useful
     first). Prefer KPIs that:
       - cover the dataset's most central measure(s),
       - include at least one trend KPI if a datetime exists,
       - include at least one composition/share KPI if a dimension exists,
       - avoid redundancy (don't pick both sum and avg of the same column
         unless both genuinely matter).
     Aim for {max_kpis} KPIs maximum.
  4) Call `compute_kpis(kpi_ids=[...])` with your curated ordered list.
  5) Call `detect_anomalies()` to surface outlier values / time spikes.
  6) Call `compare_segments()` to surface the biggest group-vs-group
     differences. (Both store their results for the report; you don't
     pass arguments.)
  7) Reply with a short summary (2-4 sentences) of which KPIs you chose
     and one notable anomaly or segment gap you noticed.

Do NOT invent KPI ids — every id you pass must come from the
suggest_kpis result.
"""


class KPIAgent(Agent):
    role = "kpi"

    @property
    def system_prompt(self) -> str:  # type: ignore[override]
        return SYSTEM_PROMPT.format(max_kpis=os.getenv("MAX_KPIS", "12"))

    def task_message(self, store: RunStore, **kwargs: Any) -> str:
        return (
            "Profile, fetch candidate KPIs, curate and compute the most meaningful ones, "
            "then detect anomalies and compare segments, and summarize."
        )
