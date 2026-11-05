/**
 * Git bar for the file panel (FR-9.1): shows the branch and changed-file count,
 * and offers init / commit / branch switching without leaving the app.
 */
import { useCallback, useEffect, useState } from 'react';
import type { GitBranches, GitStatus } from '@ohd/shared-types';
import { api } from '../lib/api';

type Mode = 'idle' | 'commit' | 'branch';

export function GitBar({
  conversation_id,
  status,
  onChanged,
}: {
  conversation_id: string;
  status: GitStatus | null;
  onChanged: () => void;
}) {
  const [mode, setMode] = useState<Mode>('idle');
  const [message, setMessage] = useState('');
  const [branches, setBranches] = useState<GitBranches | null>(null);
  const [newBranch, setNewBranch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setMode('idle');
    setError(null);
    setNotice(null);
  }, [conversation_id]);

  const isRepo = status !== null && status.branch !== null;

  const run = useCallback(
    async (action: () => Promise<{ output?: string } | unknown>) => {
      setBusy(true);
      setError(null);
      try {
        const result = (await action()) as { output?: string };
        setNotice(result?.output?.split('\n')[0] ?? 'Done');
        onChanged();
        setMode('idle');
        return true;
      } catch (err) {
        setError((err as Error).message);
        return false;
      } finally {
        setBusy(false);
      }
    },
    [onChanged],
  );

  const openBranchPicker = async () => {
    setMode('branch');
    setError(null);
    try {
      setBranches(await api.gitBranches(conversation_id));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  if (mode === 'commit') {
    return (
      <div className="mt-2 space-y-1.5 rounded border border-border bg-panelAlt/40 p-2">
        <textarea
          className="input h-14 resize-none py-1 text-xs"
          placeholder="Commit message"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          aria-label="Commit message"
        />
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            className="btn-secondary px-2 py-0.5 text-[11px]"
            disabled={busy || !message.trim()}
            onClick={() => {
              void run(async () => {
                const result = await api.gitCommit(conversation_id, message.trim());
                setMessage('');
                return result;
              });
            }}
          >
            {busy ? 'Committing…' : 'Commit all changes'}
          </button>
          <button type="button" className="btn-ghost px-2 py-0.5 text-[11px]" onClick={() => setMode('idle')}>
            Cancel
          </button>
        </div>
        {error && <p className="text-[11px] text-danger">{error}</p>}
      </div>
    );
  }

  if (mode === 'branch') {
    return (
      <div className="mt-2 space-y-1.5 rounded border border-border bg-panelAlt/40 p-2">
        <div className="flex flex-wrap gap-1">
          {(branches?.branches ?? []).map((name) => (
            <button
              key={name}
              type="button"
              className={`chip px-1.5 py-0.5 text-[11px] ${
                name === branches?.current ? 'border-accent text-accent' : 'text-muted hover:text-slate-200'
              }`}
              disabled={busy || name === branches?.current}
              onClick={() => void run(() => api.gitCheckout(conversation_id, name))}
            >
              {name}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          <input
            className="input py-0.5 text-xs"
            placeholder="new-branch-name"
            value={newBranch}
            onChange={(e) => setNewBranch(e.target.value)}
            aria-label="New branch name"
          />
          <button
            type="button"
            className="btn-secondary px-2 py-0.5 text-[11px]"
            disabled={busy || !newBranch.trim()}
            onClick={() => {
              void run(async () => {
                const result = await api.gitCheckout(conversation_id, newBranch.trim(), true);
                setNewBranch('');
                return result;
              });
            }}
          >
            Create
          </button>
          <button type="button" className="btn-ghost px-2 py-0.5 text-[11px]" onClick={() => setMode('idle')}>
            Close
          </button>
        </div>
        {error && <p className="text-[11px] text-danger">{error}</p>}
      </div>
    );
  }

  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted">
        {isRepo ? (
          <>
            <button
              type="button"
              className="chip hover:text-slate-200"
              onClick={() => void openBranchPicker()}
              title="Switch branch"
            >
              ⎇ {status?.branch}
            </button>
            {status && status.entries.length > 0 && <span>{status.entries.length} changed</span>}
            <button
              type="button"
              className="btn-ghost ml-auto px-2 py-0.5 text-[11px]"
              disabled={!status?.entries.length}
              onClick={() => setMode('commit')}
            >
              Commit
            </button>
          </>
        ) : (
          <button
            type="button"
            className="btn-ghost px-2 py-0.5 text-[11px]"
            disabled={busy || status === null}
            onClick={() => void run(() => api.gitInit(conversation_id))}
          >
            {busy ? 'Initialising…' : 'Initialise git repository'}
          </button>
        )}
      </div>
      {error && <p className="mt-1 text-[11px] text-danger">{error}</p>}
      {notice && !error && <p className="mt-1 text-[11px] text-ok">{notice}</p>}
    </div>
  );
}
