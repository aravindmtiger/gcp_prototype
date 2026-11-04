import { describe, expect, it } from 'vitest';
import { AGENT_NAME_PATTERN, canvasProblems, nextNodeId, parseDrop } from './canvas';
import type { WorkflowNode } from '../types';

const node = (id: string, tool: WorkflowNode['tool'], config: Record<string, string> = {}): WorkflowNode => ({
  id,
  tool,
  system_prompt: '',
  config,
});

describe('nextNodeId', () => {
  it('never reuses an id already on the canvas', () => {
    const nodes = [node('web_search_2', 'web_search')];
    expect(nextNodeId('web_search', nodes)).toBe('web_search_1');
    const id = nextNodeId('web_search', [node('web_search_1', 'web_search'), node('web_search_2', 'web_search')]);
    expect(id).toBe('web_search_3');
  });
});

describe('parseDrop', () => {
  it('reads a palette entry and rejects junk', () => {
    expect(parseDrop('{"tool":"web_search","label":"Web","config":{}}')?.tool).toBe('web_search');
    expect(parseDrop('not json')).toBeNull();
  });
});

describe('agent name pattern', () => {
  it('accepts identity-safe names only', () => {
    expect(AGENT_NAME_PATTERN.test('policy_agent-1')).toBe(true);
    expect(AGENT_NAME_PATTERN.test('1agent')).toBe(false);
    expect(AGENT_NAME_PATTERN.test('ab')).toBe(false);
    expect(AGENT_NAME_PATTERN.test('has space')).toBe(false);
  });
});

describe('canvasProblems', () => {
  it('reports missing description, empty canvas and unset tool sources', () => {
    const problems = canvasProblems('policy_agent', '', []);
    expect(problems).toContain('Add a description');
    expect(problems).toContain('Drag at least one tool onto the canvas');
    const missing = canvasProblems('policy_agent', 'ok', [node('kb_1', 'knowledge_retriever')]);
    expect(missing).toEqual(['kb_1: choose a knowledge source']);
  });

  it('is empty when the canvas is ready', () => {
    expect(canvasProblems('policy_agent', 'Answers', [node('web_search_1', 'web_search')])).toEqual([]);
  });
});
