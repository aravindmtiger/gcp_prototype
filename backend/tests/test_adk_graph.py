"""Canvas architecture to ADK graph: the compile rules, the generated source, and the save path."""

import ast

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import SessionLocal
from app.main import app
from app.schemas import AgentArchitecture
from app.services.adk_draft import render_adk_agent
from app.services.adk_graph import ArchitectureError, compile_architecture
from app.services.seed import ensure_default_guardrail

ALICE = {"X-Dev-User": "alice@example.com"}


def _graph(
    nodes: list[str], edges: list[tuple[str, str]], markers: bool = False
) -> AgentArchitecture:
    items = [{"id": n, "kind": "tool", "tool": "web_search"} for n in nodes]
    if markers:
        items = [{"id": "start", "kind": "start"}, *items, {"id": "end", "kind": "end"}]
    return AgentArchitecture.model_validate(
        {
            "nodes": items,
            "edges": [{"id": f"{a}_{b}", "source": a, "target": b} for a, b in edges],
        }
    )


def test_a_chain_runs_one_agent_after_another():
    compiled = compile_architecture(_graph(["a", "b", "c"], [("a", "b"), ("b", "c")]), "flow")
    assert compiled.root["type"] == "sequential"
    assert [step["name"] for step in compiled.root["sub_agents"]] == ["a", "b", "c"]
    assert compiled.order == ["a", "b", "c"]
    assert compiled.root["sub_agents"][1]["reads"] == ["a"]


def test_a_fan_out_runs_in_parallel_then_joins():
    architecture = _graph(["a", "b", "c", "d"], [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")])
    compiled = compile_architecture(architecture, "flow")
    steps = compiled.root["sub_agents"]
    assert steps[0]["name"] == "a"
    assert {member["name"] for member in steps[1]["sub_agents"]} == {"b", "c"}
    assert steps[1]["type"] == "parallel"
    assert steps[2]["name"] == "d"
    assert set(steps[2]["reads"]) == {"b", "c"}


def test_a_loop_is_rejected_with_the_nodes_in_it():
    with pytest.raises(ArchitectureError) as info:
        compile_architecture(_graph(["a", "b"], [("a", "b"), ("b", "a")]), "flow")
    assert "loops back" in info.value.messages[0]
    assert "a, b" in info.value.messages[0]


def test_start_and_end_markers_do_not_add_agents_or_dependencies():
    markers = AgentArchitecture.model_validate(
        {
            "nodes": [
                {"id": "start", "kind": "start"},
                {"id": "a", "kind": "tool", "tool": "web_search"},
                {"id": "end", "kind": "end"},
            ],
            "edges": [
                {"id": "s", "source": "start", "target": "a"},
                {"id": "e", "source": "a", "target": "end"},
            ],
        }
    )
    compiled = compile_architecture(markers, "flow")
    assert compiled.order == ["a"]
    assert compiled.root["type"] == "llm"
    assert compiled.root["name"] == "flow"


def test_generated_source_is_valid_python_with_the_graph_structure():
    architecture = _graph(["a", "b", "c", "d"], [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")])
    compiled = compile_architecture(architecture, "flow")
    source = render_adk_agent("flow", "Answers", compiled.as_dict())
    ast.parse(source)
    assert "ParallelAgent(" in source
    assert "root_agent = group_" in source
    assert "{b?}" in source and "{c?}" in source


def test_architecture_rules_are_checked_when_parsed():
    with pytest.raises(ValueError, match="itself"):
        _graph(["a"], [("a", "a")])
    with pytest.raises(ValueError, match="not on the canvas"):
        AgentArchitecture.model_validate(
            {
                "nodes": [{"id": "a", "kind": "tool", "tool": "web_search"}],
                "edges": [{"id": "x", "source": "a", "target": "ghost"}],
            }
        )


@pytest.fixture
async def client(database):
    async with SessionLocal() as session:
        await ensure_default_guardrail(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


async def test_saving_a_draft_stores_the_architecture_and_the_adk_graph(client):
    payload = {
        "name": "flow_agent",
        "description": "Answers",
        "architecture": {
            "nodes": [
                {"id": "start", "kind": "start", "position": {"x": 0, "y": 0}},
                {
                    "id": "lookup",
                    "kind": "tool",
                    "tool": "web_search",
                    "position": {"x": 200, "y": 0},
                },
                {
                    "id": "answer",
                    "kind": "tool",
                    "tool": "web_search",
                    "position": {"x": 400, "y": 0},
                },
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "lookup"},
                {"id": "e2", "source": "lookup", "target": "answer"},
            ],
        },
    }
    created = await client.post("/api/v1/agents", headers=ALICE, json=payload)
    assert created.status_code == 201, created.text
    agent = created.json()
    assert agent["architecture"]["edges"][1]["target"] == "answer"
    assert agent["adk_graph"]["root"]["type"] == "sequential"
    assert "SequentialAgent(" in agent["adk_source"]


async def test_a_looping_canvas_is_refused_with_a_clear_message(client):
    payload = {
        "name": "loop_agent",
        "description": "Loops",
        "architecture": {
            "nodes": [
                {"id": "a", "kind": "tool", "tool": "web_search"},
                {"id": "b", "kind": "tool", "tool": "web_search"},
            ],
            "edges": [
                {"id": "x", "source": "a", "target": "b"},
                {"id": "y", "source": "b", "target": "a"},
            ],
        },
    }
    refused = await client.post("/api/v1/agents", headers=ALICE, json=payload)
    assert refused.status_code == 422
    assert "loops back" in refused.json()["detail"]
