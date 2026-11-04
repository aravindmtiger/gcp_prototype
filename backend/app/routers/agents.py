"""Agent Studio and Agent Canvas: save agent drafts and submit them for approval."""

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.deps import Builder, DbSession, User
from app.errors import AppError
from app.models import AgentDraft, Approval, KnowledgeSource, McpServer
from app.schemas import (
    AgentArchitecture,
    AgentCreate,
    AgentOut,
    AgentUpdate,
    AgentWorkflow,
    ApprovalOut,
)
from app.services.adk_draft import identifier, render_adk_agent
from app.services.adk_graph import (
    ArchitectureError,
    architecture_from_workflow,
    compile_architecture,
)
from app.services.resources import default_guardrail, get_owned, get_visible_guardrail

router = APIRouter(prefix="/api/v1", tags=["agents"])

# Every submitted agent goes to the admins. Shown as the reviewer on each approval.
APPROVER_LABEL = "admins"

# Tools available on the canvas. Users cannot pick a model; the Agent Gateway does that.
TOOL_CATALOG = [
    {
        "id": "knowledge_retriever",
        "label": "Knowledge retriever",
        "description": "Retrieves data from a RAG corpus created in the Knowledge Studio.",
        "config": ["knowledge_source_id"],
    },
    {
        "id": "sql_executor",
        "label": "SQL executor",
        "description": "Runs text-to-SQL against a structured table from the Knowledge Studio.",
        "config": ["knowledge_source_id"],
    },
    {
        "id": "nosql_executor",
        "label": "NoSQL executor",
        "description": "Runs document-store or collection-style queries against a NoSQL backend.",
        "config": ["knowledge_source_id"],
    },
    {
        "id": "web_search",
        "label": "Web search",
        "description": "Performs an external web search for current information.",
        "config": [],
    },
    {
        "id": "email_sender",
        "label": "Email sender",
        "description": "Sends email notifications or outbound messages from the workflow.",
        "config": [],
    },
    {
        "id": "file_reader",
        "label": "File reader",
        "description": "Reads files and extracts structured or unstructured content.",
        "config": [],
    },
    {
        "id": "code_executor",
        "label": "Code executor",
        "description": "Executes a code snippet or script in the sandboxed runtime.",
        "config": [],
    },
    {
        "id": "mcp_server",
        "label": "MCP server",
        "description": "Calls the tools of an MCP server from the MCP Studio.",
        "config": ["mcp_server_id"],
    },
    {
        "id": "base",
        "label": "Base",
        "description": "Baseline agent node used as a standard task step in the canvas.",
        "config": [],
    },
    {
        "id": "router",
        "label": "Router",
        "description": "Routes execution to one of several downstream paths based on logic.",
        "config": [],
    },
    {
        "id": "loop",
        "label": "Loop",
        "description": "Repeats a task until a stop condition is met.",
        "config": [],
    },
    {
        "id": "if_else",
        "label": "If Else",
        "description": "Evaluates a branch condition and chooses the next path.",
        "config": [],
    },
    {
        "id": "hitl",
        "label": "HITL",
        "description": "Stops for human input before continuing the workflow.",
        "config": [],
    },
]

EDITABLE_STATUSES = {"draft", "rejected"}


@router.get("/tools")
async def list_tools() -> list[dict]:
    return TOOL_CATALOG


async def _check_references(session: DbSession, user: User, workflow: AgentWorkflow) -> None:
    """Every tool must point at a resource the user owns, of the right kind."""
    for node in workflow.nodes:
        if node.tool == "knowledge_retriever":
            source = await get_owned(
                session,
                KnowledgeSource,
                user,
                node.config["knowledge_source_id"],
                "Knowledge source",
            )
            if source.kind != "unstructured":
                raise AppError(
                    422, f"'{node.id}': knowledge retriever needs an unstructured source"
                )
        elif node.tool in {"sql_executor", "nosql_executor", "no_sql_executor"}:
            source = await get_owned(
                session,
                KnowledgeSource,
                user,
                node.config["knowledge_source_id"],
                "Knowledge source",
            )
            if source.kind != "structured":
                raise AppError(422, f"'{node.id}': data executor needs a structured source")
        elif node.tool == "mcp_server":
            await get_owned(session, McpServer, user, node.config["mcp_server_id"], "MCP server")


async def _ensure_unique_name(session: DbSession, name: str, agent_id: str | None = None) -> None:
    statement = select(AgentDraft.id).where(AgentDraft.name == name)
    existing = (await session.execute(statement)).scalars().all()
    if any(found != agent_id for found in existing):
        raise AppError(409, f"An agent named '{name}' already exists. Choose another name.")


@router.get("/agents/name-check")
async def check_agent_name(
    session: DbSession, user: User, name: str = Query(min_length=1, max_length=64)
) -> dict:
    """Whether an agent name is still free. The canvas calls this as the name is typed."""
    taken = await session.execute(select(AgentDraft.id).where(AgentDraft.name == name))
    return {"name": name, "available": taken.first() is None}


