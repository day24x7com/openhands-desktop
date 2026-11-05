import { useCallback, useEffect, useState } from 'react';
import type { AppSettings, HealthResponse, Workspace } from '@ohd/shared-types';
import { ChatWorkspace } from './components/ChatWorkspace';
import { OnboardingWizard } from './components/OnboardingWizard';
import { SettingsView } from './components/SettingsView';
import { api } from './lib/api';

type Phase = 'connecting' | 'onboarding' | 'ready' | 'unreachable';

export default function App() {
  const [phase, setPhase] = useState<Phase>('connecting');
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [showSettings, setShowSettings] = useState(false);
  const [message, setMessage] = useState<string>('');

  const bootstrap = useCallback(async () => {
    setPhase('connecting');
    setMessage('');
    try {
      const healthInfo = await api.health();
      setHealth(healthInfo);
      const [currentSettings, workspaceList] = await Promise.all([api.getSettings(), api.listWorkspaces()]);
      setSettings(currentSettings);
      setWorkspaces(workspaceList);
      if (!currentSettings.onboarded || workspaceList.length === 0) {
        setPhase('onboarding');
      } else {
        setPhase('ready');
      }
    } catch (error) {
      setMessage((error as Error).message);
      setPhase('unreachable');
    }
  }, []);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  if (phase === 'connecting') {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-muted">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-border border-t-accent" />
        <p className="text-sm">Starting the local agent service…</p>
      </div>
    );
  }

  if (phase === 'unreachable') {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
        <p className="text-lg font-medium text-danger">Agent service unavailable</p>
        <p className="max-w-md text-sm text-muted">{message}</p>
        <p className="max-w-md text-xs text-muted">
          The desktop shell starts the Python sidecar automatically. If you are running the UI standalone, start it with
          <code className="mx-1 rounded bg-panelAlt px-1">python -m app</code>
          from the <code>sidecar/</code> folder.
        </p>
        <button type="button" className="btn-primary" onClick={bootstrap}>
          Retry
        </button>
      </div>
    );
  }

  if (phase === 'onboarding') {
    return (
      <OnboardingWizard
        health={health}
        onDone={async (_workspace, _profile, updatedSettings) => {
          setSettings(updatedSettings);
          setWorkspaces(await api.listWorkspaces());
          setPhase('ready');
        }}
      />
    );
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-10 shrink-0 items-center gap-3 border-b border-border bg-panel px-3 text-xs">
        <span className="font-semibold text-slate-200">OpenHands Desktop</span>
        <span className="chip">{health?.platform ?? 'unknown'}</span>
        {health && (
          <span className="chip">
            {health.environment.filter((c) => c.available).length}/{health.environment.length} tools detected
          </span>
        )}
        <span className="ml-auto text-muted">sidecar {health?.sidecar_version}</span>
      </header>
      <div className="min-h-0 flex-1">
        {showSettings ? (
          <SettingsView
            onClose={async () => {
              setShowSettings(false);
              setSettings(await api.getSettings());
              setWorkspaces(await api.listWorkspaces());
            }}
          />
        ) : (
          <ChatWorkspace workspaces={workspaces} settings={settings} onOpenSettings={() => setShowSettings(true)} />
        )}
      </div>
    </div>
  );
}
