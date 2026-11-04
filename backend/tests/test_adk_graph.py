"""Canvas architecture compilation, generated ADK source, and save validation."""

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
    items = [{"id": name, "kind": "tool", "tool": "web_search"} for name in nodes]
    if markers:
        items = [{"id": "start", "kind": "start"}, *items, {"id": "end", "kind": "end"}]
    return AgentArchitecture.model_validate(
        {
            "nodes": items,
            "edges": [{"id": f"{a}_{b}", "source": a, "target": b} for a, b in edges],
        }
    )


def test_a_chain_compiles_to_connected_workflow_nodes():
    compiled = compile_architecture(_graph(["a", "b", "c"], [("a", "b"), ("b", "c")]), "flow")
    assert compiled.root["type"] == "workflow"
    assert compiled.order == ["a", "b", "c"]
    assert [node["name"] for node in compiled.root["nodes"]] == ["a", "b", "c"]
    assert compiled.root["entry_nodes"] == ["a"]
    assert compiled.root["edges"] == [
        {"source": "a", "target": "b", "route": None},
        {"source": "b", "target": "c", "route": None},
    ]
    assert compiled.root["nodes"][1]["reads"] == ["a"]


def test_a_fan_out_keeps_every_edge_for_adk_concurrency():
    architecture = _graph(
        ["a", "b", "c", "d"],
        [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")],
    )
    compiled = compile_architecture(architecture, "flow")
    assert compiled.order == ["a", "b", "c", "d"]
    assert len(compiled.root["edges"]) == 4
    assert compiled.root["nodes"][-1]["reads"] == ["b", "c"]


def test_unbounded_cycles_are_rejected():
    with pytest.raises(ArchitectureError, match="not controlled by a Loop"):
        compile_architecture(_graph(["a", "b"], [("a", "b"), ("b", "a")]), "flow")


def test_a_loop_node_can_control_a_bounded_cycle():
    architecture = AgentArchitecture.model_validate(
        {
            "nodes": [
                {"id": "start", "kind": "start"},
                {"id": "repeat", "kind": "tool", "tool": "loop", "config": {"max_iterations": 4}},
                {"id": "body", "kind": "tool", "tool": "base"},
                {"id": "end", "kind": "end"},
            ],
            "edges": [
                {"id": "start", "source": "start", "target": "repeat"},
                {"id": "continue", "source": "repeat", "target": "body", "route": "continue"},
                {"id": "again", "source": "body", "target": "repeat"},
                {"id": "exit", "source": "repeat", "target": "end", "route": "exit"},
            ],
        }
    )
    compiled = compile_architecture(architecture, "flow")
    assert compiled.order == ["repeat", "body"]
    assert {"source": "repeat_route", "target": "body", "route": "continue"} in compiled.root[
        "edges"
    ]
    source = render_adk_agent("flow", "Repeat safely", compiled.as_dict())
    namespace = {}
    exec(compile(source, "agent.py", "exec"), namespace)
    assert namespace["root_agent"].name == "flow"


def test_control_nodes_require_explicit_labeled_paths():
    architecture = AgentArchitecture.model_validate(
        {
            "nodes": [
                {"id": "start", "kind": "start"},
                {"id": "route", "kind": "tool", "tool": "router"},
                {"id": "one", "kind": "tool", "tool": "base"},
                {"id": "two", "kind": "tool", "tool": "base"},
                {"id": "end", "kind": "end"},
            ],
            "edges": [
                {"id": "s", "source": "start", "target": "route"},
                {"id": "one", "source": "route", "target": "one", "route": "approve"},
                {"id": "two", "source": "route", "target": "two", "route": "reject"},
            ],
        }
    )
    compiled = compile_architecture(architecture, "flow")
    assert {"source": "route_route", "target": "one", "route": "approve"} in compiled.root["edges"]
    assert compiled.root["nodes"][0]["routes"] == ["approve", "reject"]
    source = render_adk_agent("flow", "Choose a route", compiled.as_dict())
    namespace = {}
    exec(compile(source, "agent.py", "exec"), namespace)
    assert namespace["root_agent"].name == "flow"

    invalid = architecture.model_copy(
        update={
            "edges": [
                architecture.edges[0],
                architecture.edges[1].model_copy(update={"route": None}),
                architecture.edges[2],
            ]
        }
    )
    with pytest.raises(ArchitectureError, match="route label"):
        compile_architecture(invalid, "flow")


def test_hitl_compiles_to_resumable_choice_node():
    architecture = AgentArchitecture.model_validate(
        {
            "nodes": [
                {"id": "start", "kind": "start"},
                {
                    "id": "approval",
                    "kind": "tool",
                    "tool": "hitl",
                    "config": {"message": "Approve?"},
                },
                {"id": "yes", "kind": "tool", "tool": "base"},
                {"id": "no", "kind": "tool", "tool": "base"},
                {"id": "end", "kind": "end"},
            ],
            "edges": [
                {"id": "s", "source": "start", "target": "approval"},
                {"id": "y", "source": "approval", "target": "yes", "route": "approve"},
                {"id": "n", "source": "approval", "target": "no", "route": "reject"},
            ],
        }
    )
    graph = compile_architecture(architecture, "flow").as_dict()
    source = render_adk_agent("flow", "Review", graph)
    ast.parse(source)
    namespace = {}
    exec(compile(source, "agent.py", "exec"), namespace)
    assert "RequestInput(" in source
    assert "rerun_on_resume=True" in source
    assert namespace["root_agent"].name == "flow"


def test_generated_source_instantiates_a_real_adk_workflow():
    graph = compile_architecture(_graph(["a", "b"], [("a", "b")], markers=True), "flow").as_dict()
    source = render_adk_agent("flow", "Answers", graph)
    ast.parse(source)
    namespace = {}
    exec(compile(source, "agent.py", "exec"), namespace)
    assert namespace["root_agent"].name == "flow"
    assert "Workflow(" in source
    assert "google_search" in source


def test_requested_tools_are_wired_to_adk_or_google_cloud_clients():
    architecture = AgentArchitecture.model_validate(
        {
            "nodes": [
                {
                    "id": "kb",
                    "kind": "tool",
                    "tool": "knowledge_retriever",
                    "config": {"knowledge_source_id": "rag"},
                },
                {
                    "id": "sql",
                    "kind": "tool",
                    "tool": "sql_executor",
                    "config": {"knowledge_source_id": "table"},
                },
                {
                    "id": "nosql",
                    "kind": "tool",
                    "tool": "nosql_executor",
                    "config": {"firestore_collection": "customers"},
                },
                {"id": "web", "kind": "tool", "tool": "web_search"},
                {
                    "id": "mail",
                    "kind": "tool",
                    "tool": "email_sender",
                    "config": {"sender_email": "agent@example.com"},
                },
                {
                    "id": "file",
                    "kind": "tool",
                    "tool": "file_reader",
                    "config": {"gcs_bucket": "agent-files"},
                },
                {"id": "code", "kind": "tool", "tool": "code_executor"},
            ],
            "edges": [],
        }
    )
    graph = compile_architecture(architecture, "tools").as_dict()
    source = render_adk_agent(
        "tools",
        "Uses tools",
        graph,
        {
            "kb": {"rag_corpus": "projects/demo/locations/us-central1/ragCorpora/policies"},
            "sql": {"backend": "bigquery", "table_ref": "demo.data.orders"},
        },
    )
    ast.parse(source)
    namespace = {}
    exec(compile(source, "agent.py", "exec"), namespace)
    assert "VertexAiRagRetrieval(" in source
    assert "google.cloud import bigquery" in source
    assert "google.cloud import firestore" in source
    assert "gmail.googleapis.com/gmail/v1/users/me/messages/send" in source
    assert "google.cloud import storage" in source
    assert "BuiltInCodeExecutor()" in source
    assert "CODE_EXECUTOR_MODEL_ID" in source
    assert namespace["root_agent"].name == "tools"


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


async def test_saving_a_draft_stores_the_architecture_and_routed_adk_graph(client):
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
    assert {node["kind"] for node in agent["architecture"]["nodes"]} >= {"start", "end"}
    assert any(
        edge["source"] == "answer" and edge["target"] == "end"
        for edge in agent["architecture"]["edges"]
    )
    assert agent["adk_graph"]["root"]["type"] == "workflow"
    assert "Workflow(" in agent["adk_source"]


async def test_a_looping_canvas_without_a_loop_node_is_refused(client):
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
    assert "cycle not controlled by a Loop" in refused.json()["detail"]
