import { useState, type FormEvent } from 'react';
import { api } from '../../api';
import { EmptyState, ErrorBanner, PageHeader, StatusBadge, messageOf, useLoad, studioStyles as s } from '../../studio/ui';
import type { McpAuthType, McpServer, McpServerInput } from '../../types';

const AUTH_OPTIONS: { value: McpAuthType; title: string; hint: string }[] = [
  { value: 'none', title: 'None', hint: 'The server accepts calls without credentials.' },
  { value: 'google_id_token', title: 'Google service account', hint: 'The backend signs an ID token. Grant its service account access to the server.' },
  { value: 'bearer_token', title: 'Bearer token', hint: 'Sends a secret as an Authorization header.' },
  { value: 'api_key_header', title: 'API key header', hint: 'Sends a secret in a header you name.' },
];

const AUTH_TITLE = Object.fromEntries(AUTH_OPTIONS.map((o) => [o.value, o.title])) as Record<McpAuthType, string>;
const SECRET_PLACEHOLDER = 'projects/my-project/secrets/crm-token/versions/latest';

interface Draft {
  name: string;
  description: string;
  endpointUrl: string;
  authType: McpAuthType;
  headerName: string;
  secretName: string;
}

const EMPTY: Draft = { name: '', description: '', endpointUrl: '', authType: 'none', headerName: '', secretName: '' };

function problemWith(draft: Draft): string | null {
  if (!draft.name.trim()) return 'Give the connection a name';
  const local = /^http:\/\/(localhost|127\.0\.0\.1)/.test(draft.endpointUrl);
  if (!draft.endpointUrl.startsWith('https://') && !local) return 'The endpoint must start with https://';
  if (draft.authType === 'bearer_token' || draft.authType === 'api_key_header') {
    if (!draft.secretName.trim()) return 'Enter the Secret Manager secret that holds the credential';
  }
  if (draft.authType === 'api_key_header' && !draft.headerName.trim()) return 'Enter the header the key is sent in';
  return null;
}

function toInput(draft: Draft): McpServerInput {
  const input: McpServerInput = {
    name: draft.name.trim(),
    description: draft.description.trim(),
    endpoint_url: draft.endpointUrl.trim(),
    auth_type: draft.authType,
  };
  if (draft.authType === 'bearer_token' || draft.authType === 'api_key_header') input.secret_name = draft.secretName.trim();
  if (draft.authType === 'api_key_header') input.header_name = draft.headerName.trim();
  return input;
}

