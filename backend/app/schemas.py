"""Pydantic request/response models and flow-definition validation.

A flow is an ordered list of nodes. Nodes communicate through named variables:
each node reads ``input_var`` and writes ``output_var``. The executor runs nodes in
list order, so a variable must be produced by an earlier node. Exactly one
``output`` node must exist and it must be the last one.
"""

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import get_settings
from app.models import Approval

NodeType = Literal["chat_input", "llm", "retriever", "output"]
VAR_PATTERN = r"^[a-zA-Z_][a-zA-Z0-9_]{0,39}$"


class ChatInputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LlmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system_prompt: str = Field(default="", max_length=4000)


class RetrieverConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,99}$")
    top_k: int = Field(default=4, ge=1, le=20)


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


NODE_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "chat_input": ChatInputConfig,
    "llm": LlmConfig,
    "retriever": RetrieverConfig,
    "output": OutputConfig,
}


class NodeDef(BaseModel):
    id: str = Field(pattern=VAR_PATTERN)
    type: NodeType
    input_var: str | None = Field(default=None, pattern=VAR_PATTERN)
    output_var: str | None = Field(default=None, pattern=VAR_PATTERN)
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_wiring_and_config(self) -> "NodeDef":
        needs_input = self.type in {"llm", "retriever", "output"}
        needs_output = self.type in {"chat_input", "llm", "retriever"}
        if needs_input and not self.input_var:
            raise ValueError(f"node '{self.id}' ({self.type}) requires input_var")
        if self.type == "chat_input" and self.input_var:
            raise ValueError("chat_input reads the run message and takes no input_var")
        if needs_output and not self.output_var:
            raise ValueError(f"node '{self.id}' ({self.type}) requires output_var")
        if self.type == "output" and self.output_var:
            raise ValueError("output nodes do not write a variable")
        NODE_CONFIG_MODELS[self.type].model_validate(self.config)
        return self


class FlowDefinition(BaseModel):
    nodes: list[NodeDef] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _check_graph(self) -> "FlowDefinition":
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("node ids must be unique")

        defined: set[str] = set()
        for node in self.nodes:
            if node.input_var and node.input_var not in defined:
                raise ValueError(f"node '{node.id}' reads '{node.input_var}' before it is produced")
            if node.output_var:
                if node.output_var in defined:
                    raise ValueError(f"variable '{node.output_var}' is written twice")
                defined.add(node.output_var)

        outputs = [i for i, n in enumerate(self.nodes) if n.type == "output"]
        if len(outputs) != 1 or outputs[0] != len(self.nodes) - 1:
            raise ValueError("a flow needs exactly one output node, placed last")
        return self


class FlowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    definition: FlowDefinition


class FlowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    definition: FlowDefinition | None = None


class FlowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    definition: FlowDefinition
    owner_email: str
    created_at: datetime
    updated_at: datetime


class RunCreate(BaseModel):
    message: str = Field(min_length=1, max_length=20000)


class StepTrace(BaseModel):
    node_id: str
    node_type: str
    status: Literal["succeeded", "failed"]
    duration_ms: float
    output_preview: str = ""


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    flow_id: str
    owner_email: str
    status: Literal["queued", "running", "succeeded", "failed"]
    input_message: str
    output: dict[str, Any] | None
    steps: list[StepTrace]
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class DocumentIn(BaseModel):
    source: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=500_000)


class IngestResult(BaseModel):
    collection: str
    source: str
    chunks: int


# --- Agent Canvas -------------------------------------------------------------
# Each canvas tool has its own configuration. There is deliberately no model field:
# the Agent Gateway chooses the model for each prompt.

ToolName = Literal[
    "knowledge_retriever",
    "sql_executor",
    "nosql_executor",
    "no_sql_executor",
    "web_search",
    "email_sender",
    "file_reader",
    "code_executor",
    "mcp_server",
    "base",
    "router",
    "loop",
    "if_else",
    "hitl",
]


class KnowledgeRetrieverConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    knowledge_source_id: str = Field(min_length=1, max_length=36)


class SqlExecutorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    knowledge_source_id: str = Field(min_length=1, max_length=36)


class WebSearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class McpServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mcp_server_id: str = Field(min_length=1, max_length=36)


TOOL_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "knowledge_retriever": KnowledgeRetrieverConfig,
    "sql_executor": SqlExecutorConfig,
    "nosql_executor": SqlExecutorConfig,
    "no_sql_executor": SqlExecutorConfig,
    "web_search": WebSearchConfig,
    "email_sender": WebSearchConfig,
    "file_reader": WebSearchConfig,
    "code_executor": WebSearchConfig,
    "mcp_server": McpServerConfig,
    "base": WebSearchConfig,
    "router": WebSearchConfig,
    "loop": WebSearchConfig,
    "if_else": WebSearchConfig,
    "hitl": WebSearchConfig,
}


