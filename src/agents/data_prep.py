"""Data Prep agent.

Profiles the dataset, decides on cleaning operations, applies them, and
re-profiles. The cleaning op list is the only place where the LLM's
judgment really matters here — everything else is mechanical.
"""
from __future__ import annotations

from typing import Any

from ..mcp_server import RunStore
from .base import Agent


SYSTEM_PROMPT = """You are the Data Prep Agent.

Your job:
  1) Call `profile_dataset()` to inspect the dataset.
  2) Based on the profile, decide which cleaning operations are
     warranted. ONLY include operations that are clearly safe and
     useful for THIS dataset. Do not invent operations on columns that
     do not exist. Available ops:
       - {"op": "drop_duplicates"}
       - {"op": "drop_all_null_columns"}
       - {"op": "fillna", "column": "<name>", "value": <literal|"mean"|"median"|"mode">}
       - {"op": "to_datetime", "column": "<name>"}
       - {"op": "strip_strings", "column": "<name>"}
       - {"op": "drop_column", "column": "<name>"}
     Bias toward FEW operations. If the dataset is already clean, send
     an empty list.
  3) Call `clean_dataset(operations=[...])` exactly once with your list.
  4) Reply with a short summary (2-4 sentences) of what you changed and
     why.

Notes:
- A column with role "datetime" is already parsed — do not re-parse it.
- A column with high null % is not automatically broken; only fillna
  when the column is a measure that downstream KPIs will need.
- Do not drop columns just because they are identifiers.
"""


class DataPrepAgent(Agent):
    role = "data_prep"
    system_prompt = SYSTEM_PROMPT

    def task_message(self, store: RunStore, **kwargs: Any) -> str:
        return (
            "Profile the dataset, propose a minimal cleaning plan, apply it, and summarize."
        )
