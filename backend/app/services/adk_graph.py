"""Compile Agent Canvas architectures into routed Google ADK workflows."""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from app.schemas import AgentArchitecture, AgentWorkflow, ArchitecturePosition

ROUTED_TOOLS = {"router", "if_else", "loop", "hitl"}


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
        return {"version": 2, "root": self.root, "order": self.order}


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


def _route_labels(node_id: str, edges: list[Any]) -> list[str]:
    labels = [edge.route for edge in edges if edge.source == node_id]
    if any(label is None for label in labels):
        raise ArchitectureError([f"'{node_id}' needs a route label on every outgoing connection"])
    cleaned = [label.strip() for label in labels if label is not None]
    if len(cleaned) != len(set(cleaned)):
        raise ArchitectureError([f"'{node_id}' has duplicate route labels"])
    return cleaned


def _validate_routes(nodes: dict[str, Any], edges: list[Any]) -> None:
    for node in nodes.values():
        if node.tool not in ROUTED_TOOLS:
            if any(edge.route is not None for edge in edges if edge.source == node.id):
                raise ArchitectureError([f"'{node.id}' does not support labeled connections"])
            continue

        labels = _route_labels(node.id, edges)
        if node.tool in {"router", "hitl"} and len(labels) < 2:
            raise ArchitectureError([f"'{node.id}' needs at least two labeled outgoing paths"])
        if node.tool == "if_else" and set(labels) != {"true", "false"}:
            raise ArchitectureError(
                [f"'{node.id}' needs outgoing paths labeled 'true' and 'false'"]
            )
        if node.tool == "loop" and set(labels) != {"continue", "exit"}:
            raise ArchitectureError(
                [f"'{node.id}' needs outgoing paths labeled 'continue' and 'exit'"]
            )


def _topological_order(nodes: dict[str, Any], edges: list[Any]) -> list[str]:
    """Allow cycles only when a Loop's ``continue`` route breaks them."""
    validation_successors: dict[str, list[str]] = defaultdict(list)
    validation_indegree = {node_id: 0 for node_id in nodes}
    for edge in edges:
        if edge.source not in nodes or edge.target not in nodes:
            continue
        if nodes[edge.source].tool == "loop" and edge.route and edge.route.lower() == "continue":
            continue
        validation_successors[edge.source].append(edge.target)
        validation_indegree[edge.target] += 1

    validation_queue = deque(node_id for node_id in nodes if validation_indegree[node_id] == 0)
    visited: set[str] = set()
    while validation_queue:
        current = validation_queue.popleft()
        visited.add(current)
        for target in validation_successors[current]:
            validation_indegree[target] -= 1
            if validation_indegree[target] == 0:
                validation_queue.append(target)
    if len(visited) != len(nodes):
        stuck = sorted(node_id for node_id in nodes if node_id not in visited)
        raise ArchitectureError(
            [f"The flow contains a cycle not controlled by a Loop node: {', '.join(stuck)}"]
        )

    successors: dict[str, list[str]] = defaultdict(list)
    indegree = {node_id: 0 for node_id in nodes}
    for edge in edges:
        if edge.source not in nodes or edge.target not in nodes:
            continue
        if nodes[edge.target].tool == "loop":
            continue
        successors[edge.source].append(edge.target)
        indegree[edge.target] += 1
    queue = deque(node_id for node_id in nodes if indegree[node_id] == 0)
    result: list[str] = []
    while queue:
        current = queue.popleft()
        result.append(current)
        for target in successors[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    return result


def compile_architecture(architecture: AgentArchitecture, agent_name: str) -> CompiledGraph:
    tools = {node.id: node for node in architecture.nodes if node.kind == "tool"}
    edges = architecture.edges
    _validate_routes(tools, edges)
    order = _topological_order(tools, edges)
    start_ids = {node.id for node in architecture.nodes if node.kind == "start"}
    entry_nodes = [
        edge.target for edge in edges if edge.source in start_ids and edge.target in tools
    ]
    if not entry_nodes:
        entry_nodes = [
            node_id
            for node_id in order
            if not any(edge.target == node_id and edge.source in tools for edge in edges)
        ]

    predecessors: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.source in tools and edge.target in tools:
            predecessors[edge.target].append(edge.source)

    specs: list[dict[str, Any]] = []
    compiled_edges: list[dict[str, Any]] = []
    for node_id in order:
        node = tools[node_id]
        options = _route_labels(node_id, edges) if node.tool in ROUTED_TOOLS else []
        instruction = node.system_prompt.strip()
        if predecessors[node_id]:
            reads = "\n".join(f"{{{pred}?}}" for pred in predecessors[node_id])
            instruction = f"{instruction}\n\nInputs from connected steps:\n{reads}".strip()

        spec: dict[str, Any] = {
            "type": "hitl" if node.tool == "hitl" else "agent",
            "name": node_id,
            "tool": node.tool,
            "config": node.config,
            "instruction": instruction,
            "output_key": node_id,
            "reads": predecessors[node_id],
            "routes": options,
        }
        if node.tool in {"router", "if_else", "loop"}:
            spec["selector"] = f"{node_id}_route"
            compiled_edges.append({"source": node_id, "target": spec["selector"], "route": None})
        specs.append(spec)

    for edge in edges:
        if edge.source not in tools:
            continue
        source = (
            f"{edge.source}_route"
            if tools[edge.source].tool in {"router", "if_else", "loop"}
            else edge.source
        )
        target = edge.target if edge.target in tools else "canvas_end"
        compiled_edges.append({"source": source, "target": target, "route": edge.route})

    if any(edge["target"] == "canvas_end" for edge in compiled_edges):
        specs.append({"type": "terminal", "name": "canvas_end"})

    root = {
        "type": "workflow",
        "name": agent_name,
        "nodes": specs,
        "edges": compiled_edges,
        "entry_nodes": entry_nodes,
    }
    return CompiledGraph(root=root, order=order)
