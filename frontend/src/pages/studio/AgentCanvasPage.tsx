import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ReactFlowProvider, applyEdgeChanges, applyNodeChanges, type Connection, type Edge, type EdgeChange, type NodeChange } from '@xyflow/react';
import { api } from '../../api';
import { FlowCanvas } from '../../components/flow/FlowCanvas';
import type { FlowNode } from '../../components/flow/ToolNode';
import { AGENT_NAME_PATTERN, MAX_CANVAS_NODES, TOOL_CONFIG_FIELDS, type PaletteEntry, canvasProblems, nextNodeId } from '../../lib/canvas';
import flowStyles from '../../components/flow/flow.module.css';
import { ErrorBanner, PageHeader, StatusBadge, messageOf, useLoad, studioStyles as s } from '../../studio/ui';
import type { Agent, AgentArchitecture, ToolId, WorkflowNode } from '../../types';
import { DeploymentPanel } from './DeploymentPanel';

const TOOL_LABELS: Record<ToolId, string> = {
  knowledge_retriever: 'Knowledge retriever',
  sql_executor: 'SQL executor',
  nosql_executor: 'NoSQL executor',
  no_sql_executor: 'NoSQL executor',
  web_search: 'Web search',
  email_sender: 'Email sender',
  file_reader: 'File reader',
  code_executor: 'Code executor',
  mcp_server: 'MCP server',
  base: 'Base',
  router: 'Router',
  loop: 'Loop',
  if_else: 'If Else',
  hitl: 'HITL',
};

const needsSetup = (tool: ToolId | undefined, config: Record<string, string>) =>
  tool ? TOOL_CONFIG_FIELDS[tool].some((field) => !config[field]) : false;

function markerNode(kind: 'start' | 'end', position: { x: number; y: number }): FlowNode {
  return {
    id: kind,
    type: 'marker',
    position,
    data: { kind, label: '', systemPrompt: '', config: {}, needsSetup: false, toolDetail: '', editable: false },
  };
}

function defaultMarkerNodes(): FlowNode[] {
  return [markerNode('start', { x: 60, y: 240 }), markerNode('end', { x: 460, y: 240 })];
}

/** Canvas state to the architecture the backend stores. Positions and edges are saved as they are. */
function toArchitecture(nodes: FlowNode[], edges: Edge[]): AgentArchitecture {
  return {
    nodes: nodes.map((n) => ({
      id: n.id,
      kind: n.data.kind,
      position: { x: Math.round(n.position.x), y: Math.round(n.position.y) },
      tool: n.data.kind === 'tool' ? (n.data.tool ?? null) : null,
      system_prompt: n.data.kind === 'tool' ? n.data.systemPrompt : '',
      config: n.data.kind === 'tool' ? n.data.config : {},
    })),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      route: typeof e.label === 'string' && e.label.trim() ? e.label.trim() : null,
    })),
  };
}

