import { BaseEdge, getBezierPath, type EdgeProps } from '@xyflow/react';

/** Dashed blue connector; orange when selected. */
export function FlowEdge({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, selected, markerEnd }: EdgeProps) {
  const [path] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  return (
    <BaseEdge
      path={path}
      markerEnd={markerEnd}
      style={{
        stroke: selected ? '#f7931e' : '#4f7fc4',
        strokeWidth: selected ? 3 : 2,
        strokeDasharray: '6 5',
      }}
    />
  );
}
