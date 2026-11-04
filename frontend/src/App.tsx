import { useEffect, useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { api } from './api';
import { getIdToken, SIGNED_OUT_EVENT } from './auth';
import { appConfig } from './config';
import { Layout } from './components/Layout';
import { LoginPage } from './pages/LoginPage';
import { AgentCanvasPage } from './pages/studio/AgentCanvasPage';
import { AgentStudioPage } from './pages/studio/AgentStudioPage';
import { ApprovalsPage } from './pages/studio/ApprovalsPage';
import { DirectoryPage } from './pages/studio/DirectoryPage';
import { EvaluationPage } from './pages/studio/EvaluationPage';
import { GuardrailsPage } from './pages/studio/GuardrailsPage';
import { KnowledgeStudioPage } from './pages/studio/KnowledgeStudioPage';
import { McpClientPage } from './pages/studio/McpClientPage';
import { ObservabilityPage } from './pages/studio/ObservabilityPage';
import { PlaygroundPage } from './pages/studio/PlaygroundPage';
import { ToolStudioPage } from './pages/studio/ToolStudioPage';
import { UsersPage } from './pages/studio/UsersPage';
import { ErrorBanner, useLoad, studioStyles as s } from './studio/ui';
import { SessionProvider } from './session';

export default function App() {
  const [signedIn, setSignedIn] = useState(() => appConfig.authMode === 'dev' || getIdToken() !== null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const onSignedOut = () => setSignedIn(false);
    window.addEventListener(SIGNED_OUT_EVENT, onSignedOut);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, onSignedOut);
  }, []);

  if (!signedIn) return <LoginPage onSignedIn={() => setSignedIn(true)} notice={notice} />;
  return (
    <Workspace
      onSignOut={() => {
        setNotice('You have logged out successfully.');
        setSignedIn(false);
      }}
    />
  );
}

/** Loads who is signed in and their role before any page renders. */
function Workspace({ onSignOut }: { onSignOut: () => void }) {
  const me = useLoad(api.me);

  if (!me.data) {
    return me.error ? <ErrorBanner message={me.error} /> : <div className={s.page}>Loading…</div>;
  }

  return (
    <SessionProvider email={me.data.email} role={me.data.role}>
      <Routes>
        <Route element={<Layout onSignOut={onSignOut} />}>
          <Route index element={<DirectoryPage />} />
          <Route path="/agents" element={<AgentStudioPage />} />
          <Route path="/agents/new" element={<AgentCanvasPage />} />
          <Route path="/agents/:agentId/edit" element={<AgentCanvasPage />} />
          <Route path="/agents/:agentId/playground" element={<PlaygroundPage />} />
          <Route path="/tools" element={<ToolStudioPage />} />
          <Route path="/mcp" element={<McpClientPage />} />
          <Route path="/knowledge" element={<KnowledgeStudioPage />} />
          <Route path="/guardrails" element={<GuardrailsPage />} />
          <Route path="/approvals" element={<ApprovalsPage />} />
          <Route path="/observability" element={<ObservabilityPage />} />
          <Route path="/evaluation" element={<EvaluationPage />} />
          <Route path="/users" element={me.data.role === 'platform_admin' ? <UsersPage /> : <Navigate to="/" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </SessionProvider>
  );
}
