import { ApiError, api } from '../api';
import { readJson, writeJson } from './storage';
import { currentEmail } from './user';
import type { CallTrace, TraceSource } from './traces';

// The newest calls come first. The cap keeps the browser storage small.
const MAX_TRACES = 200;
const storageKey = () => `af.gateway-traces:${currentEmail()}`;

export function loadTraces(): CallTrace[] {
  return readJson<CallTrace[]>(storageKey(), []);
}

export function clearTraces(): void {
  writeJson(storageKey(), []);
}

/**
 * Sends one prompt through the Agent Gateway and records the call.
 * Never throws: a failed call comes back as a trace with ok=false.
 */
export async function promptAgentTraced(
  agent: { id: string; name: string },
  prompt: string,
  source: TraceSource,
): Promise<CallTrace> {
  const startedAt = new Date().toISOString();
  const started = performance.now();
  const result = await api.promptAgent(agent.id, prompt).then(
    (reply) => ({ ok: true as const, reply }),
    (err: unknown) => ({ ok: false as const, err }),
  );
  const durationMs = Math.round(performance.now() - started);

  const base = {
    id: crypto.randomUUID(),
    agentId: agent.id,
    agentName: agent.name,
    source,
    prompt,
    startedAt,
    durationMs,
  };
  const trace: CallTrace = result.ok
    ? {
        ...base,
        ok: true,
        blocked: false,
        reply: result.reply.text,
        model: result.reply.model,
        complexity: result.reply.complexity,
        screened: result.reply.screened,
        error: null,
      }
    : {
        ...base,
        ok: false,
        // The gateway answers 403 when the agent's guardrail stops the prompt.
        blocked: result.err instanceof ApiError && result.err.status === 403,
        reply: null,
        model: null,
        complexity: null,
        screened: null,
        error: result.err instanceof Error ? result.err.message : 'Something went wrong',
      };

  writeJson(storageKey(), [trace, ...loadTraces()].slice(0, MAX_TRACES));
  return trace;
}
