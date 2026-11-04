import { describe, expect, it } from 'vitest';
import { percentile, summarize, type CallTrace } from './traces';

const trace = (overrides: Partial<CallTrace>): CallTrace => ({
  id: 'x',
  agentId: 'a1',
  agentName: 'Support',
  source: 'probe',
  prompt: 'hi',
  startedAt: '2026-11-02T10:00:00.000Z',
  durationMs: 100,
  ok: true,
  blocked: false,
  reply: 'hello',
  model: 'gemini-2.5-flash',
  complexity: 'simple',
  screened: true,
  error: null,
  ...overrides,
});

describe('percentile', () => {
  it('uses the nearest rank', () => {
    const sorted = [10, 20, 30, 40];
    expect(percentile(sorted, 50)).toBe(20);
    expect(percentile(sorted, 95)).toBe(40);
  });

  it('returns null when there are no calls', () => {
    expect(percentile([], 50)).toBeNull();
  });
});

describe('summarize', () => {
  it('reports zeros for an empty log', () => {
    expect(summarize([])).toEqual({
      calls: 0,
      failures: 0,
      blocked: 0,
      failureRate: 0,
      screenedRate: 0,
      p50Ms: null,
      p95Ms: null,
      models: [],
    });
  });

  it('counts failures, guardrail blocks, and model use', () => {
    const summary = summarize([
      trace({ durationMs: 100 }),
      trace({ durationMs: 300, model: 'claude-sonnet' }),
      trace({ ok: false, blocked: true, reply: null, model: null, screened: null, error: 'blocked' }),
      trace({ ok: false, blocked: false, reply: null, model: null, screened: null, error: 'boom', durationMs: 500 }),
    ]);

    expect(summary.calls).toBe(4);
    expect(summary.failures).toBe(2);
    expect(summary.blocked).toBe(1);
    expect(summary.failureRate).toBe(0.5);
    expect(summary.screenedRate).toBe(1);
    expect(summary.p50Ms).toBe(100);
    expect(summary.models).toEqual([
      { model: 'gemini-2.5-flash', count: 1 },
      { model: 'claude-sonnet', count: 1 },
    ]);
  });
});
