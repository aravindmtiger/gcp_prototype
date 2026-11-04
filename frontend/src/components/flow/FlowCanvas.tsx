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
  nodePalette: PaletteEntry[];
  toolPalette: PaletteEntry[];
  activePalette: 'nodes' | 'tools' | null;
  interactionMode: 'select' | 'pan';
  onNodesChange: OnNodesChange<FlowNode>;
  onEdgesChange: OnEdgesChange;
  onConnect: (connection: Connection) => void;
  onDrop: (entry: PaletteEntry, position: { x: number; y: number }) => void;
  onAddTool: (entry: PaletteEntry) => void;
  onPaletteChange: (panel: 'nodes' | 'tools' | null) => void;
  onInteractionModeChange: (mode: 'select' | 'pan') => void;
  onSelect: (id: string | null) => void;
  onAutoFormat?: () => void;
  editable: boolean;
}

/** The agent canvas. Must sit inside a ReactFlowProvider, because it reads the viewport to place drops. */
export function FlowCanvas({
  nodes,
  edges,
  nodePalette,
  toolPalette,
  activePalette,
  interactionMode,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onDrop,
  onAddTool,
  onPaletteChange,
  onInteractionModeChange,
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

  const startPaletteDrag = (entry: PaletteEntry) => (event: DragEvent<HTMLButtonElement>) => {
    event.dataTransfer.setData(DRAG_TYPE, JSON.stringify(entry));
    event.dataTransfer.effectAllowed = 'copy';
  };

  const renderPalette = (items: PaletteEntry[]) => (
    <div className={styles.paletteList}>
      {items.map((entry) => (
        <button
          key={`${entry.tool}-${entry.label}`}
          type="button"
          className={styles.paletteItem}
          draggable={editable}
          onDragStart={startPaletteDrag(entry)}
          onDoubleClick={() => editable && onAddTool(entry)}
          disabled={!editable}
          title="Drag onto the canvas or double-click to add"
        >
          <span>{entry.label}</span>
          <span className={styles.dragMark} aria-hidden="true">⠿</span>
        </button>
      ))}
    </div>
  );

  return (
    <div className={styles.canvas} onDragOver={(e) => editable && e.preventDefault()} onDrop={handleDrop}>
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
        fitViewOptions={{ padding: 0.3, maxZoom: 0.75 }}
        minZoom={0.15}
        maxZoom={1.5}
        panOnDrag={interactionMode === 'pan'}
        selectionOnDrag={interactionMode === 'select'}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{ type: 'flow' }}
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} color="#d6d6e0" />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable nodeColor={(n) => (n.type === 'marker' ? '#f7931e' : '#4f7fc4')} />
      </ReactFlow>
      {activePalette && (
        <aside className={styles.palettePanel} aria-label={`${activePalette} palette`}>
          <div className={styles.paletteHeader}>
            <strong>{activePalette === 'nodes' ? 'Nodes' : 'Tools'}</strong>
            <button type="button" onClick={() => onPaletteChange(null)} aria-label="Close palette">×</button>
          </div>
          <p className={styles.paletteHint}>Drag an item onto the canvas. Start and Stop are already on the canvas.</p>
          {renderPalette(activePalette === 'nodes' ? nodePalette : toolPalette)}
        </aside>
      )}
      <nav className={styles.sideToolbar} aria-label="Canvas toolbar">
        <button
          type="button"
          className={`${styles.sideToolButton} ${activePalette === 'nodes' ? styles.sideToolActive : ''}`}
          onClick={() => onPaletteChange(activePalette === 'nodes' ? null : 'nodes')}
          aria-label="Open node palette"
          aria-pressed={activePalette === 'nodes'}
          title="Nodes"
        >
          <span aria-hidden="true">▦</span><small>Nodes</small>
        </button>
        <button
          type="button"
          className={`${styles.sideToolButton} ${activePalette === 'tools' ? styles.sideToolActive : ''}`}
          onClick={() => onPaletteChange(activePalette === 'tools' ? null : 'tools')}
          aria-label="Open tool palette"
          aria-pressed={activePalette === 'tools'}
          title="Tools"
        >
          <span aria-hidden="true">⚙</span><small>Tools</small>
        </button>
        <span className={styles.toolbarDivider} />
        <button
          type="button"
          className={`${styles.sideToolButton} ${interactionMode === 'select' ? styles.sideToolActive : ''}`}
          onClick={() => onInteractionModeChange('select')}
          aria-label="Select and connect nodes"
          aria-pressed={interactionMode === 'select'}
          title="Select and connect"
        >
          <span aria-hidden="true">↖</span><small>Select</small>
        </button>
        <button
          type="button"
          className={`${styles.sideToolButton} ${interactionMode === 'pan' ? styles.sideToolActive : ''}`}
          onClick={() => onInteractionModeChange('pan')}
          aria-label="Pan canvas"
          aria-pressed={interactionMode === 'pan'}
          title="Pan canvas"
        >
          <span aria-hidden="true">✋</span><small>Pan</small>
        </button>
        <button
          type="button"
          className={styles.sideToolButton}
          onClick={onAutoFormat}
          aria-label="Auto format canvas"
          title="Auto Format"
        >
          <span aria-hidden="true">⌘</span><small>Format</small>
        </button>
        <button
          type="button"
          className={styles.sideToolButton}
          onClick={() => fitView({ padding: 0.2, duration: 300 })}
          aria-label="Fit canvas to view"
          title="Fit View"
        >
          <span aria-hidden="true">⛶</span><small>Fit</small>
        </button>
      </nav>
    </div>
  );
}
