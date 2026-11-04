import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeTypes,
  type NodeTypes,
  type OnEdgesChange,
  type OnNodesChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { DragEvent } from 'react';
import { DRAG_TYPE, parseDrop, type PaletteEntry } from '../../lib/canvas';
import { FlowEdge } from './FlowEdge';
import { type FlowNode, MarkerNode, ToolNode } from './ToolNode';
import styles from './flow.module.css';

const NODE_TYPES: NodeTypes = { tool: ToolNode, marker: MarkerNode };
const EDGE_TYPES: EdgeTypes = { flow: FlowEdge };

interface FlowCanvasProps {
  nodes: FlowNode[];
  edges: Edge[];
  onNodesChange: OnNodesChange<FlowNode>;
  onEdgesChange: OnEdgesChange;
  onConnect: (connection: Connection) => void;
  onDrop: (entry: PaletteEntry, position: { x: number; y: number }) => void;
  onSelect: (id: string | null) => void;
  onAutoFormat?: () => void;
  editable: boolean;
}

/** The agent canvas. Must sit inside a ReactFlowProvider, because it reads the viewport to place drops. */
export function FlowCanvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onDrop,
  onSelect,
  onAutoFormat,
  editable,
}: FlowCanvasProps) {
  const { screenToFlowPosition, fitView } = useReactFlow();

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const entry = parseDrop(event.dataTransfer.getData(DRAG_TYPE));
    if (!entry || !editable) return;
    // Centre the new node under the pointer.
    const point = screenToFlowPosition({ x: event.clientX, y: event.clientY });
    onDrop(entry, { x: point.x - 130, y: point.y - 50 });
  };

  return (
    <div className={styles.canvas} onDragOver={(e) => editable && e.preventDefault()} onDrop={handleDrop}>
      <div className={styles.toolbar} aria-label="Canvas actions">
        <button type="button" className={styles.toolbarButton} onClick={onAutoFormat}>
          ⤢ Auto Format
        </button>
        <button type="button" className={styles.toolbarButton} onClick={() => fitView({ padding: 0.2, duration: 300 })}>
          ⛶ Fit View
        </button>
      </div>
      <ReactFlow<FlowNode, Edge>
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={editable ? onConnect : undefined}
        onNodeClick={(_, node) => onSelect(node.id)}
        onPaneClick={() => onSelect(null)}
        nodesDraggable={editable}
        nodesConnectable={editable}
        elementsSelectable
        deleteKeyCode={editable ? ['Backspace', 'Delete'] : null}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        panOnDrag
        selectionOnDrag
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{ type: 'flow' }}
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} color="#d6d6e0" />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable nodeColor={(n) => (n.type === 'marker' ? '#f7931e' : '#4f7fc4')} />
      </ReactFlow>
    </div>
  );
}
