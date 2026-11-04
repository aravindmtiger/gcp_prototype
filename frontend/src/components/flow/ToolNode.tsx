import { Handle, Position, useReactFlow, type NodeProps, type Node } from '@xyflow/react';
import { CloseIcon } from '../CloseIcon';
import type { ToolId } from '../../types';
import styles from './flow.module.css';

export interface FlowNodeData extends Record<string, unknown> {
  kind: 'start' | 'end' | 'tool';
  tool?: ToolId;
  label: string;
  systemPrompt: string;
  config: Record<string, string>;
  /** Source or server still to choose. */
  needsSetup: boolean;
  /** Short line shown for the tool's source or server. */
  toolDetail: string;
  editable: boolean;
}

export type FlowNode = Node<FlowNodeData>;

const TOOL_STYLE: Record<ToolId, { head: string; tile: string; glyph: string; type: string }> = {
  knowledge_retriever: { head: '#eef4fc', tile: '#2f7ad0', glyph: '📚', type: 'Knowledge' },
  sql_executor: { head: '#fff4e6', tile: '#f7931e', glyph: '🗄', type: 'SQL' },
  nosql_executor: { head: '#fff2de', tile: '#d97706', glyph: '🗃', type: 'NoSQL' },
  no_sql_executor: { head: '#fff2de', tile: '#d97706', glyph: '🗃', type: 'NoSQL' },
  web_search: { head: '#eaf7ef', tile: '#2f9e5b', glyph: '🌐', type: 'Search' },
  email_sender: { head: '#fff0f3', tile: '#d946ef', glyph: '✉️', type: 'Email' },
  file_reader: { head: '#edf8ff', tile: '#0ea5e9', glyph: '📄', type: 'File' },
  code_executor: { head: '#f5f3ff', tile: '#8b5cf6', glyph: '💻', type: 'Code' },
  mcp_server: { head: '#f1ebff', tile: '#6b4fd0', glyph: '🔌', type: 'MCP' },
  base: { head: '#ebf8ff', tile: '#1d4ed8', glyph: '▣', type: 'Base' },
  router: { head: '#ecfccb', tile: '#65a30d', glyph: '↳', type: 'Router' },
  loop: { head: '#fef3c7', tile: '#d97706', glyph: '↻', type: 'Loop' },
  if_else: { head: '#fee2e2', tile: '#dc2626', glyph: '⇄', type: 'If/Else' },
  hitl: { head: '#f3e8ff', tile: '#7c3aed', glyph: '👤', type: 'HITL' },
};

/** A tool node: an agent with its tool, prompt and source. Input is on the left, output on the right. */
export function ToolNode({ id, data, selected }: NodeProps<FlowNode>) {
  const { deleteElements } = useReactFlow();
  const style = data.tool ? TOOL_STYLE[data.tool] : TOOL_STYLE.web_search;
  const prompt = data.systemPrompt.trim().split('\n')[0] || 'No instructions yet';

  return (
    <div
      className={`${styles.card} ${selected ? styles.cardSelected : ''} ${data.needsSetup ? styles.cardWarn : ''}`}
      style={{ width: 180 }}
    >
      <Handle type="target" position={Position.Left} id="in" className={styles.port} style={{ top: 40 }} />
      <div className={styles.head} style={{ background: style.head }}>
        <span className={styles.iconTile} style={{ background: style.tile }} aria-hidden="true">
          {style.glyph}
        </span>
        <div className={styles.titles}>
          <span className={styles.title}>{data.label}</span>
          <span className={styles.subtitle}>{style.type} · {id}</span>
        </div>
        {data.editable && (
          <button
            type="button"
            className={styles.removeButton}
            aria-label={`Remove ${id}`}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={() => void deleteElements({ nodes: [{ id }] })}
          >
            <CloseIcon />
          </button>
        )}
      </div>
      <div className={styles.body}>
        <div className={styles.row}>
          <span className={styles.rowLabel}>Model</span>
          <span className={styles.rowValue}>Chosen by the gateway</span>
        </div>
        <div className={styles.row}>
          <span className={styles.rowLabel}>Tool</span>
          <span className={`${styles.rowValue} ${data.needsSetup ? styles.warn : ''}`}>{data.toolDetail}</span>
        </div>
        <div className={styles.row}>
          <span className={styles.rowLabel}>Prompt</span>
          <span className={styles.rowValue} title={data.systemPrompt}>{prompt}</span>
        </div>
      </div>
      <Handle type="source" position={Position.Right} id="out" className={styles.port} style={{ top: 40 }} />
    </div>
  );
}

/** Start and Stop markers. They mark where the flow begins and ends; they are not agents. */
export function MarkerNode({ data, selected }: NodeProps<FlowNode>) {
  const isStart = data.kind === 'start';
  return (
    <div
      className={`${styles.marker} ${isStart ? styles.markerStart : styles.markerEnd} ${selected ? styles.markerSelected : ''}`}
      role="img"
      aria-label={isStart ? 'Start' : 'Stop'}
    >
      {isStart ? (
        <svg className={styles.markerIcon} viewBox="0 0 24 24" aria-hidden="true">
          <path d="M8 5.5v13L19 12 8 5.5Z" />
        </svg>
      ) : (
        <svg className={styles.markerIcon} viewBox="0 0 24 24" aria-hidden="true">
          <rect x="7" y="7" width="10" height="10" rx="1" />
        </svg>
      )}
      {isStart ? (
        <Handle type="source" position={Position.Right} id="out" className={`${styles.port} ${styles.markerPort}`} />
      ) : (
        <Handle type="target" position={Position.Left} id="in" className={`${styles.port} ${styles.markerPort}`} />
      )}
    </div>
  );
}