export function McpClientPage() {
  const servers = useLoad(api.listMcpServers);
  const endpoints = useLoad(api.listGcpEndpoints);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const update = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }));

  const report = (server: McpServer) => {
    if (server.status === 'connected') {
      setNotice(`${server.name} is connected. ${server.tools.length} ${server.tools.length === 1 ? 'tool' : 'tools'} found.`);
      setError(null);
    } else {
      setError(`${server.name} is saved but could not connect. ${server.last_error}`);
      setNotice(null);
    }
  };

  // One step for the user: save the connection, then run the handshake straight away.
  const connectNew = async (event: FormEvent) => {
    event.preventDefault();
    const problem = problemWith(draft);
    if (problem) return setError(problem);
    setBusy('new');
    setError(null);
    setNotice(null);
    try {
      const created = await api.createMcpServer(toInput(draft));
      report(await api.connectMcpServer(created.id));
      setDraft(EMPTY);
      setOpen(false);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(null);
      servers.reload();
    }
  };

  const reconnect = async (server: McpServer) => {
    setBusy(server.id);
    setError(null);
    setNotice(null);
    try {
      report(await api.connectMcpServer(server.id));
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(null);
      servers.reload();
    }
  };

  const needsSecret = draft.authType === 'bearer_token' || draft.authType === 'api_key_header';

  return (
    <div className={s.page}>
      <PageHeader
        title="MCP Client"
        subtitle="Connect to MCP servers already running in Google Cloud."
        actions={(
          <button type="button" className={s.btnPrimary} onClick={() => setOpen((v) => !v)}>
            {open ? 'Cancel' : 'New connection'}
          </button>)}
      />
      <ErrorBanner message={error ?? servers.error} />
      {notice && <div className={s.notice} style={{ marginBottom: 16 }}>{notice}</div>}

      {open && (
        <form className={s.card} style={{ marginBottom: 18 }} onSubmit={connectNew}>
          <div className={s.form}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 14 }}>
              <label className={s.field}>
                Name
                <input className={s.input} value={draft.name} onChange={(e) => update({ name: e.target.value })} placeholder="crm" />
              </label>
              <label className={s.field}>
                Endpoint
                <select
                  className={s.select}
                  value={draft.endpointUrl}
                  onChange={(e) => update({ endpointUrl: e.target.value })}
                  disabled={!endpoints.data?.length}
                >
                  <option value="">{endpoints.data?.length ? 'Choose an endpoint…' : 'No endpoints found'}</option>
                  {(endpoints.data ?? []).map((endpoint) => (
                    <option key={endpoint.uri} value={endpoint.uri}>
                      {endpoint.name} · {endpoint.location}
                    </option>
                  ))}
                </select>
                {endpoints.error ? (
                  <span className={s.muted}>{endpoints.error}</span>
                ) : (
                  <span className={s.muted}>Cloud Run services in this Google Cloud project.</span>
                )}
              </label>
            </div>
            <label className={s.field}>
              Description
              <input className={s.input} value={draft.description} onChange={(e) => update({ description: e.target.value })} />
            </label>

            <div>
              <p className={s.sectionTitle}>Authentication</p>
              <div className={s.choices} role="radiogroup">
                {AUTH_OPTIONS.map((option) => {
                  const active = draft.authType === option.value;
                  return (
                    <label key={option.value} className={`${s.choice} ${active ? s.choiceActive : ''}`}>
                      <input
                        type="radio"
                        className={s.visuallyHidden}
                        name="auth-type"
                        checked={active}
                        onChange={() => update({ authType: option.value })}
                      />
                      <span className={s.choiceTitle}>{option.title}</span>
                      <span className={s.choiceHint}>{option.hint}</span>
                    </label>
                  );
                })}
              </div>
            </div>

            {needsSecret && (
              <div style={{ display: 'grid', gridTemplateColumns: draft.authType === 'api_key_header' ? '1fr 2fr' : '1fr', gap: 14 }}>
                {draft.authType === 'api_key_header' && (
                  <label className={s.field}>
                    Header name
                    <input className={s.input} value={draft.headerName} onChange={(e) => update({ headerName: e.target.value })} placeholder="X-Api-Key" />
                  </label>
                )}
                <label className={s.field}>
                  Secret
                  <input className={s.input} value={draft.secretName} onChange={(e) => update({ secretName: e.target.value })} placeholder={SECRET_PLACEHOLDER} />
                  <span className={s.muted}>The value stays in Secret Manager. Only the reference is saved.</span>
                </label>
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button type="submit" className={s.btnPrimary} disabled={busy !== null}>
                {busy === 'new' ? 'Connecting…' : 'Connect'}
              </button>
            </div>
          </div>
        </form>
      )}

      {(servers.data ?? []).length === 0 && !servers.error ? (
        <EmptyState>No connections yet. Connect an MCP server to see its tools here.</EmptyState>
      ) : (
        <table className={s.table}>
          <thead>
            <tr>
              <th>Server</th>
              <th>Authentication</th>
              <th>Tools</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(servers.data ?? []).map((server) => (
              <tr key={server.id}>
                <td>
                  <strong>{server.name}</strong>
                  <div className={s.muted}>{server.endpoint_url}</div>
                </td>
                <td className={s.muted}>{AUTH_TITLE[server.auth_type]}</td>
                <td>
                  {server.tools.length === 0 ? <span className={s.muted}>None yet</span> : null}
                  {server.tools.map((tool) => (
                    <span key={tool.name} className={s.tag} title={tool.description}>{tool.name}</span>
                  ))}
                </td>
                <td>
                  <StatusBadge status={server.status} />
                  {server.last_error && <div className={s.muted}>{server.last_error}</div>}
                </td>
                <td style={{ textAlign: 'right' }}>
                  <button
                    type="button"
                    className={s.btnGhost}
                    disabled={busy !== null}
                    onClick={() => reconnect(server)}
                  >
                    {busy === server.id ? 'Connecting…' : server.status === 'connected' ? 'Refresh tools' : 'Connect'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
