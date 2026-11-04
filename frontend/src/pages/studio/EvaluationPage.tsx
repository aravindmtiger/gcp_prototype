import { useEffect, useState } from 'react';
import { api } from '../../api';
import { CHECK_LABELS, caseProblem, judge, summarizeRun, type CheckKind, type Criterion, type EvalCase, type EvalResult, type EvalSuite } from '../../lib/evaluation';
import { CriteriaPanel } from './CriteriaPanel';
import { loadSuites, saveSuites } from '../../lib/evaluationStore';
import { promptAgentTraced } from '../../lib/gatewayTraces';
import { EmptyState, ErrorBanner, PageHeader, StatusBadge, useLoad, studioStyles as s } from '../../studio/ui';

const blankCase = (): EvalCase => ({ id: crypto.randomUUID(), input: '', kind: 'contains', value: '' });

function firstProblem(cases: EvalCase[]): string | null {
  for (const [index, check] of cases.entries()) {
    const problem = caseProblem(check);
    if (problem) return `Case ${index + 1}: ${problem}`;
  }
  return null;
}

/**
 * Runs a suite against a deployed agent through the Agent Gateway. Each reply is checked
 * against its expectation. Every call is also recorded in Observability.
 */
export function EvaluationPage() {
  const agents = useLoad(() => api.listAgents());
  const [suites, setSuites] = useState<EvalSuite[]>(() => loadSuites());
  const [agentId, setAgentId] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [cases, setCases] = useState<EvalCase[]>([blankCase()]);
  const [criteria, setCriteria] = useState<Criterion[]>([]);
  const [runCases, setRunCases] = useState<EvalCase[]>([]);
  const [results, setResults] = useState<EvalResult[] | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!agentId && agents.data?.length) setAgentId(agents.data[0].id);
  }, [agents.data, agentId]);

  const agent = agents.data?.find((a) => a.id === agentId);
  const agentSuites = suites.filter((suite) => suite.agentId === agentId);

  const resetDraft = () => {
    setSelectedId(null);
    setName('');
    setCases([blankCase()]);
    setCriteria([]);
    setResults(null);
    setError(null);
  };

  const chooseAgent = (id: string) => {
    setAgentId(id);
    resetDraft();
  };

  const openSuite = (suite: EvalSuite) => {
    setSelectedId(suite.id);
    setName(suite.name);
    setCases(suite.cases);
    setCriteria(suite.criteria ?? []);
    setResults(null);
    setError(null);
  };

  const updateCase = (id: string, patch: Partial<EvalCase>) => {
    setCases((current) => current.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  };

  const saveSuite = () => {
    if (!name.trim()) return setError('Give the suite a name');
    const problem = firstProblem(cases);
    if (problem) return setError(problem);
    if (!agent) return setError('Choose an agent');

    const now = new Date().toISOString();
    const suite: EvalSuite = {
      id: selectedId ?? crypto.randomUUID(),
      name: name.trim(),
      agentId: agent.id,
      cases,
      criteria: criteria.filter((c) => c.enabled),
      updatedAt: now,
    };
    const next = selectedId ? suites.map((s) => (s.id === selectedId ? suite : s)) : [suite, ...suites];
    saveSuites(next);
    setSuites(next);
    setSelectedId(suite.id);
    setError(null);
  };

  const deleteSuite = () => {
    if (!selectedId || !window.confirm(`Delete the suite "${name}"?`)) return;
    const next = suites.filter((s) => s.id !== selectedId);
    saveSuites(next);
    setSuites(next);
    resetDraft();
  };

  const runSuite = async () => {
    if (!agent || running) return;
    const problem = firstProblem(cases);
    if (problem) return setError(problem);

    setError(null);
    setRunning(true);
    setRunCases(cases);
    setResults([]);

    const collected: EvalResult[] = [];
    for (const check of cases) {
      const trace = await promptAgentTraced({ id: agent.id, name: agent.name }, check.input, 'evaluation');
      collected.push({
        caseId: check.id,
        traceId: trace.id,
        passed: trace.ok && judge(trace.reply ?? '', check),
        durationMs: trace.durationMs,
        reply: trace.reply,
        error: trace.error,
      });
      setResults([...collected]);
    }
    setRunning(false);
  };

  const summary = results ? summarizeRun(results) : null;
  const passRate = summary?.passRate;

  return (
    <div className={s.page}>
      <PageHeader
        title="Evaluation"
        subtitle="Test a deployed agent and check each reply."
      />

      <div className={s.toolbar}>
        <select
          className={s.select}
          value={agentId}
          onChange={(e) => chooseAgent(e.target.value)}
          aria-label="Agent"
          disabled={!agents.data?.length}
        >
          {(agents.data ?? []).map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
        {agent && <StatusBadge status={agent.status} />}
      </div>

      <ErrorBanner message={error ?? agents.error} />
      {agent && agent.status !== 'deployed' && (
        <div className={s.notice} style={{ marginBottom: 16 }}>
          This agent is not deployed. The gateway only answers deployed agents, so every case will fail until it is deployed.
        </div>
      )}

      {agents.data && agents.data.length === 0 ? (
        <EmptyState>Create an agent in Agent Studio before you write evaluation suites.</EmptyState>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '240px minmax(0, 1fr)', gap: 18, alignItems: 'start' }}>
          <div className={s.card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <strong>Suites</strong>
              <button type="button" className={s.btnGhost} onClick={resetDraft}>New suite</button>
            </div>
            {agentSuites.length === 0 ? (
              <span className={s.muted}>No suites for this agent yet.</span>
            ) : (
              <ul className={s.suiteList}>
                {agentSuites.map((suite) => (
                  <li key={suite.id}>
                    <button
                      type="button"
                      className={`${s.suiteItem} ${suite.id === selectedId ? s.suiteItemActive : ''}`}
                      onClick={() => openSuite(suite)}
                    >
                      {suite.name}
                      <div className={s.muted}>{suite.cases.length} case{suite.cases.length === 1 ? '' : 's'}</div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div style={{ display: 'grid', gap: 18 }}>
            <div className={s.card}>
              <div className={s.form}>
                <label className={s.field}>
                  Suite name
                  <input className={s.input} value={name} onChange={(e) => setName(e.target.value)} placeholder="Refund questions" />
                </label>

                {cases.map((check, index) => (
                  <CaseRow
                    key={check.id}
                    index={index}
                    check={check}
                    onChange={(patch) => updateCase(check.id, patch)}
                    onRemove={cases.length > 1 ? () => setCases((current) => current.filter((c) => c.id !== check.id)) : undefined}
                  />
                ))}

                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button type="button" className={s.btnGhost} onClick={() => setCases((current) => [...current, blankCase()])}>
                    Add case
                  </button>
                  <button type="button" className={s.btnGhost} onClick={saveSuite}>Save suite</button>
                  {selectedId && (
                    <button type="button" className={s.btnDanger} onClick={deleteSuite}>Delete suite</button>
                  )}
                  <button
                    type="button"
                    className={s.btnPrimary}
                    style={{ marginLeft: 'auto' }}
                    onClick={() => void runSuite()}
                    disabled={!agent || running}
                  >
                    {running ? `Running ${results?.length ?? 0} of ${cases.length}…` : 'Run suite'}
                  </button>
                </div>
              </div>
            </div>

            <div className={s.card}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
                <strong>Criteria</strong>
                <span className={s.muted}>Scored by ADK when the suite runs. The ADK runner is not connected yet.</span>
              </div>
              <CriteriaPanel value={criteria} onChange={setCriteria} />
            </div>

            {results && (
              <div>
                {summary && (
                  <div className={s.metrics}>
                    <Metric label="Pass rate" value={passRate === null || passRate === undefined ? '—' : `${Math.round(passRate * 100)}%`} />
                    <Metric label="Passed" value={`${summary.passed} of ${summary.total}`} />
                    <Metric label="Failed" value={String(summary.failed)} />
                  </div>
                )}
                {results.length === 0 ? null : (
                  <table className={s.table}>
                    <thead>
                      <tr>
                        <th>Input</th>
                        <th>Check</th>
                        <th>Result</th>
                        <th>Reply or error</th>
                        <th>Latency</th>
                      </tr>
                    </thead>
                    <tbody>
                      {results.map((result, index) => {
                        const check = runCases[index];
                        return (
                          <tr key={result.caseId}>
                            <td>{check?.input}</td>
                            <td className={s.muted}>
                              {check && `${CHECK_LABELS[check.kind]}: “${check.value}”`}
                            </td>
                            <td><StatusBadge status={result.passed ? 'passed' : 'failed'} /></td>
                            <td className={s.muted} style={{ whiteSpace: 'pre-wrap' }}>{result.reply ?? result.error}</td>
                            <td className={s.muted}>{result.durationMs} ms</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </div>
        </div>
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

function CaseRow({
  index,
  check,
  onChange,
  onRemove,
}: {
  index: number;
  check: EvalCase;
  onChange: (patch: Partial<EvalCase>) => void;
  onRemove?: () => void;
}) {
  return (
    <div className={s.card} style={{ padding: 14, display: 'grid', gap: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <strong>Case {index + 1}</strong>
        {onRemove && <button type="button" className={s.iconButton} onClick={onRemove} aria-label={`Remove case ${index + 1}`}>Remove</button>}
      </div>
      <textarea
        className={s.textarea}
        value={check.input}
        onChange={(e) => onChange({ input: e.target.value })}
        placeholder="Message sent to the agent"
        aria-label={`Input for case ${index + 1}`}
      />
      <div style={{ display: 'flex', gap: 8 }}>
        <select
          className={s.select}
          value={check.kind}
          onChange={(e) => onChange({ kind: e.target.value as CheckKind })}
          aria-label={`Check for case ${index + 1}`}
        >
          {(Object.keys(CHECK_LABELS) as CheckKind[]).map((kind) => (
            <option key={kind} value={kind}>{CHECK_LABELS[kind]}</option>
          ))}
        </select>
        <input
          className={s.input}
          style={{ flex: 1 }}
          value={check.value}
          onChange={(e) => onChange({ value: e.target.value })}
          placeholder={check.kind === 'regex' ? 'Pattern, for example order #\\d+' : 'Text to look for'}
          aria-label={`Expected text for case ${index + 1}`}
        />
      </div>
    </div>
  );
}
