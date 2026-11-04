import { api } from '../../api';
import { EmptyState, ErrorBanner, PageHeader, useLoad, studioStyles as s } from '../../studio/ui';

/** Built-in tools available on the Agent Canvas. Read-only: the list comes from the API. */
export function ToolStudioPage() {
  const tools = useLoad(api.listTools);
  return (
    <div className={s.page}>
      <PageHeader title="Tools" subtitle="Tools you can drag onto an agent." />
      <ErrorBanner message={tools.error} />
      {(tools.data ?? []).length === 0 && !tools.error && <EmptyState>No tools registered.</EmptyState>}
      <div className={s.grid}>
        {(tools.data ?? []).map((tool) => (
          <div key={tool.id} className={s.card}>
            <h3 style={{ margin: '0 0 6px' }}>{tool.label}</h3>
            <p className={s.muted} style={{ marginTop: 0 }}>{tool.description}</p>
            <div>
              {tool.config.length === 0 ? (
                <span className={s.tag}>no settings</span>
              ) : (
                tool.config.map((field) => (
                  <span key={field} className={s.tag}>{field}</span>
                ))
              )}
            </div>
            <div className={s.muted} style={{ marginTop: 8 }}>id: {tool.id}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
