import { describe, expect, it } from 'vitest';
import { caseProblem, judge, summarizeRun, type EvalCase, type EvalResult } from './evaluation';

const check = (overrides: Partial<EvalCase>): EvalCase => ({
  id: 'c1',
  input: 'How do I get a refund?',
  kind: 'contains',
  value: 'refund',
  ...overrides,
});

describe('judge', () => {
  it('matches contains regardless of case', () => {
    expect(judge('Refunds take 5 days', check({ value: 'refund' }))).toBe(true);
  });

  it('inverts for not_contains', () => {
    expect(judge('Please call support', check({ kind: 'not_contains', value: 'password' }))).toBe(true);
    expect(judge('Your PASSWORD is', check({ kind: 'not_contains', value: 'password' }))).toBe(false);
  });

  it('matches regex case-insensitively', () => {
    expect(judge('Order #4521 shipped', check({ kind: 'regex', value: 'order #\\d{4}' }))).toBe(true);
    expect(judge('No order number', check({ kind: 'regex', value: '#\\d+' }))).toBe(false);
  });
});

describe('caseProblem', () => {
  it('accepts a complete case', () => {
    expect(caseProblem(check({}))).toBeNull();
  });

  it('flags an empty input or expected text', () => {
    expect(caseProblem(check({ input: '  ' }))).toBe('Input is empty');
    expect(caseProblem(check({ value: '' }))).toBe('Expected text is empty');
  });

  it('flags a regex that does not compile', () => {
    expect(caseProblem(check({ kind: 'regex', value: '([' }))).toBe('Not a valid regular expression');
  });
});

describe('summarizeRun', () => {
  it('counts passes and returns no pass rate for an empty run', () => {
    expect(summarizeRun([])).toEqual({ total: 0, passed: 0, failed: 0, passRate: null });
  });

  it('computes the pass rate', () => {
    const results: EvalResult[] = [
      { caseId: 'a', traceId: 't1', passed: true, durationMs: 90, reply: 'ok', error: null },
      { caseId: 'b', traceId: 't2', passed: false, durationMs: 120, reply: 'no', error: null },
      { caseId: 'c', traceId: 't3', passed: false, durationMs: 0, reply: null, error: 'down' },
      { caseId: 'd', traceId: 't4', passed: true, durationMs: 80, reply: 'yes', error: null },
    ];
    expect(summarizeRun(results)).toEqual({ total: 4, passed: 2, failed: 2, passRate: 0.5 });
  });
});
