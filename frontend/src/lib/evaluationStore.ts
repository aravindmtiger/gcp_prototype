import type { EvalSuite } from './evaluation';
import { readJson, writeJson } from './storage';
import { currentEmail } from './user';

// Suites live in this browser only, one list per signed-in user.
const storageKey = () => `af.eval-suites:${currentEmail()}`;

export function loadSuites(): EvalSuite[] {
  return readJson<EvalSuite[]>(storageKey(), []);
}

export function saveSuites(suites: EvalSuite[]): void {
  writeJson(storageKey(), suites);
}
