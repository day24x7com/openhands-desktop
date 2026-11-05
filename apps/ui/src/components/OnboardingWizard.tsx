import { useEffect, useMemo, useState } from 'react';
import type { AppSettings, HealthResponse, LlmProfile, LlmProvider, Workspace } from '@ohd/shared-types';
import { api } from '../lib/api';

export const PROVIDERS: {
  id: LlmProvider;
  label: string;
  needsKey: boolean;
  baseUrl?: string;
  models: string[];
}[] = [
  { id: 'anthropic', label: 'Anthropic', needsKey: true, models: ['claude-sonnet-4-5', 'claude-opus-4-1', 'claude-haiku-4-5'] },
  { id: 'openai', label: 'OpenAI', needsKey: true, models: ['gpt-4.1', 'gpt-4o', 'o4-mini'] },
  { id: 'google', label: 'Google Gemini', needsKey: true, models: ['gemini-2.5-pro', 'gemini-2.5-flash'] },
  { id: 'azure', label: 'Azure OpenAI', needsKey: true, models: ['gpt-4o'] },
  { id: 'openrouter', label: 'OpenRouter', needsKey: true, models: ['anthropic/claude-sonnet-4.5', 'openai/gpt-4.1'] },
  { id: 'bedrock', label: 'AWS Bedrock', needsKey: true, models: ['anthropic.claude-sonnet-4-5-v1:0'] },
  {
    id: 'ollama',
    label: 'Ollama (local)',
    needsKey: false,
    baseUrl: 'http://localhost:11434/v1',
    models: ['qwen2.5-coder:7b', 'llama3.1:8b', 'deepseek-coder-v2:16b'],
  },
  { id: 'lmstudio', label: 'LM Studio (local)', needsKey: false, baseUrl: 'http://localhost:1234/v1', models: ['local-model'] },
  { id: 'vllm', label: 'vLLM (local)', needsKey: false, baseUrl: 'http://localhost:8000/v1', models: ['local-model'] },
  { id: 'openai-compatible', label: 'Custom OpenAI-compatible', needsKey: true, baseUrl: '', models: [''] },
  { id: 'mock', label: 'Demo (offline mock)', needsKey: false, models: ['mock-model'] },
];

export function providerMeta(provider: LlmProvider) {
  return PROVIDERS.find((p) => p.id === provider) ?? PROVIDERS[PROVIDERS.length - 1];
}

type Step = 0 | 1 | 2 | 3;

