"""Provider-agnostic chat client supporting tool use.

Two providers are supported:

- Groq (recommended; hosted Llama 3.x / Mixtral, OpenAI-compatible API).
- Ollama (local; OpenAI-compatible /chat endpoint with `tools` support
  in recent versions).

Both providers accept OpenAI-style `tools=[{...}]` and respond with
`message.tool_calls`. We normalize their outputs to a single shape.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Normalized types
# ---------------------------------------------------------------------------

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatMessage:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    # For role="tool" only:
    tool_call_id: str | None = None
    name: str | None = None
    # Response-only metadata (populated by the client on assistant turns;
    # ignored by `to_openai`). usage = {"input_tokens", "output_tokens",
    # "total_tokens"}.
    usage: dict[str, int] | None = None
    latency_ms: int | None = None

    def to_openai(self) -> dict[str, Any]:
        """Convert to the OpenAI-compatible wire format used by both
        Groq and Ollama."""
        if self.role == "tool":
            return {
                "role": "tool",
                "tool_call_id": self.tool_call_id,
                "name": self.name,
                "content": self.content,
            }
        msg: dict[str, Any] = {"role": self.role, "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in self.tool_calls
            ]
        return msg


# ---------------------------------------------------------------------------
# Client interface
# ---------------------------------------------------------------------------


class LLMClient:
    """Subclassed by GroqClient and OllamaClient."""

    model: str

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> ChatMessage:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Groq
# ---------------------------------------------------------------------------


class GroqClient(LLMClient):
    def __init__(self, api_key: str, model: str):
        from groq import Groq  # local import so Ollama-only users don't need groq installed

        self._client = Groq(api_key=api_key)
        self.model = model

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> ChatMessage:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_openai() for m in messages],
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        t0 = time.perf_counter()
        resp = self._client.chat.completions.create(**kwargs)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        choice = resp.choices[0].message

        tool_calls: list[ToolCall] = []
        if getattr(choice, "tool_calls", None):
            for tc in choice.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        return ChatMessage(
            role="assistant",
            content=choice.content or "",
            tool_calls=tool_calls,
            usage=_usage_from_openai(getattr(resp, "usage", None)),
            latency_ms=latency_ms,
        )


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


class OllamaClient(LLMClient):
    def __init__(self, host: str, model: str):
        import ollama

        self._client = ollama.Client(host=host)
        self.model = model

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> ChatMessage:
        # Ollama uses an almost-identical schema. `tool_calls` shows up
        # under the same field name on the response.
        wire_messages = [m.to_openai() for m in messages]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": wire_messages,
            "options": {"temperature": temperature},
        }
        if tools:
            kwargs["tools"] = tools

        t0 = time.perf_counter()
        resp = self._client.chat(**kwargs)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        msg = resp["message"]

        tool_calls: list[ToolCall] = []
        for i, tc in enumerate(msg.get("tool_calls", []) or []):
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            # Ollama sometimes returns arguments as a dict already, sometimes
            # as a JSON string. Normalize.
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_raw": args}
            tool_calls.append(
                ToolCall(
                    id=tc.get("id") or f"call_{i}",
                    name=fn.get("name", ""),
                    arguments=args or {},
                )
            )

        # Ollama reports token counts under different keys.
        in_tok = int(resp.get("prompt_eval_count", 0) or 0)
        out_tok = int(resp.get("eval_count", 0) or 0)
        usage = (
            {"input_tokens": in_tok, "output_tokens": out_tok, "total_tokens": in_tok + out_tok}
            if (in_tok or out_tok)
            else None
        )

        return ChatMessage(
            role="assistant",
            content=msg.get("content", "") or "",
            tool_calls=tool_calls,
            usage=usage,
            latency_ms=latency_ms,
        )


# ---------------------------------------------------------------------------
# Usage helpers
# ---------------------------------------------------------------------------


def _usage_from_openai(usage: Any) -> dict[str, int] | None:
    """Normalize an OpenAI-style usage object (Groq) to our shape."""
    if usage is None:
        return None
    pt = int(getattr(usage, "prompt_tokens", 0) or 0)
    ct = int(getattr(usage, "completion_tokens", 0) or 0)
    tt = int(getattr(usage, "total_tokens", 0) or (pt + ct))
    if not (pt or ct or tt):
        return None
    return {"input_tokens": pt, "output_tokens": ct, "total_tokens": tt}


def estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Best-effort cost estimate from env-configured per-1K prices.

    Returns 0.0 when prices are unset (e.g. local Ollama). Always treat
    the result as an estimate — actual billing depends on the provider.
    """
    try:
        in_price = float(os.getenv("LLM_PRICE_PER_1K_INPUT", "0") or "0")
        out_price = float(os.getenv("LLM_PRICE_PER_1K_OUTPUT", "0") or "0")
    except ValueError:
        return 0.0
    return round((input_tokens / 1000.0) * in_price + (output_tokens / 1000.0) * out_price, 6)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_llm_client() -> LLMClient:
    """Pick provider based on env vars. Raises if misconfigured."""
    provider = os.getenv("LLM_PROVIDER", "groq").strip().lower()

    if provider == "groq":
        key = os.getenv("GROQ_API_KEY")
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        if not key or key == "your_groq_api_key_here":
            raise RuntimeError(
                "GROQ_API_KEY is not set. Set it in .env or switch "
                "LLM_PROVIDER=ollama to use a local model."
            )
        return GroqClient(api_key=key, model=model)

    if provider == "ollama":
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        return OllamaClient(host=host, model=model)

    raise RuntimeError(f"Unknown LLM_PROVIDER: {provider!r} (expected 'groq' or 'ollama')")
