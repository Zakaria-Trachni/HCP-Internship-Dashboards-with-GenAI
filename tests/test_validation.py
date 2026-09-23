"""Tests for grounded-findings validation and the retry-with-nudge loop.

These are LLM-free: the validator is pure Python, and the nudge test
drives the agent loop with a scripted fake LLM client.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.core.validation import extract_numbers, validate_findings
from src.llm import ChatMessage, LLMClient, ToolCall
from src.mcp_server import BIMCPServer


# ---------------------------------------------------------------------------
# Validator fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kpis() -> list[dict]:
    return [
        {"id": "total_revenue", "value": 1_325_855.86, "display": "1,325,855.86"},
        {"id": "total_records", "value": 4000, "display": "4,000"},
        {"id": "top_share", "value": 0.234, "display": "23.4% (North)"},
    ]


@pytest.fixture
def profile() -> dict:
    return {
        "row_count": 4000,
        "column_count": 12,
        "columns": [
            {"name": "revenue", "role": "measure", "min": 5.0, "max": 2808.0, "mean": 331.46},
        ],
        "correlations": [{"a": "unit_price", "b": "revenue", "pearson": 0.664}],
    }


# ---------------------------------------------------------------------------
# extract_numbers
# ---------------------------------------------------------------------------


def test_extract_numbers_handles_formats():
    nums = extract_numbers("Revenue was $1.3M across 4,000 orders, up 12.5% with r=0.66.")
    assert any(abs(n - 1_300_000) < 1 for n in nums)   # $1.3M
    assert any(abs(n - 4000) < 1 for n in nums)        # 4,000
    assert any(abs(n - 12.5) < 0.001 for n in nums)    # 12.5%
    assert any(abs(n - 0.66) < 0.001 for n in nums)    # 0.66


def test_magnitude_suffix_not_confused_with_words():
    # The 'm' of "measure" must NOT be read as "million".
    nums = extract_numbers("Schema: 3 measure(s), 7 dimension(s), 1 datetime column(s).")
    assert 3 in nums and 7 in nums and 1 in nums
    assert 3_000_000 not in nums
    # But a real attached suffix still works.
    assert any(abs(n - 3_000_000) < 1 for n in extract_numbers("about 3M rows"))


# ---------------------------------------------------------------------------
# validate_findings
# ---------------------------------------------------------------------------


def test_all_supported_is_verified(kpis, profile):
    findings = [
        "The dataset holds 4,000 records.",
        "Total revenue is 1,325,855.86.",
        "The North region contributes 23.4% of revenue.",
    ]
    res = validate_findings(findings, kpis, profile)
    assert res["verdict"] == "verified"
    assert res["supported"] == res["checked"]
    assert res["unsupported"] == []


def test_rounded_value_still_supported(kpis, profile):
    # Prose rounds 1,325,855.86 -> "$1.3M"; within tolerance, supported.
    res = validate_findings(["Total revenue is about $1.3M."], kpis, profile)
    assert res["verdict"] == "verified"
    assert res["supported"] == 1


def test_hallucinated_number_flagged(kpis, profile):
    findings = [
        "There are 4,000 records.",          # supported
        "Mystery metric reached 87,654.",     # invented
    ]
    res = validate_findings(findings, kpis, profile)
    assert res["verdict"] == "partial"
    assert res["supported"] == 1
    assert res["checked"] == 2
    assert any("87,654" in u["number"] for u in res["unsupported"])


def test_percent_matches_fraction_kpi(kpis, profile):
    # KPI stores 0.234; prose says "23.4%".
    res = validate_findings(["North drives 23.4% of revenue."], kpis, profile)
    assert res["verdict"] == "verified"


def test_no_numbers_is_verified(kpis, profile):
    res = validate_findings(["Revenue is concentrated in a few regions."], kpis, profile)
    assert res["verdict"] == "verified"
    assert res["checked"] == 0


def test_all_unsupported_is_none(kpis, profile):
    res = validate_findings(["Sales hit 999,999 and grew 314%."], kpis, profile)
    assert res["verdict"] == "none"
    assert res["supported"] == 0


# ---------------------------------------------------------------------------
# Retry-with-nudge
# ---------------------------------------------------------------------------


class _ScriptedLLM(LLMClient):
    """Returns pre-scripted ChatMessages in order, so we can simulate an
    agent that skips its tool on the first turn then complies."""

    model = "scripted"

    def __init__(self, script: list[ChatMessage]):
        self._script = script
        self._i = 0

    def chat(self, messages, *, tools=None, temperature=0.2):
        msg = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        return msg


def _write_tiny_csv(tmp_path: Path) -> str:
    p = tmp_path / "tiny.csv"
    p.write_text("a,b\n1,x\n2,y\n3,z\n4,x\n5,y\n", encoding="utf-8")
    return str(p)


def test_nudge_makes_skipping_agent_use_its_tool(tmp_path):
    from src.agents import IngestionAgent

    cfg = Path(__file__).resolve().parent.parent / "config.yaml"
    server = BIMCPServer(cfg)
    store = server.new_run(artifact_root=tmp_path)
    csv_path = _write_tiny_csv(tmp_path)

    # Turn 1: prose only (skips the tool) -> should trigger a nudge.
    # Turn 2: calls load_dataset -> tool executes.
    # Turn 3: prose -> agent finishes.
    script = [
        ChatMessage(role="assistant", content="I will load the dataset."),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="c1", name="load_dataset", arguments={"path": csv_path})],
        ),
        ChatMessage(role="assistant", content="Loaded and validated."),
    ]
    agent = IngestionAgent(llm=_ScriptedLLM(script), server=server)
    result = agent.run(store, path=csv_path)

    assert result.nudges_used == 1
    # The dataset was actually loaded because the nudge made the agent
    # call its tool (no deterministic fallback involved here).
    assert store.require_dataframe().shape[0] == 5
    assert any(tc["tool"] == "load_dataset" for tc in result.tool_calls)


def test_no_nudge_when_agent_uses_tool_immediately(tmp_path):
    from src.agents import IngestionAgent

    cfg = Path(__file__).resolve().parent.parent / "config.yaml"
    server = BIMCPServer(cfg)
    store = server.new_run(artifact_root=tmp_path)
    csv_path = _write_tiny_csv(tmp_path)

    script = [
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="c1", name="load_dataset", arguments={"path": csv_path})],
        ),
        ChatMessage(role="assistant", content="Done."),
    ]
    agent = IngestionAgent(llm=_ScriptedLLM(script), server=server)
    result = agent.run(store, path=csv_path)
    assert result.nudges_used == 0
