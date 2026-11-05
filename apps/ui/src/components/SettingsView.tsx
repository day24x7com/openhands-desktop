import { useEffect, useState } from 'react';
import type { AppSettings, LlmProfile, LlmProfileInput, LlmProvider, Workspace } from '@ohd/shared-types';
import { api } from '../lib/api';
import { PROVIDERS, providerMeta } from './OnboardingWizard';

const EMPTY: LlmProfileInput = {
  name: '',
  provider: 'anthropic',
  model: 'claude-sonnet-4-5',
  base_url: null,
  api_key: null,
  temperature: 0,
  max_tokens: 4096,
  timeout_seconds: 300,
  retries: 2,
  is_default: false,
};

export function SettingsView({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<'providers' | 'workspaces' | 'general' | 'environment'>('providers');
  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-border px-4 py-2">
        <h2 className="text-sm font-semibold">Settings</h2>
        <nav className="flex gap-1 text-xs">
          {(['providers', 'workspaces', 'general', 'environment'] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`rounded px-2 py-1 capitalize ${tab === t ? 'bg-accentSoft text-accent' : 'text-muted hover:text-slate-200'}`}
            >
              {t}
            </button>
          ))}
        </nav>
        <button type="button" className="btn-ghost ml-auto px-2 py-1 text-xs" onClick={onClose}>
          Close
        </button>
      </header>
      <div className="flex-1 overflow-auto p-4">
        {tab === 'providers' && <ProvidersTab />}
        {tab === 'workspaces' && <WorkspacesTab />}
        {tab === 'general' && <GeneralTab />}
        {tab === 'environment' && <EnvironmentTab />}
      </div>
    </div>
  );
}

