import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { clearIdToken, getSignedInEmail } from '../auth';
import { appConfig } from '../config';
import { useSession } from '../session';
import styles from './Layout.module.css';

interface LayoutProps {
  onSignOut: () => void;
}

// Icon rail entries, in the order of the studios. Glyphs stand in for icons.
const RAIL: { to: string; label: string; glyph: string; end?: boolean }[] = [
  { to: '/', label: 'Directory', glyph: '⌂', end: true },
  { to: '/agents', label: 'Agent Studio', glyph: '🤖' },
  { to: '/tools', label: 'Tool Studio', glyph: '🔧' },
  { to: '/mcp', label: 'MCP Client', glyph: '🔌' },
  { to: '/knowledge', label: 'Knowledge Studio', glyph: '🗄' },
  { to: '/observability', label: 'Observability', glyph: '📈' },
  { to: '/evaluation', label: 'Evaluation', glyph: '✅' },
  { to: '/guardrails', label: 'Guardrails', glyph: '🛡' },
  { to: '/approvals', label: 'Approvals', glyph: '📋' },
];

export function Layout({ onSignOut }: LayoutProps) {
  const { email, role, isAdmin } = useSession();
  const navigate = useNavigate();
  const [who, setWho] = useState<string>(email || appConfig.devUser);

  useEffect(() => {
    if (appConfig.authMode === 'google') setWho(getSignedInEmail() ?? email);
  }, [email]);

  const signOut = () => {
    clearIdToken();
    onSignOut();
    navigate('/');
  };

  return (
    <div className={styles.shell}>
      <nav className={styles.rail} aria-label="Studios">
        <div className={styles.logo}>AO</div>
        {RAIL.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            title={item.label}
            aria-label={item.label}
            className={({ isActive }) => `${styles.navItem} ${isActive ? styles.navActive : ''}`}
          >
            {item.glyph}
          </NavLink>
        ))}
        <div className={styles.railFooter}>
          {isAdmin && (
            <NavLink
              to="/users"
              title="Users"
              aria-label="Users"
              className={({ isActive }) => `${styles.navItem} ${isActive ? styles.navActive : ''}`}
            >
              👥
            </NavLink>
          )}
          <span title={who}>{who.split('@')[0]}</span>
          <span className={styles.role}>{role}</span>
          {appConfig.authMode === 'google' && <button type="button" onClick={signOut}>Sign out</button>}
        </div>
      </nav>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}
