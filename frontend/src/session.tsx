import { createContext, useContext, type ReactNode } from 'react';
import type { Role } from './types';

export interface Session {
  email: string;
  role: Role;
  isAdmin: boolean;
}

const SessionContext = createContext<Session>({ email: '', role: 'platform_user', isAdmin: false });

export function SessionProvider({ email, role, children }: { email: string; role: Role; children: ReactNode }) {
  const value: Session = { email, role, isAdmin: role === 'platform_admin' };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  return useContext(SessionContext);
}