function ProvidersTab() {
  const [profiles, setProfiles] = useState<LlmProfile[]>([]);
  const [draft, setDraft] = useState<LlmProfileInput>(EMPTY);
  const [test, setTest] = useState<{ ok: boolean; message: string; latency_ms: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => {
    try {
      setProfiles(await api.listProfiles());
    } catch (err) {
      setError((err as Error).message);
    }
  };
  useEffect(() => {
    void reload();
  }, []);

  const meta = providerMeta(draft.provider);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.createProfile(draft);
      setDraft(EMPTY);
      setTest(null);
      await reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const runTest = async () => {
    setBusy(true);
    try {
      setTest(await api.testProfile(draft));
    } catch (err) {
      setTest({ ok: false, message: (err as Error).message, latency_ms: 0 });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className="card p-4">
        <h3 className="mb-3 text-sm font-semibold">Saved profiles</h3>
        <ul className="space-y-2">
          {profiles.map((profile) => (
            <li key={profile.id} className="flex items-center gap-2 rounded border border-border bg-panelAlt p-2 text-sm">
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-slate-100">{profile.name}</div>
                <div className="text-xs text-muted">
                  {providerMeta(profile.provider).label} · {profile.model}
                  {profile.is_default && <span className="ml-2 text-accent">default</span>}
                  {profile.has_api_key && <span className="ml-2 text-ok">key ✓</span>}
                </div>
              </div>
              <button
                type="button"
                className="btn-secondary px-2 py-1 text-xs"
                onClick={async () => {
                  try {
                    const result = await api.testSavedProfile(profile.id);
                    setTest(result);
                  } catch (err) {
                    setTest({ ok: false, message: (err as Error).message, latency_ms: 0 });
                  }
                }}
              >
                Test
              </button>
              <button
                type="button"
                className="btn-ghost px-2 py-1 text-xs"
                onClick={async () => {
                  await api.deleteProfile(profile.id);
                  await reload();
                }}
              >
                Delete
              </button>
            </li>
          ))}
          {!profiles.length && <li className="text-xs text-muted">No profiles yet.</li>}
        </ul>
      </section>

      <section className="card space-y-3 p-4">
        <h3 className="text-sm font-semibold">Add a model</h3>
        {error && <p className="text-xs text-danger">{error}</p>}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="label" htmlFor="p-name">Name</label>
            <input id="p-name" className="input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          </div>
          <div>
            <label className="label" htmlFor="p-provider">Provider</label>
            <select
              id="p-provider"
              className="input"
              value={draft.provider}
              onChange={(e) => {
                const provider = e.target.value as LlmProvider;
                const m = PROVIDERS.find((p) => p.id === provider);
                setDraft({ ...draft, provider, model: m?.models[0] ?? '', base_url: m?.baseUrl ?? null });
              }}
            >
              {PROVIDERS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="p-model">Model</label>
            <input id="p-model" className="input" value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} />
          </div>
          <div>
            <label className="label" htmlFor="p-base">Base URL</label>
            <input
              id="p-base"
              className="input"
              value={draft.base_url ?? ''}
              onChange={(e) => setDraft({ ...draft, base_url: e.target.value || null })}
            />
          </div>
          {meta.needsKey && (
            <div className="col-span-2">
              <label className="label" htmlFor="p-key">API key</label>
              <input
                id="p-key"
                type="password"
                className="input"
                value={draft.api_key ?? ''}
                onChange={(e) => setDraft({ ...draft, api_key: e.target.value || null })}
                autoComplete="off"
              />
            </div>
          )}
          <div>
            <label className="label" htmlFor="p-temp">Temperature</label>
            <input
              id="p-temp"
              type="number"
              step="0.1"
              className="input"
              value={draft.temperature ?? 0}
              onChange={(e) => setDraft({ ...draft, temperature: Number(e.target.value) })}
            />
          </div>
          <div>
            <label className="label" htmlFor="p-max">Max tokens</label>
            <input
              id="p-max"
              type="number"
              className="input"
              value={draft.max_tokens ?? 4096}
              onChange={(e) => setDraft({ ...draft, max_tokens: Number(e.target.value) })}
            />
          </div>
          <label className="col-span-2 flex items-center gap-2 text-xs text-muted">
            <input
              type="checkbox"
              checked={draft.is_default ?? false}
              onChange={(e) => setDraft({ ...draft, is_default: e.target.checked })}
            />
            Make this the default model
          </label>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" className="btn-secondary" onClick={runTest} disabled={busy}>
            Test connection
          </button>
          <button type="button" className="btn-primary" onClick={create} disabled={busy || !draft.name || !draft.model}>
            Save profile
          </button>
          {test && (
            <span className={`text-xs ${test.ok ? 'text-ok' : 'text-danger'}`}>
              {test.ok ? `✓ ${test.latency_ms} ms` : `✗ ${test.message}`}
            </span>
          )}
        </div>
      </section>
    </div>
  );
}

function WorkspacesTab() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [path, setPath] = useState('');
  const [gitUrl, setGitUrl] = useState('');
  const [error, setError] = useState<string | null>(null);

  const reload = async () => setWorkspaces(await api.listWorkspaces());
  useEffect(() => {
    void reload();
  }, []);

  const add = async () => {
    try {
      await api.createWorkspace({ path });
      setPath('');
      await reload();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const clone = async () => {
    try {
      await api.cloneWorkspace(gitUrl);
      setGitUrl('');
      await reload();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="space-y-4">
      {error && <p className="text-xs text-danger">{error}</p>}
      <section className="card p-4">
        <h3 className="mb-2 text-sm font-semibold">Workspaces</h3>
        <ul className="space-y-2">
          {workspaces.map((workspace) => (
            <li key={workspace.id} className="flex items-center gap-2 rounded border border-border bg-panelAlt p-2 text-sm">
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{workspace.name}</div>
                <div className="truncate text-xs text-muted">{workspace.path}</div>
              </div>
              <span className="chip">{workspace.kind}</span>
              <button
                type="button"
                className="btn-ghost px-2 py-1 text-xs"
                onClick={async () => {
                  await api.deleteWorkspace(workspace.id);
                  await reload();
                }}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section className="card space-y-2 p-4">
        <h3 className="text-sm font-semibold">Add workspace</h3>
        <div className="flex gap-2">
          <input className="input" value={path} onChange={(e) => setPath(e.target.value)} placeholder="C:\\path\\to\\project" />
          <button type="button" className="btn-secondary shrink-0" onClick={add} disabled={!path}>
            Add folder
          </button>
        </div>
        <div className="flex gap-2">
          <input className="input" value={gitUrl} onChange={(e) => setGitUrl(e.target.value)} placeholder="https://github.com/org/repo" />
          <button type="button" className="btn-secondary shrink-0" onClick={clone} disabled={!gitUrl}>
            Clone
          </button>
        </div>
      </section>
    </div>
  );
}

function GeneralTab() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    void api.getSettings().then(setSettings);
  }, []);

  if (!settings) return <p className="text-xs text-muted">Loading…</p>;

  return (
    <section className="card max-w-xl space-y-3 p-4">
      <h3 className="text-sm font-semibold">General</h3>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={settings.confirm_risky_actions}
          onChange={(e) => setSettings({ ...settings, confirm_risky_actions: e.target.checked })}
        />
        Ask before risky shell commands
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={settings.allow_network_in_shell}
          onChange={(e) => setSettings({ ...settings, allow_network_in_shell: e.target.checked })}
        />
        Allow the agent to fetch web pages
      </label>
      <div>
        <label className="label" htmlFor="shell">Default shell</label>
        <select
          id="shell"
          className="input"
          value={settings.default_shell}
          onChange={(e) => setSettings({ ...settings, default_shell: e.target.value as AppSettings['default_shell'] })}
        >
          {['powershell', 'cmd', 'bash', 'wsl'].map((shell) => (
            <option key={shell} value={shell}>
              {shell}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="label" htmlFor="budget">Cost limit per conversation (USD)</label>
        <input
          id="budget"
          type="number"
          step="0.5"
          className="input"
          value={settings.max_cost_usd_per_conversation ?? ''}
          onChange={(e) =>
            setSettings({
              ...settings,
              max_cost_usd_per_conversation: e.target.value ? Number(e.target.value) : null,
            })
          }
          placeholder="no limit"
        />
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="btn-primary"
          onClick={async () => {
            setSettings(await api.saveSettings(settings));
            setSaved(true);
            window.setTimeout(() => setSaved(false), 1500);
          }}
        >
          Save
        </button>
        {saved && <span className="text-xs text-ok">Saved</span>}
      </div>
    </section>
  );
}

function EnvironmentTab() {
  const [health, setHealth] = useState<Awaited<ReturnType<typeof api.health>> | null>(null);
  const [docker, setDocker] = useState<Awaited<ReturnType<typeof api.docker>> | null>(null);

  useEffect(() => {
    void api.health().then(setHealth);
    void api.docker().then(setDocker);
  }, []);

  return (
    <section className="card max-w-xl space-y-2 p-4 text-sm">
      <h3 className="text-sm font-semibold">Environment</h3>
      {health?.environment.map((check) => (
        <div key={check.name} className="flex items-center gap-2">
          <span className={check.available ? 'text-ok' : 'text-warn'}>{check.available ? '✓' : '✗'}</span>
          <span className="font-mono text-xs">{check.name}</span>
          <span className="truncate text-xs text-muted">{check.version ?? check.hint ?? ''}</span>
        </div>
      ))}
      <div className="pt-2 text-xs text-muted">
        Docker: {docker?.available ? `available (${docker.engine})` : docker?.message ?? 'checking…'}
      </div>
      <div className="text-xs text-muted">Data directory: {health?.data_dir}</div>
    </section>
  );
}
