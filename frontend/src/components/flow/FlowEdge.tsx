import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@xyflow/react';

/** Dashed blue connector; orange when selected. */
export function FlowEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  selected,
  markerEnd,
  label,
}: EdgeProps) {
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  return (
    <>
      <BaseEdge
        path={path}
        markerEnd={markerEnd}
        style={{
          stroke: selected ? '#f7931e' : '#4f7fc4',
          strokeWidth: selected ? 3 : 2,
          strokeDasharray: '6 5',
        }}
      />
      {label && (
        <EdgeLabelRenderer>
          <span
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: 'none',
              borderRadius: 999,
              padding: '2px 7px',
              background: '#fff',
              border: '1px solid #d6d6e0',
              color: '#444',
              fontSize: 11,
              fontWeight: 600,
            }}
          >
            {label}
          </span>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
