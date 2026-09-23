"""Base Agent class implementing the LLM tool-calling loop.

Each agent:

1. Holds a role name (used to scope MCP tool permissions).
2. Has a role-specific system prompt.
3. Runs a bounded loop: LLM -> tool calls -> tool results -> LLM ...
   until the model emits a final text response (no tool calls) or the
   step budget is exhausted.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from ..llm import ChatMessage, LLMClient, ToolCall, estimate_cost_usd
from ..mcp_server import BIMCPServer, RunStore


class _UsageAccumulator:
    """Sums token usage and latency across the LLM calls of one agent run."""

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.latency_ms = 0
        self.llm_calls = 0

    def add(self, msg: ChatMessage) -> None:
        self.llm_calls += 1
        if msg.latency_ms:
            self.latency_ms += msg.latency_ms
        if msg.usage:
            self.input_tokens += int(msg.usage.get("input_tokens", 0))
            self.output_tokens += int(msg.usage.get("output_tokens", 0))

    def finalize(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "llm_calls": self.llm_calls,
            "latency_ms": self.latency_ms,
            "est_cost_usd": estimate_cost_usd(self.input_tokens, self.output_tokens),
        }


@dataclass
class AgentResult:
    role: str
    final_text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    finished: bool = True
    nudges_used: int = 0
    # {"input_tokens", "output_tokens", "total_tokens", "llm_calls",
    #  "latency_ms", "est_cost_usd"}
    usage: dict[str, Any] = field(default_factory=dict)


class Agent:
    role: str = "base"
    system_prompt: str = "You are a generic agent."

    def __init__(self, llm: LLMClient, server: BIMCPServer):
        self.llm = llm
        self.server = server
        self.max_steps = int(os.getenv("AGENT_MAX_STEPS", "12"))
        self.temperature = float(os.getenv("AGENT_TEMPERATURE", "0.2"))
        # How many times we'll prod an agent that answered without using
        # any tool before giving up and letting the deterministic
        # fallback take over.
        self.nudge_budget = int(os.getenv("AGENT_NUDGE_BUDGET", "2"))

    # ----- Hooks subclasses may override -----------------------------------

    def task_message(self, store: RunStore, **kwargs: Any) -> str:
        """Compose the user task message for this agent run."""
        raise NotImplementedError

    # ----- Main loop -------------------------------------------------------

    def run(self, store: RunStore, **kwargs: Any) -> AgentResult:
        tools = self.server.tools_for(self.role)
        if not tools:
            # Reporter only uses tools via prompt — keep going anyway.
            pass

        task = self.task_message(store, **kwargs)
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=self.system_prompt),
            ChatMessage(role="user", content=task),
        ]

        store.log_event({"type": "agent_start", "role": self.role, "task_preview": task[:300]})

        all_tool_calls: list[dict[str, Any]] = []
        final_text = ""
        nudges_used = 0
        usage_acc = _UsageAccumulator()

        for step in range(1, self.max_steps + 1):
            try:
                response = self.llm.chat(
                    messages=messages,
                    tools=tools if tools else None,
                    temperature=self.temperature,
                )
            except Exception as e:
                store.log_event({
                    "type": "agent_error", "role": self.role, "step": step,
                    "error": f"{type(e).__name__}: {e}",
                })
                return AgentResult(
                    role=self.role,
                    final_text=f"LLM error on step {step}: {e}",
                    tool_calls=all_tool_calls,
                    steps=step,
                    finished=False,
                    nudges_used=nudges_used,
                    usage=usage_acc.finalize(),
                )

            usage_acc.add(response)

            # No tool calls. Either the agent legitimately finished, or it
            # answered with prose without doing any work. If it has used
            # zero tools so far and has tools available, prod it once
            # (within budget) before accepting the text as final — this is
            # what makes the agent actually exercise its judgment instead
            # of leaning on the deterministic fallback.
            if not response.tool_calls:
                if all_tool_calls or not tools or nudges_used >= self.nudge_budget:
                    final_text = response.content or ""
                    messages.append(response)
                    break
                # Nudge.
                messages.append(response)
                tool_names = ", ".join(t["function"]["name"] for t in tools)
                messages.append(ChatMessage(
                    role="user",
                    content=(
                        "You replied without calling any tool, so no work has "
                        "been done yet. To complete your task you MUST call the "
                        f"appropriate tool now. Available to you: {tool_names}. "
                        "Call it — do not just describe what you would do."
                    ),
                ))
                nudges_used += 1
                store.log_event({
                    "type": "agent_nudge", "role": self.role,
                    "step": step, "nudges_used": nudges_used,
                })
                continue

            # Append the assistant turn (with tool_calls) before the tool results.
            messages.append(response)

            for tc in response.tool_calls:
                tool_result = self._execute_tool(store, tc)
                all_tool_calls.append({
                    "tool": tc.name,
                    "arguments": tc.arguments,
                    "result_preview": _preview(tool_result),
                })
                messages.append(ChatMessage(
                    role="tool",
                    tool_call_id=tc.id,
                    name=tc.name,
                    content=json.dumps(tool_result, default=str),
                ))
        else:
            final_text = "(agent step budget exhausted before producing a final message)"
            store.log_event({"type": "agent_budget_exhausted", "role": self.role})

        usage = usage_acc.finalize()
        store.log_event({
            "type": "agent_end", "role": self.role,
            "steps": step, "final_text_preview": final_text[:300],
            "tool_calls": len(all_tool_calls), "nudges_used": nudges_used,
            "usage": usage,
        })

        return AgentResult(
            role=self.role,
            final_text=final_text,
            tool_calls=all_tool_calls,
            steps=step,
            finished=True,
            nudges_used=nudges_used,
            usage=usage,
        )

    def _execute_tool(self, store: RunStore, tc: ToolCall) -> Any:
        try:
            return self.server.call_tool(store, self.role, tc.name, tc.arguments)
        except Exception as e:
            # Return error to the LLM as a structured payload — the
            # tool-call loop continues so it can self-correct.
            return {"error": f"{type(e).__name__}: {e}"}


def _preview(v: Any) -> Any:
    s = json.dumps(v, default=str)
    if len(s) > 500:
        return s[:500] + "…"
    return v
