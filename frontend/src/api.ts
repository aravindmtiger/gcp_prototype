import { getIdToken, clearIdToken, SIGNED_OUT_EVENT } from './auth';
import { appConfig } from './config';
import type {
  Agent,
  AgentArchitecture,
  AgentInput,
  AppUser,
  BigQueryTable,
  CloudTraceRow,
  EvalMetric,
  ExporterStatus,
  GcpEndpoint,
  GcpStatus,
  ObservabilitySummary,
  RagCorpus,
  TraceDetail,
  TraceSummaryRow,
  Me,
  Role,
  Approval,
  Deployment,
  DeployTarget,
  GuardrailTemplate,
  KnowledgeSource,
  McpServer,
  McpServerInput,
  PromptReply,
  ToolInfo,
} from './types';

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function errorMessage(status: number, body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((item: { loc?: unknown[]; msg?: string }) => {
      const field = item.loc?.slice(1).join('.');
      return field ? `${field}: ${item.msg}` : (item.msg ?? 'Invalid input');
    }).join('; ');
  }
  return status ? `${fallback} (HTTP ${status})` : fallback;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined) headers.set('Content-Type', 'application/json');

  if (appConfig.authMode === 'google') {
    const token = getIdToken();
    if (token) headers.set('Authorization', `Bearer ${token}`);
  } else {
    headers.set('X-Dev-User', appConfig.devUser);
  }

  const response = await fetch(`${appConfig.apiBaseUrl}${path}`, { ...init, headers });
  if (response.status === 204) return undefined as T;

  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && appConfig.authMode === 'google') {
      clearIdToken();
      window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
    }
    throw new ApiError(response.status, errorMessage(response.status, body, 'Request failed'));
  }
  return body as T;
}

