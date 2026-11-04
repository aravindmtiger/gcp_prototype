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

const clock = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });

/**
 * Chat with a deployed agent. Sends each message to the deployment's endpoint URL.
 * The request body shape is {"message": "..."}; the deployed service has to accept it.
 */
export function PlaygroundPage() {
  const { agentId } = useParams();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [endpoint, setEndpoint] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!agentId) return;
    Promise.all([api.getAgent(agentId), api.listDeployments(agentId)])
      .then(([loaded, deployments]: [Agent, Deployment[]]) => {
        setAgent(loaded);
        const live = deployments.find((d) => d.status === 'succeeded' && d.endpoint_url);
        setEndpoint(live?.endpoint_url ?? null);
      })
      .catch((err: unknown) => setError(messageOf(err)));
  }, [agentId]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' });
  }, [turns, sending]);

  const send = async () => {
    const message = draft.trim();
    if (!message || !endpoint || sending) return;
    setDraft('');
    setTurns((current) => [...current, { role: 'user', text: message, at: new Date().toISOString() }]);
    setSending(true);
    setError(null);
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      });
      const text = await response.text();
      if (!response.ok) throw new Error(`The agent returned HTTP ${response.status}`);
      setTurns((current) => [...current, { role: 'agent', text, at: new Date().toISOString() }]);
    } catch (err) {
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
              <span>{endpoint ? 'Messages go to the deployed agent.' : 'Deploy the agent to chat with it here.'}</span>
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
            placeholder={endpoint ? 'Message the agent' : 'Deploy the agent first'}
            disabled={!endpoint}
            aria-label="Message"
          />
          <button type="submit" className={styles.send} disabled={!endpoint || sending || !draft.trim()}>
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
