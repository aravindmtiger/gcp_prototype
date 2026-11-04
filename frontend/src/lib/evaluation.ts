/**
 * Evaluation suites: test cases checked against the replies of a deployed agent.
 * Pure: the storage and the gateway calls live elsewhere.
 */

export type CheckKind = 'contains' | 'not_contains' | 'regex';

export const CHECK_LABELS: Record<CheckKind, string> = {
  contains: 'Reply contains',
  not_contains: 'Reply does not contain',
  regex: 'Reply matches regex',
};

export interface EvalCase {
  id: string;
  input: string;
  kind: CheckKind;
  value: string;
}

/** One ADK evaluation criterion, as configured in the criteria panel. */
export interface Criterion {
  key: string;
  enabled: boolean;
  threshold: number;
  rubrics: string[];
}

export interface EvalSuite {
  id: string;
  name: string;
  agentId: string;
  cases: EvalCase[];
  criteria?: Criterion[];
  updatedAt: string;
}

export interface EvalResult {
  caseId: string;
  traceId: string;
  passed: boolean;
  durationMs: number;
  reply: string | null;
  error: string | null;
}

/** Returns why a case cannot be saved or run, or null when it is complete. */
export function caseProblem(check: EvalCase): string | null {
  if (!check.input.trim()) return 'Input is empty';
  if (!check.value.trim()) return 'Expected text is empty';
  if (check.kind === 'regex') {
    try {
      new RegExp(check.value);
    } catch {
      return 'Not a valid regular expression';
    }
  }
  return null;
}

/** Checks one reply. Matching ignores case so that "Refund" and "refund" are the same answer. */
export function judge(reply: string, check: EvalCase): boolean {
  const text = reply.toLowerCase();
  const expected = check.value.toLowerCase();
  switch (check.kind) {
    case 'contains':
      return text.includes(expected);
    case 'not_contains':
      return !text.includes(expected);
    case 'regex':
      return new RegExp(check.value, 'i').test(reply);
  }
}

export function summarizeRun(results: EvalResult[]) {
  const passed = results.filter((r) => r.passed).length;
  return {
    total: results.length,
    passed,
    failed: results.length - passed,
    passRate: results.length ? passed / results.length : null,
  };
}
