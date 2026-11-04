/**
 * Runtime configuration.
 *
 * In production the container writes window.__APP_CONFIG__ from UI_* environment
 * variables (public/config.js). In local development Vite injects the same UI_* keys
 * from the root .env. Runtime values win, so one image serves every environment.
 */

export type AuthMode = 'dev' | 'google';

export interface AppConfig {
  apiBaseUrl: string;
  authMode: AuthMode;
  googleClientId: string;
  devUser: string;
}

function readSetting(key: string): string | undefined {
  const runtime = window.__APP_CONFIG__?.[key];
  if (runtime) return runtime;
  const buildTime = import.meta.env[key] as string | undefined;
  return buildTime || undefined;
}

export const appConfig: AppConfig = {
  apiBaseUrl: (readSetting('UI_API_BASE_URL') ?? 'http://localhost:8080').replace(/\/$/, ''),
  authMode: readSetting('UI_AUTH_MODE') === 'google' ? 'google' : 'dev',
  googleClientId: readSetting('UI_GOOGLE_CLIENT_ID') ?? '',
  devUser: readSetting('UI_DEV_USER') ?? 'dev@example.com',
};
