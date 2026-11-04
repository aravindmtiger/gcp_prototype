// Agent Canvas helpers: node creation from a drop, client-side checks that mirror the API.
import type { ToolId, WorkflowNode } from '../types';

export const AGENT_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9_-]{2,63}$/;
export const MAX_CANVAS_NODES = 20;
export const DRAG_TYPE = 'application/x-agent-node';

/** What a tool palette item carries when it is dragged onto the canvas. */
export interface PaletteEntry {
  tool: ToolId;
  label: string;
  config: Record<string, string>;
}

/** Config fields each tool needs before it can be saved. Mirrors TOOL_CATALOG in the API. */
export const TOOL_CONFIG_FIELDS: Record<ToolId, string[]> = {
  knowledge_retriever: ['knowledge_source_id'],
  sql_executor: ['knowledge_source_id'],
  nosql_executor: ['firestore_collection'],
  no_sql_executor: ['firestore_collection'],
  web_search: [],
  email_sender: ['sender_email'],
  file_reader: ['gcs_bucket'],
  code_executor: [],
  mcp_server: ['mcp_server_id'],
  base: [],
  router: [],
  loop: [],
  if_else: ['condition'],
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
    if (
      typeof parsed?.tool !== 'string' ||
      typeof parsed?.label !== 'string' ||
      typeof parsed?.config !== 'object' ||
      parsed.config === null ||
      Array.isArray(parsed.config) ||
      !Object.prototype.hasOwnProperty.call(TOOL_CONFIG_FIELDS, parsed.tool)
    ) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

/** Human-readable reasons the canvas cannot be saved yet. Empty means ready. */
export function canvasProblems(
  name: string,
  description: string,
  nodes: WorkflowNode[],
  edges: { source: string; target: string; label?: unknown }[] = [],
): string[] {
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
    if (node.tool === 'loop' && node.config.max_iterations) {
      const max = Number(node.config.max_iterations);
      if (!Number.isInteger(max) || max < 1 || max > 20) {
        problems.push(`${node.id}: maximum loop iterations must be between 1 and 20`);
      }
    }

    if (['router', 'if_else', 'loop', 'hitl'].includes(node.tool)) {
      const outgoing = edges.filter((edge) => edge.source === node.id);
      const labels = outgoing.map((edge) => (typeof edge.label === 'string' ? edge.label.trim() : ''));
      if (labels.some((label) => !label)) {
        problems.push(`${node.id}: label every outgoing path`);
      }
      if (new Set(labels.filter(Boolean)).size !== labels.filter(Boolean).length) {
        problems.push(`${node.id}: outgoing path labels must be unique`);
      }
      if ((node.tool === 'router' || node.tool === 'hitl') && outgoing.length < 2) {
        problems.push(`${node.id}: add at least two outgoing paths`);
      }
      if (node.tool === 'if_else' && (labels.length !== 2 || !['true', 'false'].every((label) => labels.includes(label)))) {
        problems.push(`${node.id}: label its two outgoing paths 'true' and 'false'`);
      }
      if (node.tool === 'loop' && (labels.length !== 2 || !['continue', 'exit'].every((label) => labels.includes(label)))) {
        problems.push(`${node.id}: label its two outgoing paths 'continue' and 'exit'`);
      }
    }
  }
  return problems;
}
