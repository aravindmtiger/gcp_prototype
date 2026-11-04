import { useCallback, useEffect, useMemo, useState, type DragEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ReactFlowProvider, applyEdgeChanges, applyNodeChanges, type Connection, type Edge, type EdgeChange, type NodeChange } from '@xyflow/react';
import { api } from '../../api';
import { FlowCanvas } from '../../components/flow/FlowCanvas';
import type { FlowNode } from '../../components/flow/ToolNode';
import { AGENT_NAME_PATTERN, DRAG_TYPE, MAX_CANVAS_NODES, TOOL_CONFIG_FIELDS, type PaletteEntry, canvasProblems, nextNodeId } from '../../lib/canvas';
import { EmptyState, ErrorBanner, PageHeader, StatusBadge, messageOf, useLoad, studioStyles as s } from '../../studio/ui';
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
    edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target })),
  };
}

/** Saved architecture to canvas state. Older agents without a graph get a row of tools, chained. */
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
        : { id: n.id, type: 'marker', position: { x: n.position.x, y: n.position.y }, data: { kind: n.kind, label: '', systemPrompt: '', config: {}, needsSetup: false, toolDetail: '', editable: true } },
    );
    const edges: Edge[] = agent.architecture.edges.map((e) => ({ id: e.id, source: e.source, target: e.target, type: 'flow', sourceHandle: 'out', targetHandle: 'in' }));
    return { nodes, edges };
  }

  const tools = agent.workflow.nodes;
  const nodes = tools.map((n, index) => toolNode(n.id, 120 + index * 300, 160, n.tool, n.system_prompt, n.config));
  const edges: Edge[] = tools.slice(1).map((n, index) => ({
    id: `${tools[index].id}->${n.id}`, source: tools[index].id, target: n.id, type: 'flow', sourceHandle: 'out', targetHandle: 'in',
  }));
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
  const [nodes, setNodes] = useState<FlowNode[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [guardrailId, setGuardrailId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [panel, setPanel] = useState<'agents' | 'nodes' | 'tools'>('tools');

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

  const problems = canvasProblems(name, description, workflowNodes);
  if (nameFree === false) problems.unshift(`The name '${name}' is already used by another agent`);

  const palette: PaletteEntry[] = [
    { tool: 'base', label: TOOL_LABELS.base, config: {} },
    { tool: 'router', label: TOOL_LABELS.router, config: {} },
    { tool: 'loop', label: TOOL_LABELS.loop, config: {} },
    { tool: 'if_else', label: TOOL_LABELS.if_else, config: {} },
    { tool: 'hitl', label: TOOL_LABELS.hitl, config: {} },
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
        data: { kind: 'tool', tool, label: TOOL_LABELS[tool], systemPrompt: '', config: { ...config }, needsSetup: false, toolDetail: '', editable: true },
      },
    ]);
    setSelectedId(id);
  };

  const addMarker = (kind: 'start' | 'end', position: { x: number; y: number }) => {
    if (nodes.some((n) => n.id === kind)) return; // one Start and one Stop at most
    setNodes((current) => [
      ...current,
      { id: kind, type: 'marker', position, data: { kind, label: '', systemPrompt: '', config: {}, needsSetup: false, toolDetail: '', editable: true } },
    ]);
  };

  const onDrop = (entry: PaletteEntry, position: { x: number; y: number }) => {
    if (!editable) return;
    if (entry.marker) return addMarker(entry.marker, position);
    if (entry.tool) addTool(entry.tool, entry.config, position);
  };

  const onConnect = (connection: Connection) => {
    if (!connection.source || !connection.target || connection.source === connection.target) return;
    const id = `${connection.source}->${connection.target}`;
    setEdges((current) =>
      current.some((e) => e.id === id)
        ? current
        : [...current, { id, source: connection.source!, target: connection.target!, type: 'flow', sourceHandle: connection.sourceHandle, targetHandle: connection.targetHandle }],
    );
  };

  const onNodesChange = (changes: NodeChange<FlowNode>[]) => {
    setNodes((current) => applyNodeChanges(changes, current));
    for (const change of changes) {
      if (change.type === 'remove' && change.id === selectedId) setSelectedId(null);
    }
    // Deleting a node also removes its edges.
    const removed = changes.filter((c) => c.type === 'remove').map((c) => c.id);
    if (removed.length) setEdges((current) => current.filter((e) => !removed.includes(e.source) && !removed.includes(e.target)));
  };

  const onEdgesChange = (changes: EdgeChange[]) => setEdges((current) => applyEdgeChanges(changes, current));

  const updateTool = (id: string, patch: Partial<FlowNode['data']>) =>
    setNodes((current) => current.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)));

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

  const onPaletteDragStart = (entry: PaletteEntry) => (event: DragEvent<HTMLDivElement>) => {
    event.dataTransfer.setData(DRAG_TYPE, JSON.stringify(entry));
  };

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
              x: 180 + (index % 3) * 260,
              y: 120 + Math.floor(index / 3) * 180,
            },
          };
        }
        if (node.data.kind === 'start') {
          return { ...node, position: { x: 80, y: 220 } };
        }
        if (node.data.kind === 'end') {
          return { ...node, position: { x: 180 + ((toolNodes.length - 1) % 3) * 260 + 200, y: 120 + Math.floor((toolNodes.length - 1) / 3) * 180 } };
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
        actions={agent && <StatusBadge status={agent.status} />}
      />
      <ErrorBanner message={error} />
      {notice && <div className={s.notice}>{notice}</div>}

      <div className={s.split}>
        <aside className={s.card}>
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            {(['agents', 'nodes', 'tools'] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                className={s.iconButton}
                style={{
                  flex: 1,
                  fontWeight: panel === tab ? 700 : 500,
                  background: panel === tab ? '#fff6ec' : '#fff',
                  borderColor: panel === tab ? '#f7c27d' : '#e6e6ee',
                  color: panel === tab ? '#b8660a' : '#2d2d35',
                }}
                onClick={() => setPanel(tab)}
              >
                {tab === 'agents' ? 'Agents' : tab === 'nodes' ? 'Nodes' : 'Tools'}
              </button>
            ))}
          </div>

          {panel === 'agents' && (
            <div style={{ display: 'grid', gap: 10 }}>
              <div className={s.muted}>Selected agent</div>
              <div className={s.card} style={{ padding: 12, background: '#fafafc' }}>
                <strong>{name || 'New agent'}</strong>
                <span className={s.muted}>{description || 'No description yet'}</span>
              </div>
            </div>
          )}

          {panel === 'nodes' && (
            <div>
              <h3 style={{ marginTop: 0 }}>Start and stop</h3>
              {(['start', 'end'] as const).map((kind) => {
                const placed = nodes.some((n) => n.id === kind);
                return (
                  <div
                    key={kind}
                    className={s.paletteItem}
                    draggable={editable && !placed}
                    onDragStart={onPaletteDragStart({ marker: kind, label: kind === 'start' ? 'Start' : 'Stop', config: {} })}
                    title={placed ? 'Already on the canvas' : 'Drag onto the canvas'}
                    style={{ opacity: placed ? 0.45 : 1 }}
                  >
                    {kind === 'start' ? '▶ Start' : '■ Stop'}
                  </div>
                );
              })}
              <p className={s.muted}>Drag from one card's right port to another card's left port to connect them.</p>
            </div>
          )}

          {panel === 'tools' && (
            <div>
              <h3 style={{ marginTop: 0 }}>Tool palette</h3>
              {palette.map((entry) => (
                <div
                  key={`${entry.tool}-${entry.label}`}
                  className={s.paletteItem}
                  draggable={editable}
                  onDragStart={onPaletteDragStart(entry)}
                  onDoubleClick={() => editable && entry.tool && addTool(entry.tool, entry.config, { x: 160 + toolNodes.length * 40, y: 180 })}
                  title="Drag onto the canvas, or double-click to add"
                >
                  {entry.label}
                </div>
              ))}
            </div>
          )}
        </aside>

        <section>
          {nodes.length === 0 && <EmptyState>Drag a tool or Start onto the canvas to begin.</EmptyState>}
          <FlowCanvas
            nodes={displayNodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onDrop={onDrop}
            onSelect={setSelectedId}
            onAutoFormat={autoFormatCanvas}
            editable={editable}
          />
        </section>

        <div style={{ display: 'grid', gap: 18 }}>
          {selected && selected.data.kind === 'tool' && (
            <aside className={s.card} style={{ display: 'grid', gap: 12 }}>
              <h3 style={{ margin: 0 }}>{TOOL_LABELS[selected.data.tool as ToolId]}</h3>
              <span className={s.muted}>{selected.id}</span>

              {(selected.data.tool === 'knowledge_retriever' || selected.data.tool === 'sql_executor' || selected.data.tool === 'nosql_executor' || selected.data.tool === 'no_sql_executor') && (
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
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <button type="button" className={s.btnGhost} onClick={validateCanvas}>
                Validate first
              </button>
              <button type="button" className={s.btnPrimary} disabled={busy || !editable || problems.length > 0} onClick={save}>
                Save
              </button>
            </div>

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
  if (tool === 'knowledge_retriever' || tool === 'sql_executor' || tool === 'nosql_executor' || tool === 'no_sql_executor') {
    const found = sources?.find((source) => source.id === config.knowledge_source_id);
    return found ? found.name : 'Choose a source';
  }
  if (tool === 'mcp_server') {
    const found = servers?.find((server) => server.id === config.mcp_server_id);
    return found ? found.name : 'Choose a server';
  }
  if (tool === 'web_search') return 'Search the web';
  if (tool === 'email_sender') return 'Send outbound mail';
  if (tool === 'file_reader') return 'Read files';
  if (tool === 'code_executor') return 'Run code';
  if (tool === 'base' || tool === 'router' || tool === 'loop' || tool === 'if_else' || tool === 'hitl') return 'Canvas node';
  return 'Ready';
}