class WorkflowNode(BaseModel):
    # extra="forbid" makes a client-supplied "model" field an error, not a silent no-op.
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=VAR_PATTERN)
    tool: ToolName
    system_prompt: str = Field(default="", max_length=4000)
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_config(self) -> "WorkflowNode":
        TOOL_CONFIG_MODELS[self.tool].model_validate(self.config)
        return self


class AgentWorkflow(BaseModel):
    nodes: list[WorkflowNode] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _check_unique_ids(self) -> "AgentWorkflow":
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("tool node ids must be unique")
        return self


class ArchitecturePosition(BaseModel):
    x: float = 0
    y: float = 0


class ArchitectureNode(BaseModel):
    """A canvas node. ``start`` and ``end`` mark the flow's ends. ``tool`` is an agent."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=VAR_PATTERN)
    kind: Literal["start", "end", "tool"]
    position: ArchitecturePosition = Field(default_factory=ArchitecturePosition)
    tool: ToolName | None = None
    system_prompt: str = Field(default="", max_length=4000)
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_kind(self) -> "ArchitectureNode":
        if self.kind == "tool":
            if self.tool is None:
                raise ValueError(f"{self.id}: a tool node needs a tool")
            TOOL_CONFIG_MODELS[self.tool].model_validate(self.config)
        elif self.tool is not None or self.config or self.system_prompt:
            raise ValueError(f"{self.id}: start and end nodes take no tool, prompt or config")
        return self


class ArchitectureEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=40)
    target: str = Field(min_length=1, max_length=40)


class AgentArchitecture(BaseModel):
    """The canvas graph: nodes with positions, and the edges that connect them."""

    nodes: list[ArchitectureNode] = Field(min_length=1, max_length=40)
    edges: list[ArchitectureEdge] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def _check_graph(self) -> "AgentArchitecture":
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("node ids must be unique")
        if sum(n.kind == "tool" for n in self.nodes) == 0:
            raise ValueError("the architecture needs at least one tool node")
        if sum(n.kind == "tool" for n in self.nodes) > 20:
            raise ValueError("at most 20 tool nodes")
        for kind in ("start", "end"):
            if sum(n.kind == kind for n in self.nodes) > 1:
                raise ValueError(f"at most one {kind} node")
        known = set(ids)
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError(f"edge {edge.id} connects a node that is not on the canvas")
            if edge.source == edge.target:
                raise ValueError(f"edge {edge.id} connects a node to itself")
        return self


AGENT_NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]{2,63}$"


class AgentCreate(BaseModel):
    name: str = Field(pattern=AGENT_NAME_PATTERN)
    description: str = Field(min_length=1, max_length=2000)
    # The canvas graph. Older clients send only ``workflow``, a plain chain of tools.
    architecture: AgentArchitecture | None = None
    workflow: AgentWorkflow | None = None
    guardrail_template_id: str | None = Field(default=None, max_length=36)

    @model_validator(mode="after")
    def _need_a_graph(self) -> "AgentCreate":
        if self.architecture is None and self.workflow is None:
            raise ValueError("send the canvas architecture")
        return self


class AgentUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    architecture: AgentArchitecture | None = None
    workflow: AgentWorkflow | None = None
    guardrail_template_id: str | None = Field(default=None, max_length=36)


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    workflow: AgentWorkflow
    architecture: AgentArchitecture | None = None
    adk_graph: dict[str, Any] | None = None
    adk_source: str
    guardrail_template_id: str | None
    status: Literal["draft", "in_review", "approved", "rejected", "deployed"]
    owner_email: str
    created_at: datetime
    updated_at: datetime


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=2000)


class ApprovalOut(BaseModel):
    id: str
    agent_id: str
    agent_name: str
    requested_by: str
    approver_group: str
    status: Literal["pending", "approved", "rejected"]
    decided_by: str | None
    decision_comment: str
    created_at: datetime
    decided_at: datetime | None

    @classmethod
    def build(cls, approval: "Approval", agent_name: str) -> "ApprovalOut":
        return cls(
            id=approval.id,
            agent_id=approval.agent_id,
            agent_name=agent_name,
            requested_by=approval.requested_by,
            approver_group=approval.approver_group,
            status=approval.status,
            decided_by=approval.decided_by,
            decision_comment=approval.decision_comment,
            created_at=approval.created_at,
            decided_at=approval.decided_at,
        )


# --- Knowledge Studio ----------------------------------------------------------

RAG_CORPUS_PATTERN = r"^projects/[^/]+/locations/[^/]+/ragCorpora/[^/]+$"


class KnowledgeSourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    kind: Literal["structured", "unstructured"]
    config: dict[str, Any]

    @model_validator(mode="after")
    def _check_config(self) -> "KnowledgeSourceIn":
        if self.kind == "structured":
            StructuredSourceConfig.model_validate(self.config)
        else:
            UnstructuredSourceConfig.model_validate(self.config)
        return self


class StructuredSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: Literal["bigquery", "cloud_sql"]
    table_ref: str = Field(min_length=1, max_length=300)


class UnstructuredSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rag_corpus: str = Field(pattern=RAG_CORPUS_PATTERN, max_length=300)


class KnowledgeSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    kind: Literal["structured", "unstructured"]
    config: dict[str, Any]
    owner_email: str
    created_at: datetime


# --- Guardrails Studio ---------------------------------------------------------


class CustomInfoType(BaseModel):
    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    regex: str = Field(min_length=1, max_length=500)

    @field_validator("regex")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
        return value


class GuardrailIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Model Armor and Sensitive Data Protection can be combined in one template.
    providers: list[Literal["model_armor", "sdp"]] = Field(min_length=1, max_length=2)
    protections: list[Literal["prompt_injection", "jailbreak"]] = Field(
        default_factory=list, max_length=2
    )
    info_types: list[str] = Field(default_factory=list, max_length=50)
    custom_infotypes: list[CustomInfoType] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _check_provider_fields(self) -> "GuardrailIn":
        if len(self.providers) != len(set(self.providers)):
            raise ValueError("providers must not repeat")
        if len(self.protections) != len(set(self.protections)):
            raise ValueError("protections must not repeat")

        has_infotypes = bool(self.info_types or self.custom_infotypes)
        if "model_armor" in self.providers and not self.protections:
            raise ValueError("Model Armor needs at least one protection")
        if "model_armor" not in self.providers and self.protections:
            raise ValueError("Protections need Model Armor turned on")
        if "sdp" in self.providers and not has_infotypes:
            raise ValueError("Sensitive Data Protection needs at least one infotype")
        if "sdp" not in self.providers and has_infotypes:
            raise ValueError("Infotypes need Sensitive Data Protection turned on")
        return self


class GuardrailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    providers: list[Literal["model_armor", "sdp"]]
    config: dict[str, Any]
    is_default: bool
    owner_email: str
    created_at: datetime


# --- MCP Client ----------------------------------------------------------------

AuthType = Literal["none", "google_id_token", "bearer_token", "api_key_header"]
SECRET_RESOURCE_PATTERN = r"^projects/[^/]+/secrets/[^/]+(/versions/[^/]+)?$"
HEADER_NAME_PATTERN = r"^[A-Za-z0-9-]{1,64}$"


# --- Users and roles ------------------------------------------------------------

Role = Literal["platform_admin", "platform_user"]


class MeOut(BaseModel):
    email: str
    role: Role


class UserIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)
    role: Role


class RoleUpdate(BaseModel):
    role: Role


class UserOut(BaseModel):
    email: str
    role: Role
    # True when the admin list in the server settings sets this role. The UI cannot change it.
    managed_by_config: bool
    created_at: datetime | None


class McpServerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    endpoint_url: str = Field(min_length=8, max_length=2000)
    auth_type: AuthType = "none"
    # Only for api_key_header: the header to send the key in.
    header_name: str | None = Field(default=None, pattern=HEADER_NAME_PATTERN)
    # Only for bearer_token and api_key_header: a Secret Manager secret, never the value.
    secret_name: str | None = Field(default=None, pattern=SECRET_RESOURCE_PATTERN)

    @field_validator("endpoint_url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        if value.startswith("https://"):
            return value
        # Plain http is allowed for a server on this machine, outside production only.
        local = value.startswith(("http://localhost", "http://127.0.0.1"))
        if local and get_settings().app_env != "production":
            return value
        raise ValueError("The endpoint must use https://")

    @model_validator(mode="after")
    def _check_auth_fields(self) -> "McpServerIn":
        needs_secret = self.auth_type in ("bearer_token", "api_key_header")
        if needs_secret and not self.secret_name:
            raise ValueError("Choose the Secret Manager secret that holds the credential")
        if not needs_secret and self.secret_name:
            raise ValueError("This authentication type does not use a secret")
        if self.auth_type == "api_key_header" and not self.header_name:
            raise ValueError("Enter the header name the key is sent in")
        if self.auth_type != "api_key_header" and self.header_name:
            raise ValueError("Only the API key header type takes a header name")
        return self

    def auth_config(self) -> dict[str, str]:
        if self.auth_type == "api_key_header":
            return {"header_name": self.header_name or "", "secret_name": self.secret_name or ""}
        if self.auth_type == "bearer_token":
            return {"secret_name": self.secret_name or ""}
        return {}


class McpToolOut(BaseModel):
    name: str
    description: str


class McpServerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    endpoint_url: str
    auth_type: AuthType
    auth_config: dict[str, str]
    tools: list[McpToolOut]
    status: Literal["draft", "connected", "error"]
    last_error: str
    owner_email: str
    created_at: datetime


# --- Deployment ----------------------------------------------------------------


class DeploymentIn(BaseModel):
    target: Literal["cloud_run", "agent_engine"]
    session_backend: Literal["vertex_ai_session", "in_memory"] = "vertex_ai_session"
    memory_backend: Literal["vertex_ai_memory_bank", "none"] = "vertex_ai_memory_bank"


class DeploymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    target: Literal["cloud_run", "agent_engine"]
    session_backend: str
    memory_backend: str
    status: Literal["queued", "running", "succeeded", "failed"]
    endpoint_url: str | None
    agent_identity: str | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None
