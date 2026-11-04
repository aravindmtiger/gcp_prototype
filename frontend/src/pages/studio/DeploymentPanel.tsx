import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { ErrorBanner, StatusBadge, formatDate, messageOf, studioStyles as s } from '../../studio/ui';
import type { Agent, DeployTarget, Deployment } from '../../types';

const TERMINAL = new Set(['succeeded', 'failed']);

const SESSION_OPTIONS = [
  { value: 'vertex_ai_session', label: 'Vertex AI Agent Engine sessions' },
  { value: 'in_memory', label: 'In-memory' },
];

const MEMORY_OPTIONS = [
  { value: 'vertex_ai_memory_bank', label: 'Vertex AI Memory Bank' },
  { value: 'none', label: 'No long-term memory' },
];

/** Deployment dialog, shown after approval. Deploy is disabled until the agent is approved. */
export function DeploymentPanel({ agent, onChanged }: { agent: Agent; onChanged: () => void }) {
  const [target, setTarget] = useState<DeployTarget>('cloud_run');
  const [sessionBackend, setSessionBackend] = useState(SESSION_OPTIONS[0].value);
  const [memoryBackend, setMemoryBackend] = useState(MEMORY_OPTIONS[0].value);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    api
      .listDeployments(agent.id)
      .then((list) => mounted.current && setDeployments(list))
      .catch((err: unknown) => mounted.current && setError(messageOf(err)));
    return () => {
      mounted.current = false;
    };
  }, [agent.id]);

  const latest = deployments[0];
  const canDeploy = agent.status === 'approved' && !busy;

  const deploy = async () => {
    setBusy(true);
    setError(null);
    try {
      let current = await api.createDeployment(agent.id, target, sessionBackend, memoryBackend);
      setDeployments((list) => [current, ...list]);
      while (!TERMINAL.has(current.status)) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        current = await api.getDeployment(current.id);
        if (!mounted.current) return;
        setDeployments((list) => [current, ...list.filter((d) => d.id !== current.id)]);
      }
      if (current.status === 'failed') setError(current.error ?? 'Deployment failed');
      onChanged();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={s.card} style={{ display: 'grid', gap: 14 }}>
      <h3 style={{ margin: 0 }}>Deployment</h3>
      {agent.status !== 'approved' && agent.status !== 'deployed' && (
        <p className={s.muted}>Deployment unlocks after an approver approves this agent.</p>
      )}

      <div className={s.form}>
        <label className={s.field}>
          Target
          <select className={s.select} value={target} onChange={(e) => setTarget(e.target.value as DeployTarget)} disabled={!canDeploy}>
            <option value="cloud_run">Cloud Run service with its own URL</option>
            <option value="agent_engine">Vertex AI Agent Engine</option>
          </select>
        </label>
        <label className={s.field}>
          Session
          <select className={s.select} value={sessionBackend} onChange={(e) => setSessionBackend(e.target.value)} disabled={!canDeploy}>
            {SESSION_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
        <label className={s.field}>
          Memory
          <select className={s.select} value={memoryBackend} onChange={(e) => setMemoryBackend(e.target.value)} disabled={!canDeploy}>
            {MEMORY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
        <button type="button" className={s.btnPrimary} disabled={!canDeploy} onClick={deploy}>
          {busy ? 'Deploying…' : 'Deploy agent'}
        </button>
      </div>

      <ErrorBanner message={error} />

      {latest && (
        <div style={{ display: 'grid', gap: 6, fontSize: 14 }}>
          <div>
            Latest deployment: <StatusBadge status={latest.status} /> <span className={s.muted}>{formatDate(latest.created_at)}</span>
          </div>
          {latest.endpoint_url && <div>Endpoint: <code>{latest.endpoint_url}</code></div>}
          {latest.agent_identity && <div>Agent identity: <code>{latest.agent_identity}</code></div>}
          {latest.status === 'succeeded' && agent.status === 'deployed' && (
            <Link to={`/agents/${agent.id}/playground`} className={s.btnPrimary} style={{ textDecoration: 'none', justifySelf: 'start' }}>
              Run playground
            </Link>
          )}
        </div>
      )}
    </section>
  );
}
