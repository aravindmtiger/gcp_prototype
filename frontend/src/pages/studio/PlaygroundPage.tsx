import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../../api';
import { ErrorBanner, PageHeader, messageOf, studioStyles as s } from '../../studio/ui';
import type { Agent, Deployment } from '../../types';
import styles from './PlaygroundPage.module.css';

interface Turn {
  role: 'user' | 'agent';
  text: string;
  at: string;
}

interface ChoiceRequest {
  interruptId: string;
  functionCallEventId?: string;
  message: string;
  choices: string[];
}

interface AdkEvent {
  id?: string;
  content?: {
    parts?: {
      text?: string;
      functionCall?: {
        id?: string;
        name?: string;
        args?: Record<string, unknown>;
      };
    }[];
  };
  partial?: boolean;
  turnComplete?: boolean;
  actions?: { endOfAgent?: boolean };
}

const clock = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });

function choiceRequest(events: AdkEvent[]): ChoiceRequest | null {
  for (const event of events) {
    for (const part of event.content?.parts ?? []) {
      const call = part.functionCall;
      if (!call || !call.name?.includes('request_input')) continue;
      const args = call.args ?? {};
      const payload = args.payload as { choices?: unknown } | undefined;
      const choices = Array.isArray(payload?.choices)
        ? payload.choices.filter((choice): choice is string => typeof choice === 'string')
        : [];
      const interruptId = String(args.interruptId ?? call.id ?? '');
      if (!interruptId || choices.length === 0) {
        throw new Error('The agent requested human input without valid choice options.');
      }
      return {
        interruptId,
        functionCallEventId: event.id,
        message: typeof args.message === 'string' ? args.message : 'Choose how to continue.',
        choices,
      };
    }
  }
  return null;
}

function answerText(events: AdkEvent[]): string {
  const finalTexts = events
    .filter((event) => !event.partial)
    .flatMap((event) => (event.content?.parts ?? []).map((part) => part.text ?? '').filter(Boolean));
  if (finalTexts.length) return finalTexts[finalTexts.length - 1];
  return events.flatMap((event) => (event.content?.parts ?? []).map((part) => part.text ?? '')).join('');
}

/** Chat with an ADK deployment, preserving its session for normal turns and HITL resumes. */
export function PlaygroundPage() {
  const { agentId } = useParams();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [deployment, setDeployment] = useState<Deployment | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [choice, setChoice] = useState<ChoiceRequest | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const endpoint = deployment?.endpoint_url ?? null;

  useEffect(() => {
    if (!agentId) return;
    Promise.all([api.getAgent(agentId), api.listDeployments(agentId)])
      .then(([loaded, deployments]: [Agent, Deployment[]]) => {
        setAgent(loaded);
        const live = deployments.find((item) => item.status === 'succeeded' && item.endpoint_url);
        setDeployment(live ?? null);
      })
      .catch((err: unknown) => setError(messageOf(err)));
  }, [agentId]);

  useEffect(() => {
    setSessionId(null);
    setChoice(null);
    setTurns([]);
  }, [agentId, endpoint]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' });
  }, [turns, sending, choice]);

  const createSession = async (): Promise<string> => {
    if (!agentId) throw new Error('No agent was selected.');
    const created = await api.createPlaygroundSession(agentId);
    setSessionId(created.session_id);
    return created.session_id;
  };

  const invoke = async (
    input: { message?: string; choice?: string; interrupt_id?: string },
    functionCallEventId?: string,
  ): Promise<AdkEvent[]> => {
    if (!agentId || !deployment?.endpoint_url) throw new Error('No successful deployment is available.');
    const id = sessionId ?? await createSession();
    const result = await api.runPlayground(agentId, {
      session_id: id,
      ...input,
      ...(functionCallEventId ? { function_call_event_id: functionCallEventId } : {}),
    });
    return result.events as AdkEvent[];
  };

  const appendAgentReply = (events: AdkEvent[]) => {
    const pending = choiceRequest(events);
    if (pending) {
      setChoice(pending);
      setTurns((current) => [...current, { role: 'agent', text: pending.message, at: new Date().toISOString() }]);
      return;
    }
    const text = answerText(events);
    if (text) setTurns((current) => [...current, { role: 'agent', text, at: new Date().toISOString() }]);
  };

  const send = async () => {
    const message = draft.trim();
    if (!message || !endpoint || sending || choice) return;
    setDraft('');
    setTurns((current) => [...current, { role: 'user', text: message, at: new Date().toISOString() }]);
    setSending(true);
    setError(null);
    try {
      const events = await invoke({ message });
      appendAgentReply(events);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSending(false);
    }
  };

  const resume = async (selected: string) => {
    if (!choice || sending) return;
    const request = choice;
    setChoice(null);
    setTurns((current) => [...current, { role: 'user', text: selected, at: new Date().toISOString() }]);
    setSending(true);
    setError(null);
    try {
      const events = await invoke(
        { choice: selected, interrupt_id: request.interruptId },
        request.functionCallEventId,
      );
      appendAgentReply(events);
    } catch (err) {
      setChoice(request);
      setError(messageOf(err));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className={s.page}>
      <PageHeader title={`Playground: ${agent?.name ?? ''}`} subtitle={endpoint ?? 'No successful deployment yet.'} />
      <ErrorBanner message={error} />
      <div className={styles.panel}>
        <div ref={logRef} className={styles.log}>
          {turns.length === 0 && (
            <div className={styles.empty}>
              <strong>{endpoint ? 'Start the conversation' : 'Not deployed yet'}</strong>
              <span>{endpoint ? 'Messages use an ADK session. Human review choices appear here.' : 'Deploy the agent to chat with it here.'}</span>
            </div>
          )}
          {turns.map((turn, index) => {
            const mine = turn.role === 'user';
            return (
              <div key={index} className={`${styles.row} ${mine ? styles.rowUser : ''}`}>
                <div className={`${styles.avatar} ${mine ? styles.avatarUser : styles.avatarAgent}`} aria-hidden="true">
                  {mine ? 'You' : 'AI'}
                </div>
                <div className={styles.column}>
                  <div className={`${styles.bubble} ${mine ? styles.bubbleUser : styles.bubbleAgent}`}>{turn.text}</div>
                  <span className={styles.meta}>{clock(turn.at)}</span>
                </div>
              </div>
            );
          })}
          {choice && (
            <div className={styles.choicePanel} role="group" aria-label="Choose a workflow path">
              {choice.choices.map((option) => (
                <button key={option} type="button" disabled={sending} onClick={() => void resume(option)}>
                  {option}
                </button>
              ))}
            </div>
          )}
          {sending && (
            <div className={styles.row}>
              <div className={`${styles.avatar} ${styles.avatarAgent}`} aria-hidden="true">AI</div>
              <div className={`${styles.bubble} ${styles.bubbleAgent} ${styles.typing}`} aria-label="Agent is replying">
                <span />
                <span />
                <span />
              </div>
            </div>
          )}
        </div>
        <form
          className={styles.composer}
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <input
            className={styles.input}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={endpoint ? (choice ? 'Choose a path above to continue' : 'Message the agent') : 'Deploy the agent first'}
            disabled={!endpoint || sending || Boolean(choice)}
            aria-label="Message"
          />
          <button type="submit" className={styles.send} disabled={!endpoint || sending || Boolean(choice) || !draft.trim()}>
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
