/**
 * One Agent Gateway call as the studio saw it. Pure: no storage or network access here,
 * so the summaries can be unit tested without a browser.
 */

export type TraceSource = 'evaluation' | 'probe';

export interface CallTrace {
  id: string;
  agentId: string;
  agentName: string;
  source: TraceSource;
  prompt: string;
  startedAt: string;
  durationMs: number;
  ok: boolean;
  blocked: boolean;
  reply: string | null;
  model: string | null;
  complexity: string | null;
  screened: boolean | null;
  error: string | null;
}

export interface TraceSummary {
  calls: number;
  failures: number;
  blocked: number;
  failureRate: number;
  screenedRate: number;
  p50Ms: number | null;
  p95Ms: number | null;
  models: { model: string; count: number }[];
}

/** Nearest-rank percentile of an ascending-sorted list. */
export function percentile(sorted: number[], p: number): number | null {
  if (sorted.length === 0) return null;
  const rank = Math.min(sorted.length, Math.max(1, Math.ceil((p / 100) * sorted.length)));
  return sorted[rank - 1];
}

export function summarize(traces: CallTrace[]): TraceSummary {
  const calls = traces.length;
  const failures = traces.filter((t) => !t.ok).length;
  const answered = traces.filter((t) => t.ok);
  const screened = answered.filter((t) => t.screened).length;

  const modelCounts = new Map<string, number>();
  for (const trace of answered) {
    if (trace.model) modelCounts.set(trace.model, (modelCounts.get(trace.model) ?? 0) + 1);
  }

  const durations = traces.map((t) => t.durationMs).sort((a, b) => a - b);

  return {
    calls,
    failures,
    blocked: traces.filter((t) => t.blocked).length,
    failureRate: calls ? failures / calls : 0,
    screenedRate: answered.length ? screened / answered.length : 0,
    p50Ms: percentile(durations, 50),
    p95Ms: percentile(durations, 95),
    models: [...modelCounts]
      .map(([model, count]) => ({ model, count }))
      .sort((a, b) => b.count - a.count),
  };
}
