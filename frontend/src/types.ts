// Mirrors backend/app/schemas.py. Keep the two in sync when the API changes.

export type Role = 'platform_admin' | 'platform_user';

export interface Me {
  email: string;
  role: Role;
}

export interface AppUser {
  email: string;
  role: Role;
  managed_by_config: boolean;
  created_at: string | null;
}

export type NodeType = 'chat_input' | 'llm' | 'retriever' | 'output';

// --- Studios (mirrors the agent, knowledge, guardrail, MCP and deployment schemas) ---

export type ToolId =
  | 'knowledge_retriever'
  | 'sql_executor'
  | 'nosql_executor'
  | 'no_sql_executor'
  | 'web_search'
  | 'email_sender'
  | 'file_reader'
  | 'code_executor'
  | 'mcp_server'
  | 'base'
  | 'router'
  | 'loop'
  | 'if_else'
  | 'hitl';

export interface ToolInfo {
  id: ToolId;
  label: string;
  description: string;
  config: string[];
}

export interface WorkflowNode {
  id: string;
  tool: ToolId;
  system_prompt: string;
  config: Record<string, string>;
}

export interface AgentWorkflow {
  nodes: WorkflowNode[];
}

/** A canvas node. start and end mark where the flow begins and ends. tool nodes are agents. */
export interface ArchitectureNode {
  id: string;
  kind: 'start' | 'end' | 'tool';
  position: { x: number; y: number };
  tool?: ToolId | null;
  system_prompt?: string;
  config?: Record<string, string>;
}

export interface ArchitectureEdge {
  id: string;
  source: string;
  target: string;
  route?: string | null;
}

/** The canvas graph as the backend stores it. */
export interface AgentArchitecture {
  nodes: ArchitectureNode[];
  edges: ArchitectureEdge[];
}

export type AgentStatus = 'draft' | 'in_review' | 'approved' | 'rejected' | 'deployed';

export interface Agent {
  id: string;
  name: string;
  description: string;
  workflow: AgentWorkflow;
  architecture: AgentArchitecture | null;
  adk_graph: Record<string, unknown> | null;
  adk_source: string;
  guardrail_template_id: string | null;
  status: AgentStatus;
  owner_email: string;
  created_at: string;
  updated_at: string;
}

export interface AgentInput {
  name: string;
  description: string;
  architecture: AgentArchitecture;
  guardrail_template_id: string | null;
}

export type ApprovalStatus = 'pending' | 'approved' | 'rejected';

export interface Approval {
  id: string;
  agent_id: string;
  agent_name: string;
  requested_by: string;
  approver_group: string;
  status: ApprovalStatus;
  decided_by: string | null;
  decision_comment: string;
  created_at: string;
  decided_at: string | null;
}

export interface KnowledgeSource {
  id: string;
  name: string;
  description: string;
  kind: 'structured' | 'unstructured';
  config: Record<string, string>;
  owner_email: string;
  created_at: string;
}

export interface CustomInfoType {
  name: string;
  regex: string;
}

export type GuardrailProvider = 'model_armor' | 'sdp';

export interface GuardrailTemplate {
  id: string;
  name: string;
  providers: GuardrailProvider[];
  config: {
    protections?: ('prompt_injection' | 'jailbreak')[];
    info_types?: string[];
    custom_infotypes?: CustomInfoType[];
  };
  is_default: boolean;
  owner_email: string;
  created_at: string;
}

export interface McpTool {
  name: string;
  description: string;
}

export type McpAuthType = 'none' | 'google_id_token' | 'bearer_token' | 'api_key_header';

export interface McpServer {
  id: string;
  name: string;
  description: string;
  endpoint_url: string;
  auth_type: McpAuthType;
  auth_config: Record<string, string>;
  tools: McpTool[];
  status: 'draft' | 'connected' | 'error';
  last_error: string;
  owner_email: string;
  created_at: string;
}

export interface McpServerInput {
  name: string;
  description: string;
  endpoint_url: string;
  auth_type: McpAuthType;
  header_name?: string;
  secret_name?: string;
}

export type DeployTarget = 'cloud_run' | 'agent_engine';

export interface Deployment {
  id: string;
  agent_id: string;
  target: DeployTarget;
  session_backend: string;
  memory_backend: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  endpoint_url: string | null;
  agent_identity: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

/** Reply from the Agent Gateway. The model is chosen by the platform, never by the user. */
export interface PromptReply {
  text: string;
  model: string;
  complexity: string;
  screened: boolean;
}

// --- Google Cloud resources and observability (mirror backend/app/routers/gcp.py etc.) ---

export interface GcpEndpoint {
  name: string;
  location: string;
  uri: string;
}

export interface RagCorpus {
  name: string;
  display_name: string;
}

export interface BigQueryTable {
  table_ref: string;
  type: string;
}

export interface EvalMetric {
  key: string;
  label: string;
  description: string;
  requires: 'expected_response' | 'expected_tools' | 'rubrics' | 'none';
  default_threshold: number;
}

export interface TraceSummaryRow {
  trace_id: string;
  root_name: string;
  service_name: string;
  started_at: string;
  duration_ms: number;
  span_count: number;
  has_error: boolean;
}

export interface TraceSpan {
  span_id: string;
  parent_span_id: string | null;
  name: string;
  service_name: string;
  kind: string;
  status_code: 'ok' | 'error' | 'unset';
  start_time: string;
  end_time: string;
  duration_ms: number;
  attributes: Record<string, unknown>;
}

export interface TraceDetail {
  trace_id: string;
  spans: TraceSpan[];
}

export interface ObservabilitySummary {
  hours: number;
  traces: number;
  spans: number;
  error_rate: number;
  p50_ms: number | null;
  p95_ms: number | null;
  input_tokens: number;
  output_tokens: number;
  by_service: Record<string, number>;
  by_model: { model: string; spans: number }[];
}

export interface ExporterStatus {
  tracing_enabled: boolean;
  exporter: 'console' | 'gcp' | 'otlp';
  otlp_endpoint: string | null;
  ingest_path: string;
  accepted_formats: string[];
  cloud_trace_project: string | null;
}

export interface CloudTraceRow {
  trace_id: string;
  root_span: string;
  start_time: string | null;
  end_time: string | null;
}

export interface GcpStatus {
  project: string | null;
  location: string;
  configured: boolean;
}