@router.get("/agents", response_model=list[AgentOut])
async def list_agents(session: DbSession, user: User) -> list[AgentDraft]:
    statement = select(AgentDraft).order_by(AgentDraft.updated_at.desc())
    if not user.is_admin:
        statement = statement.where(AgentDraft.owner_email == user.email)
    return list((await session.execute(statement)).scalars().all())


def _compile(name: str, description: str, architecture: AgentArchitecture) -> dict:
    """Compiles the canvas into an ADK graph and renders the source. Invalid graphs are a 422."""
    try:
        compiled = compile_architecture(architecture, identifier(name))
    except ArchitectureError as exc:
        raise AppError(422, " ".join(exc.messages)) from exc
    return {
        "adk_graph": compiled.as_dict(),
        "adk_source": render_adk_agent(name, description, compiled.as_dict()),
        "workflow": _workflow_in_order(architecture, compiled.order),
    }


def _workflow_in_order(architecture: AgentArchitecture, order: list[str]) -> dict:
    """The tool nodes in run order, in the shape the rest of the platform reads (``workflow``)."""
    tools = {n.id: n for n in architecture.nodes if n.kind == "tool"}
    nodes = [
        {
            "id": tid,
            "tool": tools[tid].tool,
            "system_prompt": tools[tid].system_prompt,
            "config": tools[tid].config,
        }
        for tid in order
    ]
    return {"nodes": nodes}


def _architecture_for(payload_architecture, payload_workflow) -> AgentArchitecture:
    if payload_architecture is not None:
        return payload_architecture
    return architecture_from_workflow(payload_workflow)


@router.post("/agents", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(payload: AgentCreate, session: DbSession, user: Builder) -> AgentDraft:
    architecture = _architecture_for(payload.architecture, payload.workflow)
    compiled = _compile(payload.name, payload.description, architecture)
    await _check_references(session, user, AgentWorkflow.model_validate(compiled["workflow"]))
    if payload.guardrail_template_id:
        await get_visible_guardrail(session, user, payload.guardrail_template_id)
    await _ensure_unique_name(session, payload.name)

    agent = AgentDraft(
        owner_email=user.email,
        name=payload.name,
        description=payload.description,
        workflow=compiled["workflow"],
        architecture=architecture.model_dump(),
        adk_graph=compiled["adk_graph"],
        adk_source=compiled["adk_source"],
        guardrail_template_id=payload.guardrail_template_id,
        status="draft",
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


@router.get("/agents/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: str, session: DbSession, user: User) -> AgentDraft:
    return await get_owned(session, AgentDraft, user, agent_id, "Agent")


@router.put("/agents/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: str, payload: AgentUpdate, session: DbSession, user: Builder
) -> AgentDraft:
    agent = await get_owned(session, AgentDraft, user, agent_id, "Agent")
    if agent.status not in EDITABLE_STATUSES:
        raise AppError(409, f"An agent in status '{agent.status}' cannot be edited")

    if payload.architecture is None and payload.workflow is None:
        architecture = agent.architecture or architecture_from_workflow(
            AgentWorkflow.model_validate(agent.workflow)
        )
        architecture = AgentArchitecture.model_validate(architecture)
    else:
        architecture = _architecture_for(payload.architecture, payload.workflow)
    description = payload.description if payload.description is not None else agent.description
    compiled = _compile(agent.name, description, architecture)
    await _check_references(session, user, AgentWorkflow.model_validate(compiled["workflow"]))
    if payload.guardrail_template_id:
        await get_visible_guardrail(session, user, payload.guardrail_template_id)

    agent.description = description
    agent.architecture = architecture.model_dump()
    agent.workflow = compiled["workflow"]
    agent.adk_graph = compiled["adk_graph"]
    agent.adk_source = compiled["adk_source"]
    if payload.guardrail_template_id is not None:
        agent.guardrail_template_id = payload.guardrail_template_id
    await session.commit()
    await session.refresh(agent)
    return agent


@router.post(
    "/agents/{agent_id}/submit", response_model=ApprovalOut, status_code=status.HTTP_201_CREATED
)
async def submit_for_review(agent_id: str, session: DbSession, user: Builder) -> ApprovalOut:
    agent = await get_owned(session, AgentDraft, user, agent_id, "Agent")
    if agent.status not in EDITABLE_STATUSES:
        raise AppError(409, f"An agent in status '{agent.status}' cannot be submitted")

    # Agents that did not pick a guardrail get the default one, stored on the agent.
    if agent.guardrail_template_id is None:
        agent.guardrail_template_id = (await default_guardrail(session)).id

    approval = Approval(
        agent_id=agent.id,
        requested_by=user.email,
        approver_group=APPROVER_LABEL,
        status="pending",
    )
    agent.status = "in_review"
    session.add(approval)
    await session.commit()
    await session.refresh(approval)
    return ApprovalOut.build(approval, agent.name)