export function OnboardingWizard({
  health,
  onDone,
}: {
  health: HealthResponse | null;
  onDone: (workspace: Workspace, profile: LlmProfile, settings: AppSettings) => void;
}) {
  const [step, setStep] = useState<Step>(0);
  const [provider, setProvider] = useState<LlmProvider>('anthropic');
  const [model, setModel] = useState('claude-sonnet-4-5');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [workspacePath, setWorkspacePath] = useState('');
  const [samplePath, setSamplePath] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string; latency_ms: number } | null>(null);

  const meta = useMemo(() => providerMeta(provider), [provider]);

  useEffect(() => {
    const preferred = meta.baseUrl ?? '';
    setBaseUrl(preferred);
    setModel(meta.models[0] ?? '');
    setTestResult(null);
  }, [meta]);

  const pickFolder = async () => {
    if (window.openhands) {
      const picked = await window.openhands.pickDirectory();
      if (picked) setWorkspacePath(picked);
    }
  };

  const testConnection = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.testProfile({
        name: `${meta.label} default`,
        provider,
        model,
        base_url: baseUrl || null,
        api_key: apiKey || null,
      });
      setTestResult(result);
    } catch (err) {
      setTestResult({ ok: false, message: (err as Error).message, latency_ms: 0 });
    } finally {
      setBusy(false);
    }
  };

  const finish = async () => {
    setBusy(true);
    setError(null);
    try {
      const profile = await api.createProfile({
        name: `${meta.label} · ${model}`,
        provider,
        model,
        base_url: baseUrl || null,
        api_key: apiKey || null,
        is_default: true,
      });
      const workspace = await api.createWorkspace({
        path: workspacePath || '~/OpenHandsProjects',
        kind: 'local',
      });
      const updated = await api.saveSettings({
        ...(await api.getSettings()),
        onboarded: true,
        last_workspace_id: workspace.id,
        last_llm_profile_id: profile.id,
      });
      onDone(workspace, profile, updated);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center bg-canvas p-6">
      <div className="card w-full max-w-2xl p-6">
        <header className="mb-4">
          <h1 className="text-xl font-semibold text-slate-100">Welcome to OpenHands Desktop</h1>
          <p className="mt-1 text-sm text-muted">
            Connect a model and pick a project folder. Everything runs on your machine — no Docker required.
          </p>
          <div className="mt-4 flex gap-2 text-[11px] text-muted">
            {['Model', 'Credentials', 'Workspace', 'Ready'].map((label, index) => (
              <span
                key={label}
                className={`rounded-full px-2 py-0.5 ${
                  index === step ? 'bg-accent text-white' : index < step ? 'bg-ok/20 text-ok' : 'bg-panelAlt'
                }`}
              >
                {index + 1}. {label}
              </span>
            ))}
          </div>
        </header>

        {error && <p className="mb-3 rounded border border-danger/40 bg-danger/10 p-2 text-sm text-danger">{error}</p>}

        {step === 0 && (
          <div className="grid grid-cols-2 gap-2">
            {PROVIDERS.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => setProvider(p.id)}
                className={`rounded-md border p-3 text-left text-sm ${
                  provider === p.id ? 'border-accent bg-accentSoft' : 'border-border bg-panelAlt hover:border-slate-500'
                }`}
              >
                <div className="font-medium text-slate-100">{p.label}</div>
                <div className="text-xs text-muted">
                  {p.needsKey ? 'Cloud / API key' : 'Local · no key'} · {p.models[0] || 'custom model'}
                </div>
              </button>
            ))}
            {health && (
              <div className="col-span-2 mt-2 rounded border border-border bg-panelAlt/50 p-2 text-[11px] text-muted">
                Environment:{' '}
                {health.environment.map((check) => (
                  <span key={check.name} className={check.available ? 'mr-2 text-ok' : 'mr-2 text-warn'}>
                    {check.available ? '✓' : '✗'} {check.name}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {step === 1 && (
          <div className="space-y-3">
            <div>
              <label className="label" htmlFor="model">
                Model
              </label>
              <input
                id="model"
                className="input"
                value={model}
                list="model-options"
                onChange={(e) => setModel(e.target.value)}
                placeholder="model id"
              />
              <datalist id="model-options">
                {meta.models.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>
            <div>
              <label className="label" htmlFor="base-url">
                Base URL {meta.needsKey ? '(optional)' : ''}
              </label>
              <input
                id="base-url"
                className="input"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder={meta.baseUrl || 'https://api.example.com/v1'}
              />
            </div>
            {meta.needsKey && (
              <div>
                <label className="label" htmlFor="api-key">
                  API key
                </label>
                <input
                  id="api-key"
                  className="input"
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="sk-…"
                  autoComplete="off"
                />
                <p className="mt-1 text-[11px] text-muted">
                  Stored encrypted (Windows Credential Manager / DPAPI) — never written to the database or logs.
                </p>
              </div>
            )}
            <div className="flex items-center gap-2">
              <button type="button" className="btn-secondary" onClick={testConnection} disabled={busy}>
                Test connection
              </button>
              {testResult && (
                <span className={`text-xs ${testResult.ok ? 'text-ok' : 'text-danger'}`}>
                  {testResult.ok ? `✓ connected in ${testResult.latency_ms} ms` : `✗ ${testResult.message}`}
                </span>
              )}
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-3">
            <label className="label" htmlFor="workspace">
              Project folder
            </label>
            <div className="flex gap-2">
              <input
                id="workspace"
                className="input"
                value={workspacePath}
                onChange={(e) => setWorkspacePath(e.target.value)}
                placeholder="C:\\Users\\you\\Projects\\my-app"
              />
              <button type="button" className="btn-secondary shrink-0" onClick={pickFolder}>
                Browse…
              </button>
            </div>
            <p className="text-[11px] text-muted">
              The agent runs in “Local workspace” mode: it edits files in this folder and asks before running risky
              commands. Leave empty to create <code>~/OpenHandsProjects</code>.
            </p>
            <button
              type="button"
              className="btn-ghost px-0 text-[11px] text-accent"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError(null);
                try {
                  const sample = await api.createSampleWorkspace();
                  setSamplePath(sample.path);
                  setWorkspacePath(sample.path);
                } catch (err) {
                  setError((err as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              No project yet? Try the sample project instead →
            </button>
            {samplePath && (
              <p className="text-[11px] text-ok">
                Sample project ready at {samplePath}. It has one failing test — ask the agent to fix it.
              </p>
            )}
          </div>
        )}

        {step === 3 && (
          <div className="space-y-2 text-sm">
            <p className="text-slate-200">Ready to go.</p>
            <ul className="space-y-1 text-muted">
              <li>Provider: {meta.label}</li>
              <li>Model: {model}</li>
              <li>Workspace: {workspacePath || '~/OpenHandsProjects'}</li>
              <li>Risky-command approval: enabled</li>
            </ul>
          </div>
        )}

        <footer className="mt-6 flex justify-between">
          <button type="button" className="btn-ghost" onClick={() => setStep((s) => Math.max(0, s - 1) as Step)} disabled={step === 0 || busy}>
            Back
          </button>
          {step < 3 ? (
            <button
              type="button"
              className="btn-primary"
              onClick={() => setStep((s) => Math.min(3, s + 1) as Step)}
              disabled={step === 1 && (!model || (meta.needsKey && !apiKey))}
            >
              Continue
            </button>
          ) : (
            <button type="button" className="btn-primary" onClick={finish} disabled={busy}>
              Finish setup
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
