import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { currentEmail } from '../../lib/user';
import { EmptyState, ErrorBanner, PageHeader, PillTabs, StatusBadge, formatDate, useLoad, studioStyles as s } from '../../studio/ui';

type Scope = 'mine' | 'all';

export function AgentStudioPage() {
  const agents = useLoad(api.listAgents);
  const [scope, setScope] = useState<Scope>('mine');
  const [query, setQuery] = useState('');
  const me = currentEmail();

  const rows = useMemo(() => {
    const all = agents.data ?? [];
    const scoped = scope === 'mine' ? all.filter((a) => a.owner_email === me) : all;
    return scoped.filter((a) => `${a.name} ${a.description}`.toLowerCase().includes(query.toLowerCase()));
  }, [agents.data, scope, query, me]);

  return (
    <div className={s.page}>
      <PageHeader
        title="Agents"
        subtitle="Your agents."
        actions={<Link className={s.btnPrimary} to="/agents/new" style={{ textDecoration: 'none' }}>+ New agent</Link>}
      />
      <div className={s.toolbar}>
        <PillTabs<Scope>
          value={scope}
          onChange={setScope}
          options={[
            { value: 'mine', label: 'My agents' },
            { value: 'all', label: 'All agents' },
          ]}
        />
        <input className={s.search} placeholder="Search agents…" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      <ErrorBanner message={agents.error} />
      {rows.length === 0 ? (
        <EmptyState>No agents yet. Create one in the Agent Canvas.</EmptyState>
      ) : (
        <table className={s.table}>
          <thead>
            <tr>
              <th>Agent name</th>
              <th>Description</th>
              <th>Created</th>
              <th>Owner</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((agent) => (
              <tr key={agent.id}>
                <td>
                  <strong>{agent.name}</strong>
                </td>
                <td className={s.muted}>{agent.description}</td>
                <td className={s.muted}>{formatDate(agent.created_at)}</td>
                <td className={s.muted}>{agent.owner_email}</td>
                <td>
                  <StatusBadge status={agent.status} />
                </td>
                <td style={{ display: 'flex', gap: 8 }}>
                  <Link to={`/agents/${agent.id}/edit`}>Edit</Link>
                  {agent.status === 'deployed' && <Link to={`/agents/${agent.id}/playground`}>Playground</Link>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
