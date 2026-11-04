// Agent Canvas helpers: node creation from a drop, client-side checks that mirror the API.
import type { ToolId, WorkflowNode } from '../types';

export const AGENT_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9_-]{2,63}$/;
export const MAX_CANVAS_NODES = 20;
export const DRAG_TYPE = 'application/x-agent-node';

/** What a palette item carries when it is dragged onto the canvas: a tool, or a Start/Stop marker. */
export interface PaletteEntry {
  tool?: ToolId;
  marker?: 'start' | 'end';
  label: string;
  config: Record<string, string>;
}

/** Config fields each tool needs before it can be saved. Mirrors TOOL_CATALOG in the API. */
export const TOOL_CONFIG_FIELDS: Record<ToolId, string[]> = {
  knowledge_retriever: ['knowledge_source_id'],
  sql_executor: ['knowledge_source_id'],
  nosql_executor: ['knowledge_source_id'],
  no_sql_executor: ['knowledge_source_id'],
  web_search: [],
  email_sender: [],
  file_reader: [],
  code_executor: [],
  mcp_server: ['mcp_server_id'],
  base: [],
  router: [],
  loop: [],
  if_else: [],
  hitl: [],
};

export function nextNodeId(tool: ToolId, nodes: WorkflowNode[]): string {
  const taken = new Set(nodes.map((n) => n.id));
  let index = 1;
  while (taken.has(`${tool}_${index}`)) index += 1;
  return `${tool}_${index}`;
}

export function parseDrop(raw: string): PaletteEntry | null {
  try {
    const parsed = JSON.parse(raw) as PaletteEntry;
    const valid = typeof parsed?.tool === 'string' || typeof parsed?.marker === 'string';
    return valid ? parsed : null;
  } catch {
    return null;
  }
}

/** Human-readable reasons the canvas cannot be saved yet. Empty means ready. */
export function canvasProblems(name: string, description: string, nodes: WorkflowNode[]): string[] {
  const problems: string[] = [];
  if (!AGENT_NAME_PATTERN.test(name)) {
    problems.push('Name: 3-64 letters, digits, "-" or "_", starting with a letter');
  }
  if (!description.trim()) problems.push('Add a description');
  if (nodes.length === 0) problems.push('Drag at least one tool onto the canvas');
  for (const node of nodes) {
    for (const field of TOOL_CONFIG_FIELDS[node.tool]) {
      if (!node.config[field]) problems.push(`${node.id}: choose a ${field.replace(/_id$/, '').replace(/_/g, ' ')}`);
    }
  }
  return problems;
}
