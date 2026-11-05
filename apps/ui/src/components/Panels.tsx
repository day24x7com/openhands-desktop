import { useEffect, useMemo, useState } from 'react';
import type { FileDiff, FileNode, GitStatus } from '@ohd/shared-types';
import { api } from '../lib/api';
import { GitBar } from './GitBar';

const STATUS_COLOR: Record<string, string> = {
  M: 'text-warn',
  A: 'text-ok',
  D: 'text-danger',
  '?': 'text-muted',
  R: 'text-warn',
  U: 'text-danger',
};

export function FileExplorer({
  conversation_id,
  onOpen,
  refreshKey,
}: {
  conversation_id: string;
  onOpen: (path: string) => void;
  refreshKey: number;
}) {
  const [nodes, setNodes] = useState<FileNode[]>([]);
  const [git, setGit] = useState<GitStatus | null>(null);
  const [filter, setFilter] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [bump, setBump] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [tree, status] = await Promise.all([api.files(conversation_id), api.git(conversation_id)]);
        if (!cancelled) {
          setNodes(tree);
          setGit(status);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [conversation_id, refreshKey, bump]);

  const visible = useMemo(() => {
    const term = filter.trim().toLowerCase();
    if (!term) return nodes.slice(0, 400);
    return nodes.filter((n) => n.path.toLowerCase().includes(term)).slice(0, 400);
  }, [nodes, filter]);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border p-2">
        <input
          className="input py-1 text-xs"
          placeholder="Filter files…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          aria-label="Filter files"
        />
        <GitBar
          conversation_id={conversation_id}
          status={git}
          onChanged={() => setBump((n) => n + 1)}
        />
      </div>
      <div className="flex-1 overflow-auto p-1 text-sm">
        {error && <p className="p-2 text-xs text-danger">{error}</p>}
        {visible.map((node) => (
          <button
            key={node.path}
            type="button"
            onClick={() => node.type === 'file' && onOpen(node.path)}
            className={`flex w-full items-center gap-1.5 rounded px-2 py-1 text-left hover:bg-panelAlt ${
              node.type === 'dir' ? 'text-muted' : 'text-slate-300'
            }`}
            style={{ paddingLeft: `${(node.path.split('/').length - 1) * 12 + 8}px` }}
            title={node.path}
            disabled={node.type === 'dir'}
          >
            <span>{node.type === 'dir' ? '📁' : '📄'}</span>
            <span className="truncate">{node.name}</span>
            {node.git_status && (
              <span className={`ml-auto text-[10px] font-bold ${STATUS_COLOR[node.git_status]}`}>
                {node.git_status}
              </span>
            )}
          </button>
        ))}
        {!visible.length && !error && <p className="p-2 text-xs text-muted">No files.</p>}
      </div>
    </div>
  );
}

export function DiffViewer({
  conversation_id,
  path,
  onClose,
}: {
  conversation_id: string;
  path: string;
  onClose: () => void;
}) {
  const [diff, setDiff] = useState<FileDiff | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const diffs = await api.diff(conversation_id, path);
        if (!cancelled) setDiff(diffs[0] ?? null);
      } catch (err) {
        if (!cancelled) setMessage((err as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [conversation_id, path]);

  const decide = async (action: 'accept' | 'reject') => {
    setBusy(true);
    try {
      const result = action === 'accept' ? await api.acceptFile(conversation_id, path) : await api.rejectFile(conversation_id, path);
      setMessage(result.output || `${action}ed ${path}`);
      if (result.ok) onClose();
    } catch (err) {
      setMessage((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <span className="flex-1 truncate font-mono text-xs text-slate-300">{path}</span>
        {diff && (
          <span className="text-[11px]">
            <span className="text-ok">+{diff.additions}</span> <span className="text-danger">-{diff.deletions}</span>
          </span>
        )}
        <button type="button" className="btn-secondary px-2 py-1 text-xs" disabled={busy} onClick={() => decide('accept')}>
          Accept
        </button>
        <button type="button" className="btn-danger px-2 py-1 text-xs" disabled={busy} onClick={() => decide('reject')}>
          Reject
        </button>
        <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={onClose}>
          ✕
        </button>
      </div>
      {message && <p className="border-b border-border px-3 py-1 text-xs text-muted">{message}</p>}
      <div className="flex-1 overflow-auto font-mono text-xs leading-5">
        {!diff && <p className="p-3 text-muted">No pending changes for this file.</p>}
        {diff?.hunks.map((hunk, index) => (
          <div key={index}>
            <div className="bg-panelAlt px-3 py-0.5 text-[11px] text-muted">
              @@ -{hunk.old_start},{hunk.old_lines} +{hunk.new_start},{hunk.new_lines} @@
            </div>
            {hunk.lines.map((line, lineIndex) => {
              const prefix = line[0];
              const cls =
                prefix === '+'
                  ? 'bg-ok/10 text-ok'
                  : prefix === '-'
                    ? 'bg-danger/10 text-danger'
                    : 'text-slate-400';
              return (
                <div key={lineIndex} className={`whitespace-pre-wrap px-3 ${cls}`}>
                  {line}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ApprovalDialog({
  summary,
  reason,
  onDecide,
}: {
  summary: string;
  reason: string;
  onDecide: (approved: boolean, remember: boolean) => void;
}) {
  const [remember, setRemember] = useState(false);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-lg rounded-lg border border-warn/40 bg-panel p-4 shadow-2xl">
        <h2 className="mb-1 flex items-center gap-2 text-base font-semibold text-warn">⚠ Approval required</h2>
        <p className="mb-3 text-sm text-muted">{reason}</p>
        <pre className="mb-3 max-h-40 overflow-auto rounded border border-border bg-canvas p-2 font-mono text-xs text-slate-200">
          {summary}
        </pre>
        <label className="mb-3 flex items-center gap-2 text-xs text-muted">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          Always allow this exact command in this conversation
        </label>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={() => onDecide(false, false)}>
            Deny
          </button>
          <button type="button" className="btn-primary" onClick={() => onDecide(true, remember)}>
            Approve &amp; run
          </button>
        </div>
      </div>
    </div>
  );
}