/** Saved architecture to canvas state. Older agents without endpoints get the defaults. */
function fromAgent(agent: Agent): { nodes: FlowNode[]; edges: Edge[] } {
  const toolNode = (id: string, x: number, y: number, tool: ToolId, prompt: string, config: Record<string, string>): FlowNode => ({
    id,
    type: 'tool',
    position: { x, y },
    data: {
      kind: 'tool', tool, label: TOOL_LABELS[tool], systemPrompt: prompt, config,
      needsSetup: false, toolDetail: '', editable: true,
    },
  });

  if (agent.architecture) {
    const nodes: FlowNode[] = agent.architecture.nodes.map((n) =>
      n.kind === 'tool' && n.tool
        ? { ...toolNode(n.id, n.position.x, n.position.y, n.tool, n.system_prompt ?? '', n.config ?? {}) }
        : { id: n.id, type: 'marker', position: { x: n.position.x, y: n.position.y }, data: { kind: n.kind, label: '', systemPrompt: '', config: {}, needsSetup: false, toolDetail: '', editable: false } },
    );
    if (!nodes.some((n) => n.data.kind === 'start')) nodes.push(markerNode('start', { x: 60, y: 240 }));
    if (!nodes.some((n) => n.data.kind === 'end')) {
      const lastToolX = Math.max(220, ...nodes.filter((n) => n.data.kind === 'tool').map((n) => n.position.x));
      nodes.push(markerNode('end', { x: lastToolX + 220, y: 240 }));
    }
    const edges: Edge[] = agent.architecture.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      ...(e.route ? { label: e.route } : {}),
      type: 'flow',
      sourceHandle: 'out',
      targetHandle: 'in',
    }));
    const toolIds = new Set(nodes.filter((n) => n.data.kind === 'tool').map((n) => n.id));
    const incoming = new Set(edges.filter((e) => toolIds.has(e.source) && toolIds.has(e.target)).map((e) => e.target));
    const outgoing = new Set(edges.filter((e) => toolIds.has(e.source) && toolIds.has(e.target)).map((e) => e.source));
    const startId = nodes.find((n) => n.data.kind === 'start')!.id;
    const endId = nodes.find((n) => n.data.kind === 'end')!.id;
    for (const id of toolIds) {
      if (!incoming.has(id) && !edges.some((edge) => edge.source === startId && edge.target === id)) {
        edges.push({ id: `auto_${startId}_${id}`, source: startId, target: id, type: 'flow', sourceHandle: 'out', targetHandle: 'in' });
      }
      if (!outgoing.has(id) && !edges.some((edge) => edge.source === id && edge.target === endId)) {
        edges.push({ id: `auto_${id}_${endId}`, source: id, target: endId, type: 'flow', sourceHandle: 'out', targetHandle: 'in' });
      }
    }
    return { nodes, edges };
  }

  const tools = agent.workflow.nodes;
  const nodes = [
  markerNode('start', { x: 60, y: 240 }),
  ...tools.map((n, index) => toolNode(n.id, 180 + index * 220, 220, n.tool, n.system_prompt, n.config)),
  markerNode('end', { x: 180 + tools.length * 220, y: 240 }),
  ];
  const edges: Edge[] = tools.length
    ? [
        { id: `start->${tools[0].id}`, source: 'start', target: tools[0].id, type: 'flow', sourceHandle: 'out', targetHandle: 'in' },
        ...tools.slice(1).map((n, index) => ({
          id: `${tools[index].id}->${n.id}`, source: tools[index].id, target: n.id, type: 'flow', sourceHandle: 'out', targetHandle: 'in',
        })),
        { id: `${tools[tools.length - 1].id}->end`, source: tools[tools.length - 1].id, target: 'end', type: 'flow', sourceHandle: 'out', targetHandle: 'in' },
      ]
    : [];
  return { nodes, edges };
}

export function AgentCanvasPage() {
  return (
    <ReactFlowProvider>
      <AgentCanvasEditor />
    </ReactFlowProvider>
  );
}