export const api = {
  // Session and users
  me: () => apiFetch<Me>('/api/v1/me'),
  listUsers: () => apiFetch<AppUser[]>('/api/v1/users'),
  addUser: (email: string, role: Role) =>
    apiFetch<AppUser>('/api/v1/users', { method: 'POST', body: JSON.stringify({ email, role }) }),
  updateUserRole: (email: string, role: Role) =>
    apiFetch<AppUser>(`/api/v1/users/${encodeURIComponent(email)}`, { method: 'PUT', body: JSON.stringify({ role }) }),
  removeUser: (email: string) =>
    apiFetch<void>(`/api/v1/users/${encodeURIComponent(email)}`, { method: 'DELETE' }),

  // Studios
  listTools: () => apiFetch<ToolInfo[]>('/api/v1/tools'),
  listAgents: () => apiFetch<Agent[]>('/api/v1/agents'),
  getAgent: (agentId: string) => apiFetch<Agent>(`/api/v1/agents/${agentId}`),
  createAgent: (input: AgentInput) =>
    apiFetch<Agent>('/api/v1/agents', { method: 'POST', body: JSON.stringify(input) }),
  updateAgent: (agentId: string, patch: { description?: string; architecture?: AgentArchitecture; guardrail_template_id?: string | null }) =>
    apiFetch<Agent>(`/api/v1/agents/${agentId}`, { method: 'PUT', body: JSON.stringify(patch) }),
  // Every submitted agent goes to the admins for review.
  submitAgent: (agentId: string) => apiFetch<Approval>(`/api/v1/agents/${agentId}/submit`, { method: 'POST' }),
  listApprovals: (scope: 'assigned' | 'requested') => apiFetch<Approval[]>(`/api/v1/approvals?scope=${scope}`),
  decideApproval: (approvalId: string, decision: 'approve' | 'reject', comment: string) =>
    apiFetch<Approval>(`/api/v1/approvals/${approvalId}/decision`, {
      method: 'POST',
      body: JSON.stringify({ decision, comment }),
    }),
  createDeployment: (agentId: string, target: DeployTarget, sessionBackend: string, memoryBackend: string) =>
    apiFetch<Deployment>(`/api/v1/agents/${agentId}/deployments`, {
      method: 'POST',
      body: JSON.stringify({ target, session_backend: sessionBackend, memory_backend: memoryBackend }),
    }),
  listDeployments: (agentId: string) => apiFetch<Deployment[]>(`/api/v1/agents/${agentId}/deployments`),
  getDeployment: (deploymentId: string) => apiFetch<Deployment>(`/api/v1/deployments/${deploymentId}`),
  createPlaygroundSession: (agentId: string) =>
    apiFetch<{ session_id: string }>(`/api/v1/agents/${agentId}/playground/sessions`, { method: 'POST' }),
  runPlayground: (
    agentId: string,
    input: {
      session_id: string;
      message?: string;
      choice?: string;
      interrupt_id?: string;
      function_call_event_id?: string;
    },
  ) =>
    apiFetch<{ events: Record<string, unknown>[] }>(`/api/v1/agents/${agentId}/playground/run`, {
      method: 'POST',
      body: JSON.stringify(input),
    }),
  listKnowledge: () => apiFetch<KnowledgeSource[]>('/api/v1/knowledge-sources'),
  createKnowledge: (input: { name: string; description: string; kind: 'structured' | 'unstructured'; config: Record<string, string> }) =>
    apiFetch<KnowledgeSource>('/api/v1/knowledge-sources', { method: 'POST', body: JSON.stringify(input) }),
  listGuardrails: () => apiFetch<GuardrailTemplate[]>('/api/v1/guardrails'),
  createGuardrail: (input: Record<string, unknown>) =>
    apiFetch<GuardrailTemplate>('/api/v1/guardrails', { method: 'POST', body: JSON.stringify(input) }),
  listMcpServers: () => apiFetch<McpServer[]>('/api/v1/mcp-servers'),
  // Google Cloud resources, so forms can offer what the project already has
  gcpStatus: () => apiFetch<GcpStatus>('/api/v1/gcp/status'),
  listGcpEndpoints: () => apiFetch<GcpEndpoint[]>('/api/v1/gcp/mcp-endpoints'),
  listRagCorpora: () => apiFetch<RagCorpus[]>('/api/v1/gcp/rag-corpora'),
  listBigQueryTables: () => apiFetch<BigQueryTable[]>('/api/v1/gcp/bigquery-tables'),
  listCloudTraces: () => apiFetch<CloudTraceRow[]>('/api/v1/gcp/cloud-traces'),
  checkAgentName: (name: string) =>
    apiFetch<{ name: string; available: boolean }>(`/api/v1/agents/name-check?name=${encodeURIComponent(name)}`),

  // Evaluation criteria from the installed ADK
  listEvalMetrics: () => apiFetch<EvalMetric[]>('/api/v1/eval-metrics'),

  // Observability: OTLP traces stored by this platform
  listTraces: () => apiFetch<TraceSummaryRow[]>('/api/v1/observability/traces'),
  getTrace: (traceId: string) => apiFetch<TraceDetail>(`/api/v1/observability/traces/${traceId}`),
  traceSummary: (hours: number) => apiFetch<ObservabilitySummary>(`/api/v1/observability/summary?hours=${hours}`),
  exporterStatus: () => apiFetch<ExporterStatus>('/api/v1/observability/exporters'),
  promptAgent: (agentId: string, message: string) =>
    apiFetch<PromptReply>(`/api/v1/gateway/agents/${agentId}/prompt`, {
      method: 'POST',
      body: JSON.stringify({ message }),
    }),
  createMcpServer: (input: McpServerInput) =>
    apiFetch<McpServer>('/api/v1/mcp-servers', { method: 'POST', body: JSON.stringify(input) }),
  connectMcpServer: (serverId: string) =>
    apiFetch<McpServer>(`/api/v1/mcp-servers/${serverId}/connect`, { method: 'POST' }),
};
