import { Fragment, useMemo, useState } from 'react';
import { api } from '../../api';
import { clearTraces, loadTraces, promptAgentTraced } from '../../lib/gatewayTraces';
import { summarize, type CallTrace, type TraceSource } from '../../lib/traces';
import { EmptyState, PillTabs, StatusBadge, formatDate, useLoad, studioStyles as s } from '../../studio/ui';

type SourceFilter = 'all' | TraceSource;

const SOURCE_LABELS: Record<TraceSource, string> = { evaluation: 'Evaluation', probe: 'Probe' };

function statusOf(trace: CallTrace): string {
  if (trace.ok) return 'succeeded';
  return trace.blocked ? 'blocked' : 'failed';
}

function formatMs(value: number | null): string {
  return value === null ? '—' : `${value} ms`;
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/**
 * Call log for the Agent Gateway. It records calls made from this studio only, in this browser:
 * evaluation runs and the probes below. Calls from other clients are not visible here.
 */
export function AgentCallsPanel() {
  const agents = useLoad(() => api.listAgents());
  const [traces, setTraces] = useState<CallTrace[]>(() => loadTraces());
  const [agentFilter, setAgentFilter] = useState('all');
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [probeAgentId, setProbeAgentId] = useState('');
  const [probePrompt, setProbePrompt] = useState('');
  const [sending, setSending] = useState(false);

  const visible = useMemo(
    () =>
      traces.filter(
        (t) =>
          (agentFilter === 'all' || t.agentId === agentFilter) &&
          (sourceFilter === 'all' || t.source === sourceFilter),
      ),
    [traces, agentFilter, sourceFilter],
  );
  const metrics = useMemo(() => summarize(visible), [visible]);
  const agentOptions = useMemo(
    () => [...new Map(traces.map((t) => [t.agentId, t.agentName])).entries()],
    [traces],
  );

  const selectedProbeAgent = agents.data?.find((a) => a.id === (probeAgentId || agents.data?.[0]?.id));

  const sendProbe = async () => {
    const message = probePrompt.trim();
    if (!selectedProbeAgent || !message || sending) return;
    setSending(true);
    const trace = await promptAgentTraced({ id: selectedProbeAgent.id, name: selectedProbeAgent.name }, message, 'probe');
    setTraces(loadTraces());
    setExpandedId(trace.id);
    setProbePrompt('');
    setSending(false);
  };

  const clearLog = () => {
    if (!window.confirm('Clear the call log in this browser? This cannot be undone.')) return;
    clearTraces();
    setTraces([]);
    setExpandedId(null);
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <span className={s.muted}>Calls to the Agent Gateway made from this studio. Latency, failures and models.</span>
        <button type="button" className={s.btnGhost} onClick={clearLog} disabled={traces.length === 0}>
          Clear log
        </button>
      </div>

      <div className={s.toolbar}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <select className={s.select} value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)} aria-label="Agent">
            <option value="all">All agents</option>
            {agentOptions.map(([id, name]) => (
              <option key={id} value={id}>{name}</option>
            ))}
          </select>
        </div>
        <PillTabs<SourceFilter>
          value={sourceFilter}
          onChange={setSourceFilter}
          options={[
            { value: 'all', label: 'All' },
            { value: 'evaluation', label: 'Evaluation runs' },
            { value: 'probe', label: 'Probes' },
          ]}
        />
      </div>

      <div className={s.metrics}>
        <Metric label="Calls" value={String(metrics.calls)} />
        <Metric label="Failure rate" value={metrics.calls ? formatPercent(metrics.failureRate) : '—'} />
        <Metric label="Guardrail blocks" value={String(metrics.blocked)} />
        <Metric label="Latency p50" value={formatMs(metrics.p50Ms)} />
        <Metric label="Latency p95" value={formatMs(metrics.p95Ms)} />
        <Metric label="Screened replies" value={metrics.calls ? formatPercent(metrics.screenedRate) : '—'} />
      </div>

      {metrics.models.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <span className={s.muted}>Models that answered: </span>
          {metrics.models.map((m) => (
            <span key={m.model} className={s.tag}>{m.model} × {m.count}</span>
          ))}
        </div>
      )}

      <div className={s.card} style={{ marginBottom: 20 }}>
        <h2 style={{ marginTop: 0, fontSize: 18 }}>Send a probe</h2>
        {agents.data && agents.data.length === 0 ? (
          <span className={s.muted}>Create an agent first.</span>
        ) : (
          <form
            style={{ display: 'grid', gap: 10 }}
            onSubmit={(e) => {
              e.preventDefault();
              void sendProbe();
            }}
          >
            <div style={{ display: 'flex', gap: 10 }}>
              <select
                className={s.select}
                value={selectedProbeAgent?.id ?? ''}
                onChange={(e) => setProbeAgentId(e.target.value)}
                aria-label="Probe agent"
              >
                {(agents.data ?? []).map((a) => (
                  <option key={a.id} value={a.id}>{a.name} · {a.status}</option>
                ))}
              </select>
              <input
                className={s.input}
                style={{ flex: 1 }}
                value={probePrompt}
                onChange={(e) => setProbePrompt(e.target.value)}
                placeholder="Prompt to send through the gateway"
              />
              <button type="submit" className={s.btnPrimary} disabled={!selectedProbeAgent || sending || !probePrompt.trim()}>
                {sending ? 'Sending…' : 'Send'}
              </button>
            </div>
            <span className={s.muted}>
              The gateway only answers deployed agents. A probe to any other agent is logged as a failure.
            </span>
          </form>
        )}
      </div>

      {visible.length === 0 ? (
        <EmptyState>
          {traces.length === 0
            ? 'No calls yet. Send a probe or run an evaluation suite to see calls here.'
            : 'No calls match these filters.'}
        </EmptyState>
      ) : (
        <table className={s.table}>
          <thead>
            <tr>
              <th>Time</th>
              <th>Agent</th>
              <th>Source</th>
              <th>Status</th>
              <th>Model</th>
              <th>Latency</th>
              <th>Prompt</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((trace) => (
              <Fragment key={trace.id}>
                <tr
                  className={s.clickableRow}
                  onClick={() => setExpandedId(expandedId === trace.id ? null : trace.id)}
                  aria-expanded={expandedId === trace.id}
                >
                  <td className={s.muted}>{formatDate(trace.startedAt)}</td>
                  <td>{trace.agentName}</td>
                  <td className={s.muted}>{SOURCE_LABELS[trace.source]}</td>
                  <td><StatusBadge status={statusOf(trace)} /></td>
                  <td className={s.muted}>{trace.model ?? '—'}</td>
                  <td className={s.muted}>{formatMs(trace.durationMs)}</td>
                  <td className={s.muted}>{trace.prompt.length > 60 ? `${trace.prompt.slice(0, 60)}…` : trace.prompt}</td>
                </tr>
                {expandedId === trace.id && (
                  <tr>
                    <td colSpan={7} className={s.detail}>
                      <TraceDetail trace={trace} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className={s.metric}>
      <div className={s.metricValue}>{value}</div>
      <div className={s.metricLabel}>{label}</div>
    </div>
  );
}

function TraceDetail({ trace }: { trace: CallTrace }) {
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      <div><span className={s.muted}>Prompt</span><pre className={s.pre}>{trace.prompt}</pre></div>
      {trace.ok ? (
        <div><span className={s.muted}>Reply</span><pre className={s.pre}>{trace.reply}</pre></div>
      ) : (
        <div><span className={s.muted}>Error</span><pre className={s.pre}>{trace.error}</pre></div>
      )}
      <div className={s.muted}>
        Complexity: {trace.complexity ?? '—'} · Screened: {trace.screened === null ? '—' : trace.screened ? 'yes' : 'no'}
      </div>
    </div>
  );
}
