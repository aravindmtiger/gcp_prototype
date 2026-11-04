import { GoogleLogin } from '@react-oauth/google';
import { useState } from 'react';
import { setIdToken } from '../auth';
import { appConfig } from '../config';
import styles from './LoginPage.module.css';

interface LoginPageProps {
  onSignedIn: () => void;
  /** Shown once after sign-out, for example "You have logged out successfully." */
  notice?: string | null;
}

const TILES = [
  { cls: styles.t1, title: 'Canvas', body: 'Drag tools and connect them' },
  { cls: styles.t2, title: 'Playground', body: 'Chat with a deployed agent' },
  { cls: styles.t3, title: 'Evaluation', body: 'Criteria and rubrics' },
  { cls: styles.t4, title: 'Deploy', body: 'Cloud Run or Agent Runtime' },
];

/** GCP Agent OS sign-in. Google sign-in is also how people register: the first sign-in creates the account. */
export function LoginPage({ onSignedIn, notice }: LoginPageProps) {
  const [error, setError] = useState<string | null>(null);

  return (
    <main className={styles.page}>
      {notice && (
        <div className={styles.toast} role="status">
          <span className={styles.check} aria-hidden="true">✓</span>
          {notice}
        </div>
      )}

      <section className={styles.showcase} aria-hidden="true">
        <div className={styles.brand}>
          <span className={styles.mark}>AO</span>
          GCP Agent OS
        </div>
        {TILES.map((tile) => (
          <div key={tile.title} className={`${styles.tile} ${tile.cls}`}>
            <strong>{tile.title}</strong>
            <span style={{ fontSize: 12, color: '#6b6b78' }}>{tile.body}</span>
            <div className={styles.bars}>
              <div className={styles.bar} />
              <div className={styles.bar} />
              <div className={styles.bar} style={{ gridColumn: 'span 2' }} />
            </div>
          </div>
        ))}
        <span className={styles.dot} style={{ top: 120, left: 210 }}>⌘</span>
        <span className={styles.dot} style={{ top: 330, left: 520 }}>▶</span>
        <span className={styles.dot} style={{ top: 440, left: 240 }}>⬈</span>
      </section>

      <section className={styles.panel} aria-labelledby="login-title">
        <div className={styles.icon} aria-hidden="true">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <rect x="4" y="8" width="16" height="11" rx="3" />
            <path d="M12 4v4M9 13h.01M15 13h.01M9 17h6" />
          </svg>
        </div>
        <h1 id="login-title" className={styles.title}>GCP Agent OS</h1>
        <p className={styles.description}>Build, deploy, and manage secure, scalable AI agents using native GCP services.</p>

        <div className={styles.google}>
          <GoogleLogin
            onSuccess={(response) => {
              if (!response.credential) {
                setError('Google did not return a credential. Try again.');
                return;
              }
              setIdToken(response.credential);
              onSignedIn();
            }}
            onError={() => setError('Google sign-in failed. Check the OAuth client configuration.')}
            text="continue_with"
            shape="rectangular"
            size="large"
            theme="outline"
            width="340"
          />
        </div>

        {error && <div className={styles.error} role="alert">{error}</div>}
        {!appConfig.googleClientId && (
          <div className={styles.error} role="alert">UI_GOOGLE_CLIENT_ID is not set.</div>
        )}
        <p className={styles.note}>
          New here? Sign in with your Google account to register. Your account is created on first sign-in with the default role.
        </p>
      </section>
    </main>
  );
}
