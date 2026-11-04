/**
 * Google ID token storage for AUTH_MODE=google.
 *
 * The token lives in sessionStorage (cleared when the tab closes). It expires after
 * about an hour, so expired tokens are dropped here rather than sent to the API.
 */

const STORAGE_KEY = 'agentflow.idToken';
export const SIGNED_OUT_EVENT = 'agentflow:signed-out';

interface TokenClaims {
  exp?: number;
  email?: string;
}

function decodeClaims(token: string): TokenClaims | null {
  try {
    const payload = token.split('.')[1];
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(base64)) as TokenClaims;
  } catch {
    return null;
  }
}

export function setIdToken(token: string): void {
  sessionStorage.setItem(STORAGE_KEY, token);
}

export function clearIdToken(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}

export function getIdToken(): string | null {
  const token = sessionStorage.getItem(STORAGE_KEY);
  if (!token) return null;
  const claims = decodeClaims(token);
  if (!claims?.exp || claims.exp * 1000 <= Date.now()) {
    clearIdToken();
    return null;
  }
  return token;
}

export function getSignedInEmail(): string | null {
  const token = getIdToken();
  return token ? (decodeClaims(token)?.email ?? null) : null;
}
