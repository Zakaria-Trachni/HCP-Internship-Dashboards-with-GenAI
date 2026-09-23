"""Orchestrator agent.

The Orchestrator in this system does NOT itself invoke specialist
agents via the LLM. Instead, the deterministic `Pipeline` runs the six
specialists in a fixed, well-tested order, and the Orchestrator's role
is to inspect the run state at the end and produce a structured run
plan/summary that the UI surfaces and the Reporter consumes.

This split is deliberate: full agent-on-agent delegation via LLM is
brittle and burns tokens. A deterministic backbone with LLM-curated
specialists gives us reliability AND adaptive intelligence.
"""
from __future__ import annotations

from typing import Any

from ..mcp_server import RunStore
from .base import Agent


SYSTEM_PROMPT = """You are the Orchestrator of a multi-agent BI pipeline.

Your job: inspect the current run state via the `get_run_state` tool and
produce a short, structured run plan in plain English. The pipeline
steps are FIXED and run in this order by the engine: Ingestion ->
Data Prep -> KPI -> Dashboard -> Publishing -> Reporter.

You do NOT execute those steps yourself. You write the plan, note the
dataset's apparent shape (rows, columns, measures vs dimensions), and
flag anything unusual (missing data, very small sample, no datetime
column, no numeric column, etc.) for downstream agents to be aware of.

Output: 4-8 short bullet points. No preamble, no closing remark.
"""


class OrchestratorAgent(Agent):
    role = "orchestrator"
    system_prompt = SYSTEM_PROMPT

    def task_message(self, store: RunStore, **kwargs: Any) -> str:
        return (
            "Call `get_run_state` once, then write the run plan as bullet points. "
            "Focus on: dataset shape, what the specialists should pay attention to, "
            "and any risks visible from the profile."
        )
