"""Renders a compiled agent graph as Google ADK source code.

The source is generated from the graph in ``services/adk_graph.py``, and it is saved with the agent.
The Cloud Build step packages it unchanged when the agent is deployed. Tools that are not wired to
ADK yet are written as comments, so the generated file is always valid Python.
"""

import re
from typing import Any

GATEWAY_MODEL_ID = "agent-gateway"  # the Agent Gateway picks the Gemini model per prompt


def identifier(name: str) -> str:
    """A safe Python and ADK name: letters, digits and underscores, not starting with a digit."""
    cleaned = re.sub(r"\W", "_", name)
    return cleaned if not cleaned[:1].isdigit() else f"_{cleaned}"


def _tool_lines(spec: dict[str, Any], imports: set[str]) -> list[str]:
    tool = spec["tool"]
    if tool == "web_search":
        imports.add("from google.adk.tools import google_search")
        return ["        google_search,"]
    if tool == "knowledge_retriever":
        # The corpus name is resolved at deploy time from knowledge_source_id.
        imports.add("from google.adk.tools import VertexAiRagRetrieval")
        source = spec["config"].get("knowledge_source_id")
        return [f"        # VertexAiRagRetrieval for knowledge source {source} (at deploy)"]
    if tool in {"sql_executor", "nosql_executor", "no_sql_executor", "email_sender", "file_reader", "code_executor", "base", "router", "loop", "if_else", "hitl"}:
        return [f"        # {tool} is not wired to ADK yet (config: {spec['config']})"]
    return [f"        # {tool} is not wired to ADK yet (config: {spec['config']})"]


def _render_agent(spec: dict[str, Any], imports: set[str], name: str) -> list[str]:
    """One LlmAgent definition, as Python lines bound to ``name``."""
    lines = [
        f"{name} = LlmAgent(",
        f"    name={identifier(spec['name'])!r},",
        "    model=GATEWAY_MODEL_ID,",
        f"    instruction={spec['instruction']!r},",
        f"    output_key={spec['output_key']!r},",
        "    tools=[",
        *_tool_lines(spec, imports),
        "    ],",
        ")",
    ]
    return lines


def _render_node(
    spec: dict[str, Any], imports: set[str], out: list[str], counter: list[int]
) -> str:
    """Emits a node (agent or composite) and returns the variable that holds it."""
    if spec["type"] == "llm":
        counter[0] += 1
        variable = identifier(spec["name"])
        out.extend(_render_agent(spec, imports, variable))
        return variable

    children = [_render_node(child, imports, out, counter) for child in spec["sub_agents"]]
    counter[0] += 1
    variable = f"group_{counter[0]}"
    cls = "ParallelAgent" if spec["type"] == "parallel" else "SequentialAgent"
    out.append(f"{variable} = {cls}(")
    out.append(f"    name={identifier(spec['name'])!r},")
    out.append(f"    sub_agents=[{', '.join(children)}],")
    out.append(")")
    return variable


def render_adk_agent(name: str, description: str, graph: dict[str, Any]) -> str:
    imports: set[str] = {"from google.adk.agents import LlmAgent"}
    body: list[str] = []
    if graph["root"]["type"] in ("parallel", "sequential"):
        imports.add("from google.adk.agents import ParallelAgent, SequentialAgent")
    root_var = _render_node(graph["root"], imports, body, [0])
    lines = [
        '"""Generated from the Agent Canvas. Edit the canvas, not this file."""',
        "",
        *sorted(imports),
        "",
        f"GATEWAY_MODEL_ID = {GATEWAY_MODEL_ID!r}",
        f"AGENT_DESCRIPTION = {description!r}",
        "",
        *body,
        "",
        f"root_agent = {root_var}",
        "",
    ]
    return "\n".join(lines)