function AgentCanvasEditor() {
  const { agentId } = useParams();
  const navigate = useNavigate();
  const isNew = !agentId;

  const knowledge = useLoad(api.listKnowledge);
  const mcpServers = useLoad(api.listMcpServers);
  const guardrails = useLoad(api.listGuardrails);

  const [agent, setAgent] = useState<Agent | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [nodes, setNodes] = useState<FlowNode[]>(defaultMarkerNodes);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [guardrailId, setGuardrailId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [activePalette, setActivePalette] = useState<'nodes' | 'tools' | null>(null);
  const [interactionMode, setInteractionMode] = useState<'select' | 'pan'>('select');

  useEffect(() => {
    if (!agentId) return;
    api
      .getAgent(agentId)
      .then((loaded) => {
        setAgent(loaded);
        setName(loaded.name);
        setDescription(loaded.description);
        const graph = fromAgent(loaded);
        setNodes(graph.nodes);
        setEdges(graph.edges);
        setGuardrailId(loaded.guardrail_template_id ?? '');
      })
      .catch((err: unknown) => setError(messageOf(err)));
  }, [agentId]);

  // Agent names are unique across the platform. Check the name against the server as it is typed.
  const [nameFree, setNameFree] = useState<boolean | null>(null);
  useEffect(() => {
    setNameFree(null);
    if (!isNew || !AGENT_NAME_PATTERN.test(name)) return;
    let live = true;
    const timer = window.setTimeout(() => {
      api
        .checkAgentName(name)
        .then((result) => live && setNameFree(result.available))
        .catch(() => live && setNameFree(null));
    }, 350);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [name, isNew]);

  const editable = !agent || agent.status === 'draft' || agent.status === 'rejected';

  // Nodes carry their live status (setup needed, editable) so the cards can show it.
  const displayNodes = useMemo<FlowNode[]>(
    () =>
      nodes.map((n) => ({
        ...n,
        selected: n.id === selectedId,
        data: {
          ...n.data,
          editable,
          needsSetup: n.data.kind === 'tool' && needsSetup(n.data.tool, n.data.config),
          toolDetail: n.data.kind === 'tool' ? toolDetail(n.data.tool, n.data.config, knowledge.data ?? undefined, mcpServers.data ?? undefined) : '',
        },
      })),
    [nodes, selectedId, editable, knowledge.data, mcpServers.data],
  );

  const toolNodes = nodes.filter((n) => n.data.kind === 'tool');
  const workflowNodes: WorkflowNode[] = toolNodes.map((n) => ({
    id: n.id, tool: n.data.tool as ToolId, system_prompt: n.data.systemPrompt, config: n.data.config,
  }));
  const selected = nodes.find((n) => n.id === selectedId && n.data.kind === 'tool') ?? null;
  const selectedRoutes = selected ? edges.filter((edge) => edge.source === selected.id) : [];

  const problems = canvasProblems(name, description, workflowNodes, edges);
  if (nameFree === false) problems.unshift(`The name '${name}' is already used by another agent`);

  const nodePalette: PaletteEntry[] = [
    { tool: 'base', label: TOOL_LABELS.base, config: {} },
    { tool: 'router', label: TOOL_LABELS.router, config: {} },
    { tool: 'loop', label: TOOL_LABELS.loop, config: {} },
    { tool: 'if_else', label: TOOL_LABELS.if_else, config: {} },
    { tool: 'hitl', label: TOOL_LABELS.hitl, config: {} },
  ];
  const toolPalette: PaletteEntry[] = [
    { tool: 'knowledge_retriever', label: TOOL_LABELS.knowledge_retriever, config: {} },
    { tool: 'sql_executor', label: TOOL_LABELS.sql_executor, config: {} },
    { tool: 'nosql_executor', label: TOOL_LABELS.nosql_executor, config: {} },
    { tool: 'web_search', label: TOOL_LABELS.web_search, config: {} },
    { tool: 'email_sender', label: TOOL_LABELS.email_sender, config: {} },
    { tool: 'file_reader', label: TOOL_LABELS.file_reader, config: {} },
    { tool: 'code_executor', label: TOOL_LABELS.code_executor, config: {} },
    ...(mcpServers.data ?? []).map((server) => ({
      tool: 'mcp_server' as const,
      label: `MCP: ${server.name}`,
      config: { mcp_server_id: server.id },
    })),
  ];

  const addTool = (tool: ToolId, config: Record<string, string>, position: { x: number; y: number }) => {
    if (toolNodes.length >= MAX_CANVAS_NODES) return;
    const id = nextNodeId(tool, workflowNodes);
    setNodes((current) => [
      ...current,
      {
        id, type: 'tool', position,
        data: {
          kind: 'tool',
          tool,
          label: TOOL_LABELS[tool],
          systemPrompt: '',
          config: { ...(tool === 'loop' ? { max_iterations: '3' } : {}), ...config },
          needsSetup: false,
          toolDetail: '',
          editable: true,
        },
      },
    ]);
    if (toolNodes.length === 0) {
      const startId = nodes.find((node) => node.data.kind === 'start')?.id ?? 'start';
      const endId = nodes.find((node) => node.data.kind === 'end')?.id ?? 'end';
      setEdges((current) => [
        ...current,
        { id: `${startId}->${id}`, source: startId, target: id, type: 'flow', sourceHandle: 'out', targetHandle: 'in' },
        { id: `${id}->${endId}`, source: id, target: endId, type: 'flow', sourceHandle: 'out', targetHandle: 'in' },
      ]);
    }
    setSelectedId(id);
  };

  const onDrop = (entry: PaletteEntry, position: { x: number; y: number }) => {
    if (!editable) return;
    addTool(entry.tool, entry.config, position);
  };

  const addPaletteTool = (entry: PaletteEntry) =>
    addTool(entry.tool, entry.config, { x: 180 + toolNodes.length * 120, y: 220 });

  const onConnect = (connection: Connection) => {
    if (!connection.source || !connection.target || connection.source === connection.target) return;
    const id = `${connection.source}->${connection.target}`;
    const source = nodes.find((node) => node.id === connection.source);
    const isRouted = source?.data.kind === 'tool'
      && ['router', 'if_else', 'loop', 'hitl'].includes(source.data.tool ?? '');
    setEdges((current) => {
      if (current.some((edge) => edge.id === id)) return current;
      const previousRoutes = current.filter((edge) => edge.source === connection.source).length;
      const label = isRouted
        ? source?.data.tool === 'if_else'
          ? previousRoutes === 0 ? 'true' : 'false'
          : source?.data.tool === 'loop'
            ? previousRoutes === 0 ? 'continue' : 'exit'
            : `path_${previousRoutes + 1}`
        : undefined;
      return [
        ...current,
        {
          id,
          source: connection.source!,
          target: connection.target!,
          ...(label ? { label } : {}),
          type: 'flow',
          sourceHandle: connection.sourceHandle,
          targetHandle: connection.targetHandle,
        },
      ];
    });
  };

  const onNodesChange = (changes: NodeChange<FlowNode>[]) => {
    const fixedMarkerIds = new Set(nodes.filter((node) => node.data.kind === 'start' || node.data.kind === 'end').map((node) => node.id));
    const editableChanges = changes.filter(
      (change) => change.type !== 'remove' || !fixedMarkerIds.has(change.id),
    );
    setNodes((current) => applyNodeChanges(editableChanges, current));
    for (const change of editableChanges) {
      if (change.type === 'remove' && change.id === selectedId) setSelectedId(null);
    }
    // Deleting a node also removes its edges.
    const removed = editableChanges.filter((c) => c.type === 'remove').map((c) => c.id);
    if (removed.length) setEdges((current) => current.filter((e) => !removed.includes(e.source) && !removed.includes(e.target)));
  };

  const onEdgesChange = (changes: EdgeChange[]) => setEdges((current) => applyEdgeChanges(changes, current));

  const updateTool = (id: string, patch: Partial<FlowNode['data']>) =>
    setNodes((current) => current.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)));

  const updateRoute = (edgeId: string, route: string) =>
    setEdges((current) => current.map((edge) => (edge.id === edgeId ? { ...edge, label: route } : edge)));

  const removeSelected = () => {
    if (!selectedId) return;
    setNodes((current) => current.filter((n) => n.id !== selectedId));
    setEdges((current) => current.filter((e) => e.source !== selectedId && e.target !== selectedId));
    setSelectedId(null);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const architecture = toArchitecture(nodes, edges);
      if (isNew) {
        const created = await api.createAgent({
          name,
          description,
          architecture,
          guardrail_template_id: guardrailId || null,
        });
        navigate(`/agents/${created.id}/edit`, { replace: true });
        return;
      }
      const updated = await api.updateAgent(agentId!, {
        description,
        architecture,
        ...(guardrailId ? { guardrail_template_id: guardrailId } : {}),
      });
      setAgent(updated);
      setNotice('Draft saved. The architecture and the ADK graph were regenerated.');
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!agent) return;
    setBusy(true);
    setError(null);
    try {
      await api.submitAgent(agent.id);
      const refreshed = await api.getAgent(agent.id);
      setAgent(refreshed);
      setNotice('Sent for review. An admin will see it in Approvals.');
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  const refreshAgent = () => {
    if (agentId) api.getAgent(agentId).then(setAgent).catch((err: unknown) => setError(messageOf(err)));
  };

  const sourcesFor = (tool: ToolId) =>
    (knowledge.data ?? []).filter((source) =>
      tool === 'knowledge_retriever' ? source.kind === 'unstructured' : source.kind === 'structured',
    );

  const autoFormatCanvas = useCallback(() => {
    setNodes((current) => {
      const toolNodes = current.filter((node) => node.data.kind === 'tool');
      if (toolNodes.length === 0) return current;

      const next = current.map((node) => {
        if (node.data.kind === 'tool') {
          const index = toolNodes.findIndex((tool) => tool.id === node.id);
          return {
            ...node,
            position: {
              x: 150 + (index % 3) * 220,
              y: 140 + Math.floor(index / 3) * 145,
            },
          };
        }
        if (node.data.kind === 'start') {
          return { ...node, position: { x: 40, y: 240 } };
        }
        if (node.data.kind === 'end') {
          const lastColumn = Math.max(0, (toolNodes.length - 1) % 3);
          const lastRow = Math.max(0, Math.floor((toolNodes.length - 1) / 3));
          return { ...node, position: { x: 150 + lastColumn * 220 + 205, y: 140 + lastRow * 145 + 22 } };
        }
        return node;
      });

      return next;
    });
  }, []);

  const validateCanvas = () => {
    if (problems.length > 0) {
      setError(problems.join(' • '));
      setNotice(null);
      return;
    }
    setError(null);
    setNotice('Canvas is valid. Ready to save.');
  };

  return (
    <div className={s.page}>
      <PageHeader
        title={isNew ? 'New agent' : name}
        subtitle="Drag tools onto the canvas and connect them. Each tool is an agent in the flow."
        actions={
          <>
            {agent && <StatusBadge status={agent.status} />}
            <button type="button" className={s.btnGhost} onClick={validateCanvas}>Validate first</button>
            <button type="button" className={s.btnPrimary} disabled={busy || !editable || problems.length > 0} onClick={save}>Save</button>
          </>
        }
      />
      <ErrorBanner message={error} />
      {notice && <div className={s.notice}>{notice}</div>}

      <FlowCanvas
        nodes={displayNodes}
        edges={edges}
        nodePalette={nodePalette}
        toolPalette={toolPalette}
        activePalette={activePalette}
        interactionMode={interactionMode}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onDrop={onDrop}
        onAddTool={addPaletteTool}
        onPaletteChange={setActivePalette}
        onInteractionModeChange={setInteractionMode}
        onSelect={setSelectedId}
        onAutoFormat={autoFormatCanvas}
        editable={editable}
      />

      <div className={flowStyles.editorDetails}>
        <div style={{ display: 'grid', gap: 18 }}>
          {selected && selected.data.kind === 'tool' && (
            <aside className={s.card} style={{ display: 'grid', gap: 12 }}>
              <h3 style={{ margin: 0 }}>{TOOL_LABELS[selected.data.tool as ToolId]}</h3>
              <span className={s.muted}>{selected.id}</span>

              {(selected.data.tool === 'knowledge_retriever' || selected.data.tool === 'sql_executor') && (
                <label className={s.field}>
                  {selected.data.tool === 'knowledge_retriever' ? 'RAG corpus' : 'Structured source'}
                  <select
                    className={s.select}
                    disabled={!editable}
                    value={selected.data.config.knowledge_source_id ?? ''}
                    onChange={(e) => updateTool(selected.id, { config: { knowledge_source_id: e.target.value } })}
                  >
                    <option value="">Choose a source…</option>
                    {sourcesFor(selected.data.tool as ToolId).map((source) => (
                      <option key={source.id} value={source.id}>{source.name}</option>
                    ))}
                  </select>
                </label>
              )}

              {(selected.data.tool === 'nosql_executor' || selected.data.tool === 'no_sql_executor') && (
                <label className={s.field}>
                  Firestore collection path
                  <input
                    className={s.input}
                    disabled={!editable}
                    value={selected.data.config.firestore_collection ?? ''}
                    onChange={(e) => updateTool(selected.id, { config: { ...selected.data.config, firestore_collection: e.target.value } })}
                    placeholder="customers"
                  />
                </label>
              )}

              {selected.data.tool === 'email_sender' && (
                <label className={s.field}>
                  Gmail sender address
                  <input
                    className={s.input}
                    type="email"
                    disabled={!editable}
                    value={selected.data.config.sender_email ?? ''}
                    onChange={(e) => updateTool(selected.id, { config: { ...selected.data.config, sender_email: e.target.value } })}
                    placeholder="agent@example.com"
                  />
                </label>
              )}

              {selected.data.tool === 'file_reader' && (
                <>
                  <label className={s.field}>
                    Cloud Storage bucket
                    <input
                      className={s.input}
                      disabled={!editable}
                      value={selected.data.config.gcs_bucket ?? ''}
                      onChange={(e) => updateTool(selected.id, { config: { ...selected.data.config, gcs_bucket: e.target.value } })}
                      placeholder="my-agent-files"
                    />
                  </label>
                  <label className={s.field}>
                    Allowed object prefix (optional)
                    <input
                      className={s.input}
                      disabled={!editable}
                      value={selected.data.config.prefix ?? ''}
                      onChange={(e) => updateTool(selected.id, { config: { ...selected.data.config, prefix: e.target.value } })}
                      placeholder="documents/"
                    />
                  </label>
                </>
              )}

              {selected.data.tool === 'router' && (
                <label className={s.field}>
                  Routing criteria
                  <textarea
                    className={s.textarea}
                    maxLength={2000}
                    disabled={!editable}
                    value={selected.data.config.route_instruction ?? ''}
                    onChange={(e) => updateTool(selected.id, { config: { ...selected.data.config, route_instruction: e.target.value } })}
                    placeholder="How should the agent choose a path?"
                  />
                </label>
              )}

              {selected.data.tool === 'if_else' && (
                <label className={s.field}>
                  Condition to evaluate
                  <textarea
                    className={s.textarea}
                    maxLength={2000}
                    disabled={!editable}
                    value={selected.data.config.condition ?? ''}
                    onChange={(e) => updateTool(selected.id, { config: { ...selected.data.config, condition: e.target.value } })}
                    placeholder="The request is about an existing customer"
                  />
                </label>
              )}

              {selected.data.tool === 'loop' && (
                <>
                  <label className={s.field}>
                    Stop condition
                    <textarea
                      className={s.textarea}
                      maxLength={2000}
                      disabled={!editable}
                      value={selected.data.config.stop_condition ?? ''}
                      onChange={(e) => updateTool(selected.id, { config: { ...selected.data.config, stop_condition: e.target.value } })}
                      placeholder="Stop when all requested items have been verified"
                    />
                  </label>
                  <label className={s.field}>
                    Maximum iterations
                    <input
                      className={s.input}
                      type="number"
                      min={1}
                      max={20}
                      disabled={!editable}
                      value={selected.data.config.max_iterations ?? '3'}
                      onChange={(e) => updateTool(selected.id, { config: { ...selected.data.config, max_iterations: e.target.value } })}
                    />
                  </label>
                </>
              )}

              {selected.data.tool === 'hitl' && (
                <label className={s.field}>
                  Message for reviewer
                  <textarea
                    className={s.textarea}
                    maxLength={2000}
                    disabled={!editable}
                    value={selected.data.config.message ?? 'Choose how to continue.'}
                    onChange={(e) => updateTool(selected.id, { config: { ...selected.data.config, message: e.target.value } })}
                  />
                </label>
              )}

              {['router', 'if_else', 'loop', 'hitl'].includes(selected.data.tool ?? '') && (
                <div className={s.field}>
                  Outgoing path labels
                  {selectedRoutes.length === 0 && <span className={s.muted}>Connect this node to its paths.</span>}
                  {selectedRoutes.map((edge, index) => (
                    <label className={s.field} key={edge.id}>
                      Path {index + 1}
                      <input
                        className={s.input}
                        disabled={!editable}
                        value={typeof edge.label === 'string' ? edge.label : ''}
                        onChange={(e) => updateRoute(edge.id, e.target.value)}
                        placeholder="Path label"
                      />
                    </label>
                  ))}
                  {selected.data.tool === 'hitl' && <span className={s.muted}>These labels are shown as selectable buttons in the playground.</span>}
                </div>
              )}

              {selected.data.tool === 'mcp_server' && (
                <label className={s.field}>
                  MCP server
                  <select
                    className={s.select}
                    disabled={!editable}
                    value={selected.data.config.mcp_server_id ?? ''}
                    onChange={(e) => updateTool(selected.id, { config: { mcp_server_id: e.target.value } })}
                  >
                    <option value="">Choose a server…</option>
                    {(mcpServers.data ?? []).map((server) => (
                      <option key={server.id} value={server.id}>{server.name}</option>
                    ))}
                  </select>
                </label>
              )}

              <label className={s.field}>
                Instructions
                <textarea
                  className={s.textarea}
                  maxLength={4000}
                  disabled={!editable}
                  value={selected.data.systemPrompt}
                  onChange={(e) => updateTool(selected.id, { systemPrompt: e.target.value })}
                  placeholder="What should this step do, and how should it answer?"
                />
              </label>

              {editable && (
                <button type="button" className={s.btnDanger} onClick={removeSelected}>
                  Remove from canvas
                </button>
              )}
            </aside>
          )}

          <aside className={s.card} style={{ display: 'grid', gap: 14 }}>
            <h3 style={{ margin: 0 }}>Agent</h3>
            <label className={s.field}>
              Name
              <input
                className={s.input}
                value={name}
                disabled={!isNew}
                onChange={(e) => setName(e.target.value)}
                placeholder="policy_agent"
              />
              {isNew && name && (
                <span className={s.muted}>
                  {!AGENT_NAME_PATTERN.test(name)
                    ? 'Use 3-64 letters, digits, "-" or "_", starting with a letter'
                    : nameFree === null
                      ? 'Checking the name…'
                      : nameFree
                        ? 'Name is available'
                        : 'Name is already taken'}
                </span>
              )}
            </label>
            <label className={s.field}>
              Description
              <textarea className={s.textarea} disabled={!editable} value={description} onChange={(e) => setDescription(e.target.value)} />
            </label>
            <label className={s.field}>
              Guardrail
              <select className={s.select} disabled={!editable} value={guardrailId} onChange={(e) => setGuardrailId(e.target.value)}>
                <option value="">Default guardrail</option>
                {(guardrails.data ?? []).filter((g) => !g.is_default).map((g) => (
                  <option key={g.id} value={g.id}>{g.name}</option>
                ))}
              </select>
            </label>
            {problems.length > 0 && editable && (
              <ul className={s.muted} style={{ margin: 0, paddingLeft: 18 }}>
                {problems.map((problem) => <li key={problem}>{problem}</li>)}
              </ul>
            )}

            {agent && editable && agent.status === 'draft' && (
              <div style={{ display: 'grid', gap: 8, borderTop: '1px solid #ececf2', paddingTop: 12 }}>
                <button type="button" className={s.btnGhost} disabled={busy} onClick={submit}>
                  Submit for review
                </button>
              </div>
            )}

            {agent && !editable && agent.status === 'in_review' && <p className={s.muted}>Waiting for approval.</p>}
          </aside>
        </div>
      </div>

      {agent && (agent.status === 'approved' || agent.status === 'deployed') && (
        <div style={{ marginTop: 18 }}>
          <DeploymentPanel agent={agent} onChanged={refreshAgent} />
        </div>
      )}
    </div>
  );
}

function toolDetail(
  tool: ToolId | undefined,
  config: Record<string, string>,
  sources: { id: string; name: string }[] | undefined,
  servers: { id: string; name: string }[] | undefined,
): string {
  if (tool === 'knowledge_retriever' || tool === 'sql_executor') {
    const found = sources?.find((source) => source.id === config.knowledge_source_id);
    return found ? found.name : 'Choose a source';
  }
  if (tool === 'nosql_executor' || tool === 'no_sql_executor') {
    return config.firestore_collection || 'Choose a Firestore collection';
  }
  if (tool === 'email_sender') return config.sender_email || 'Choose a Gmail sender';
  if (tool === 'file_reader') return config.gcs_bucket || 'Choose a Storage bucket';
  if (tool === 'mcp_server') {
    const found = servers?.find((server) => server.id === config.mcp_server_id);
    return found ? found.name : 'Choose a server';
  }
  if (tool === 'web_search') return 'Search the web';
  if (tool === 'code_executor') return 'Run code';
  if (tool === 'base' || tool === 'router' || tool === 'loop' || tool === 'if_else' || tool === 'hitl') return 'Canvas node';
  return 'Ready';
}
