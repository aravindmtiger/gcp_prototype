import { useState, type FormEvent } from 'react';
import { api } from '../../api';
import { useSession } from '../../session';
import { EmptyState, ErrorBanner, PageHeader, formatDate, messageOf, useLoad, studioStyles as s } from '../../studio/ui';
import type { Role } from '../../types';

const ROLES: { value: Role; title: string; hint: string }[] = [
  { value: 'platform_admin', title: 'Platform admin', hint: 'Manages users and reviews every agent.' },
  { value: 'platform_user', title: 'Platform user', hint: 'Builds agents, submits them, and approves their own.' },
];

const ROLE_TITLE = Object.fromEntries(ROLES.map((r) => [r.value, r.title])) as Record<Role, string>;

export function UsersPage() {
  const { email: me } = useSession();
  const users = useLoad(api.listUsers);
  const [newEmail, setNewEmail] = useState('');
  const [newRole, setNewRole] = useState<Role>('platform_user');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(done);
      users.reload();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  const add = (event: FormEvent) => {
    event.preventDefault();
    const address = newEmail.trim().toLowerCase();
    if (!address) return;
    void run(async () => {
      await api.addUser(address, newRole);
      setNewEmail('');
    }, `${address} is now ${ROLE_TITLE[newRole].toLowerCase()}.`);
  };

  return (
    <div className={s.page}>
      <PageHeader title="Users" subtitle="Roles decide what each person can do." />
      <ErrorBanner message={error ?? users.error} />
      {notice && <div className={s.notice} style={{ marginBottom: 16 }}>{notice}</div>}

      <div className={s.card} style={{ marginBottom: 18 }}>
        <form onSubmit={add} style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            className={s.input}
            style={{ flex: '1 1 280px' }}
            type="email"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            placeholder="name@company.com"
            aria-label="Email"
          />
          <select className={s.select} value={newRole} onChange={(e) => setNewRole(e.target.value as Role)} aria-label="Role">
            {ROLES.map((role) => (
              <option key={role.value} value={role.value}>{role.title}</option>
            ))}
          </select>
          <button type="submit" className={s.btnPrimary} disabled={busy || !newEmail.trim()}>
            Add user
          </button>
        </form>
        <div className={s.choices} style={{ marginTop: 16 }}>
          {ROLES.map((role) => (
            <div key={role.value} className={s.choice} style={{ cursor: 'default' }}>
              <span className={s.choiceTitle}>{role.title}</span>
              <span className={s.choiceHint}>{role.hint}</span>
            </div>
          ))}
        </div>
      </div>

      {(users.data ?? []).length === 0 && !users.error ? (
        <EmptyState>No users yet.</EmptyState>
      ) : (
        <table className={s.table}>
          <thead>
            <tr>
              <th>Email</th>
              <th>Role</th>
              <th>Added</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(users.data ?? []).map((user) => {
              const locked = user.managed_by_config || user.email === me;
              return (
                <tr key={user.email}>
                  <td>
                    <strong>{user.email}</strong>
                    {user.email === me && <span className={s.tag}>You</span>}
                  </td>
                  <td>
                    <select
                      className={s.select}
                      value={user.role}
                      disabled={locked || busy}
                      aria-label={`Role for ${user.email}`}
                      onChange={(e) =>
                        run(() => api.updateUserRole(user.email, e.target.value as Role), `${user.email} is now ${ROLE_TITLE[e.target.value as Role].toLowerCase()}.`)
                      }
                    >
                      {ROLES.map((role) => (
                        <option key={role.value} value={role.value}>{role.title}</option>
                      ))}
                    </select>
                    {user.managed_by_config && <div className={s.muted}>Set in the server settings</div>}
                  </td>
                  <td className={s.muted}>{user.created_at ? formatDate(user.created_at) : '—'}</td>
                  <td style={{ textAlign: 'right' }}>
                    <button
                      type="button"
                      className={s.btnDanger}
                      disabled={locked || busy}
                      onClick={() => {
                        if (window.confirm(`Remove ${user.email}? They keep the default role until they are added again.`)) {
                          void run(() => api.removeUser(user.email), `${user.email} was removed.`);
                        }
                      }}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
