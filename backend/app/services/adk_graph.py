"""Compiles an agent architecture (canvas nodes and edges) into an ADK agent graph.

Rules, following the Tiger AgentFlow canvas:

* ``start`` and ``end`` nodes mark where the flow begins and ends. They are not agents, and edges
  that touch them do not add dependencies between agents.
* Each tool node is one ``LlmAgent`` with its tool and its system prompt.
* The level of a node is the longest path from an entry node to it. Entry nodes are level 0.
  Nodes in the same level run together in a ``ParallelAgent``. Levels run in order in a
  ``SequentialAgent``. A node therefore starts only after every node in an earlier level has
  finished, which keeps every edge's order.
* Each agent writes its reply to session state under its own node id. An agent reads the replies
  of its direct predecessors through ``{id?}`` placeholders in its instruction.
* Cycles are rejected.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.schemas import AgentArchitecture, AgentWorkflow, ArchitecturePosition


class ArchitectureError(ValueError):
    """The canvas graph cannot be compiled. ``messages`` are safe to show the user."""

    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = messages


@dataclass
class CompiledGraph:
    root: dict[str, Any]
    order: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"version": 1, "root": self.root, "order": self.order}


def architecture_from_workflow(workflow: AgentWorkflow) -> AgentArchitecture:
    """A plain tool chain, as older clients send it, becomes a graph with one edge per step."""
    from app.schemas import ArchitectureEdge, ArchitectureNode

    nodes = [
        ArchitectureNode(
            id=node.id,
            kind="tool",
            position=ArchitecturePosition(x=120 + index * 260, y=160),
            tool=node.tool,
            system_prompt=node.system_prompt,
            config=node.config,
        )
        for index, node in enumerate(workflow.nodes)
    ]
    edges = [
        ArchitectureEdge(id=f"e_{a.id}_{b.id}", source=a.id, target=b.id)
        for a, b in zip(workflow.nodes, workflow.nodes[1:], strict=False)
    ]
    return AgentArchitecture(nodes=nodes, edges=edges)


def _agent_spec(node, predecessors: list[str]) -> dict[str, Any]:
    instruction = node.system_prompt.strip()
    if predecessors:
        reads = "\n".join(f"{{{pred}?}}" for pred in predecessors)
        instruction = f"{instruction}\n\nInputs from earlier steps:\n{reads}".strip()
    return {
        "type": "llm",
        "name": node.id,
        "tool": node.tool,
        "config": node.config,
        "instruction": instruction,
        "output_key": node.id,
        "reads": predecessors,
    }


def compile_architecture(architecture: AgentArchitecture, agent_name: str) -> CompiledGraph:
    tools = {node.id: node for node in architecture.nodes if node.kind == "tool"}
    preds: dict[str, list[str]] = defaultdict(list)
    succs: dict[str, list[str]] = defaultdict(list)
    for edge in architecture.edges:
        if edge.source in tools and edge.target in tools:
            preds[edge.target].append(edge.source)
            succs[edge.source].append(edge.target)

    # Kahn's algorithm: nodes that never reach indegree 0 sit on a cycle.
    indegree = {tid: len(preds[tid]) for tid in tools}
    queue = [tid for tid in tools if indegree[tid] == 0]
    topo: list[str] = []
    while queue:
        current = queue.pop(0)
        topo.append(current)
        for nxt in succs[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if len(topo) != len(tools):
        stuck = sorted(tid for tid in tools if tid not in topo)
        raise ArchitectureError([f"The flow loops back on itself through: {', '.join(stuck)}"])

    level: dict[str, int] = {}
    for tid in topo:
        level[tid] = 1 + max((level[p] for p in preds[tid]), default=-1)

    by_level: dict[int, list[str]] = defaultdict(list)
    for node in architecture.nodes:  # keep the canvas order inside a level
        if node.kind == "tool" and node.id in level:
            by_level[level[node.id]].append(node.id)

    steps: list[dict[str, Any]] = []
    for lvl in sorted(by_level):
        members = [_agent_spec(tools[tid], preds[tid]) for tid in by_level[lvl]]
        if len(members) == 1:
            steps.append(members[0])
        else:
            steps.append(
                {"type": "parallel", "name": f"{agent_name}_level_{lvl}", "sub_agents": members}
            )

    if len(steps) == 1:
        root = steps[0]
        root["name"] = agent_name
    else:
        root = {"type": "sequential", "name": agent_name, "sub_agents": steps}
    return CompiledGraph(root=root, order=topo)
