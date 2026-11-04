import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { ErrorBanner, useLoad, studioStyles as s } from '../../studio/ui';

const STUDIOS = [
  { to: '/agents', label: 'Agent Studio', glyph: '🤖', blurb: 'Design, build and configure custom agents.' },
  { to: '/tools', label: 'Tool Studio', glyph: '🔧', blurb: 'Browse the tools available to agents.' },
  { to: '/knowledge', label: 'Knowledge Studio', glyph: '🗄', blurb: 'Connect RAG corpora and structured tables.' },
  { to: '/mcp', label: 'MCP Studio', glyph: '🔌', blurb: 'Define MCP servers and the tools they expose.' },
  { to: '/guardrails', label: 'Guardrails', glyph: '🛡', blurb: 'Model Armor and Sensitive Data Protection templates.' },
  { to: '/approvals', label: 'Approvals', glyph: '📋', blurb: 'Review agents assigned to your group.' },
  { to: '/observability', label: 'Observability', glyph: '📈', blurb: 'Logs and traces of deployed agents.' },
  { to: '/evaluation', label: 'Evaluation', glyph: '✅', blurb: 'Offline and online evaluation of agents.' },
];

const COMMUNITY_LINK = 'https://chat.google.com/room/AAQAjBByBII?cls=7';

export function DirectoryPage() {
  const [query, setQuery] = useState('');
  const [feedback, setFeedback] = useState('');
  const [isFeedbackFocused, setIsFeedbackFocused] = useState(false);

  const counts = useLoad(async () => {
    const [agents, tools, knowledge, guardrails, mcp] = await Promise.all([
      api.listAgents(),
      api.listTools(),
      api.listKnowledge(),
      api.listGuardrails(),
      api.listMcpServers(),
    ]);
    return {
      Agent: agents.length,
      Tools: tools.length,
      Knowledge: knowledge.length,
      Guardrails: guardrails.length,
      MCP: mcp.length,
    } as Record<string, number>;
  });

  const badge = (label: string): string | null => {
    if (!counts.data) return null;
    if (label === 'Agent Studio') return `${counts.data.Agent} agents`;
    if (label === 'Tool Studio') return `${counts.data.Tools} tools`;
    if (label === 'Knowledge Studio') return `${counts.data.Knowledge} sources`;
    if (label === 'Guardrails') return `${counts.data.Guardrails} guardrails`;
    if (label === 'MCP Studio') return `${counts.data.MCP} servers`;
    return null;
  };

  const visible = STUDIOS.filter((studio) => studio.label.toLowerCase().includes(query.toLowerCase()));

  const handleJoinClick = () => {
    window.open(COMMUNITY_LINK, '_blank', 'noopener,noreferrer');
  };

  const onSubmitFeedback = () => {
    if (!feedback.trim()) return;
    setFeedback('');
  };

  return (
    <div className={s.page}>
      <div className={s.homeShell}>
        <div className={s.homeContent}>
          <header className={s.homeHeader}>
            <div>
              <h1 className={s.title}>Enterprise Agent Directory</h1>
              <p className={s.subtitle}>Discover, deploy, and manage verified intelligent workflows across your organisation.</p>
            </div>
          </header>

          <div className={s.homeSearchWrap}>
            <input
              className={s.search}
              placeholder="Describe a workflow or search a studio..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search studios"
            />
          </div>

          <ErrorBanner message={counts.error} />

          <div className={s.grid}>
            {visible.map((studio) => (
              <Link key={studio.to} to={studio.to} className={s.directoryCard}>
                <div className={s.cardIcon}>{studio.glyph}</div>
                <strong>{studio.label}</strong>
                <span className={s.muted}>{studio.blurb}</span>
                {badge(studio.label) && <span className={s.tag}>{badge(studio.label)}</span>}
              </Link>
            ))}
          </div>

          <div className={s.communitySection}>
            <div className={s.communityCard}>
              <div className={s.communityIcon}>💬</div>
              <h3 className={s.communityTitle}>For more updates, please join AgentFlow Space</h3>
              <button type="button" onClick={handleJoinClick} className={s.communityButton}>
                Join now <span aria-hidden="true">→</span>
              </button>
            </div>

            <div className={s.feedbackCard}>
              <h3 className={s.feedbackTitle}>Share Your Experience</h3>
              <p className={s.feedbackLabel}>Your Feedback</p>
              <textarea
                value={feedback}
                onChange={(event) => setFeedback(event.target.value)}
                onFocus={() => setIsFeedbackFocused(true)}
                onBlur={() => setIsFeedbackFocused(false)}
                placeholder="Type Here..."
                className={s.feedbackInput}
                style={{
                  borderColor: isFeedbackFocused ? '#f7931e' : undefined,
                  boxShadow: isFeedbackFocused ? '0 0 0 1px rgba(247,147,30,0.8)' : 'none',
                }}
              />
              <button type="button" onClick={onSubmitFeedback} className={s.submitButton}>
                Submit
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
