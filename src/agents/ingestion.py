"""Ingestion agent.

Loads the file and runs structural validation. Very mechanical role —
the LLM mostly just sequences two tool calls. We let it write a brief
narrative so the UI/Reporter has human-readable context for what was
loaded.
"""
from __future__ import annotations

from typing import Any

from ..mcp_server import RunStore
from .base import Agent


SYSTEM_PROMPT = """You are the Ingestion Agent.

Your job: load the dataset at the given path and validate it. Use ONLY
the tools you have:
  1) Call `load_dataset(path=...)` exactly once.
  2) Call `validate_dataset()` exactly once.
  3) Reply with a short (2-3 sentence) plain-English summary of what
     was loaded and any validation issues. No tables, no JSON.

Do not call any other tools. Do not invent column meanings — you have
no business context yet.
"""


class IngestionAgent(Agent):
    role = "ingestion"
    system_prompt = SYSTEM_PROMPT

    def task_message(self, store: RunStore, *, path: str, **kwargs: Any) -> str:
        return f"Load the dataset from this path, validate it, and summarize:\n\nPATH: {path}"
