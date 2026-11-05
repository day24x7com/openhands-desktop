import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { AppSettings, Conversation, Workspace } from '@ohd/shared-types';
import { api } from '../lib/api';
import { useConversationStream, useDebounced } from '../lib/stream';
import { ApprovalDialog, DiffViewer, FileExplorer } from './Panels';
import { TerminalPanel } from './TerminalPanel';
import { Timeline } from './Timeline';

type Panel = 'explorer' | 'terminal' | 'editor';

export function ChatWorkspace({
  workspaces,
  settings,
  onOpenSettings,
}: {
  workspaces: Workspace[];
  settings: AppSettings | null;
  onOpenSettings: () => void;
}) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounced(search);
  const [newWorkspaceId, setNewWorkspaceId] = useState(workspaces[0]?.id ?? '');
  const [panel, setPanel] = useState<Panel>('explorer');
  const [diffPath, setDiffPath] = useState<string | null>(null);
  const [editorPath, setEditorPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const active = conversations.find((c) => c.id === activeId) ?? null;
  const { events, conversation: liveConversation, setConversation, connected } = useConversationStream(activeId);

  useEffect(() => {
    if (!newWorkspaceId && workspaces[0]) setNewWorkspaceId(workspaces[0].id);
  }, [workspaces, newWorkspaceId]);

  const loadConversations = useCallback(async () => {
    try {
      setConversations(await api.listConversations(debouncedSearch || undefined));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [debouncedSearch]);

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    if (liveConversation) {
      setConversations((prev) => prev.map((c) => (c.id === liveConversation.id ? liveConversation : c)));
    }
  }, [liveConversation]);

  const createConversation = async () => {
    if (!newWorkspaceId) return;
    try {
      const created = await api.createConversation({
        workspace_id: newWorkspaceId,
        llm_profile_id: settings?.last_llm_profile_id ?? null,
      });
      setConversations((prev) => [created, ...prev]);
      setActiveId(created.id);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const openDiff = (path: string) => {
    setDiffPath(path);
    setPanel('editor');
  };

  const activeConversation = liveConversation ?? active;

  return (
    <div className="flex h-full">
      {/* ------------------------------------------------ conversation rail */}
      <aside className="flex w-64 shrink-0 flex-col border-r border-border bg-panel">
        <div className="space-y-2 p-2">
          <button type="button" className="btn-primary w-full" onClick={createConversation} disabled={!newWorkspaceId}>
            + New conversation
          </button>
          <select
            className="input py-1 text-xs"
            value={newWorkspaceId}
            onChange={(e) => setNewWorkspaceId(e.target.value)}
            aria-label="Workspace for new conversation"
          >
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
          <input
            className="input py-1 text-xs"
            placeholder="Search conversations…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search conversations"
          />
        </div>
        <ul className="flex-1 overflow-auto px-1 pb-2">
          {conversations.map((conv) => (
            <li key={conv.id}>
              <button
                type="button"
                onClick={() => setActiveId(conv.id)}
                className={`group mb-0.5 flex w-full items-center gap-1 rounded px-2 py-1.5 text-left text-sm ${
                  conv.id === activeId ? 'bg-accentSoft text-slate-100' : 'text-slate-300 hover:bg-panelAlt'
                }`}
              >
                <span className="min-w-0 flex-1 truncate">
                  {conv.pinned && '📌 '}
                  {conv.title}
                </span>
                <span
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    conv.status === 'running' ? 'animate-pulse bg-accent' : conv.status === 'error' ? 'bg-danger' : 'bg-transparent'
                  }`}
                />
                <span
                  role="button"
                  tabIndex={0}
                  aria-label={`Delete ${conv.title}`}
                  className="hidden text-xs text-muted hover:text-danger group-hover:block"
                  onClick={async (e) => {
                    e.stopPropagation();
                    await api.deleteConversation(conv.id);
                    if (activeId === conv.id) setActiveId(null);
                    await loadConversations();
                  }}
                  onKeyDown={() => undefined}
                >
                  ✕
                </span>
              </button>
            </li>
          ))}
          {!conversations.length && <li className="px-2 py-4 text-center text-xs text-muted">No conversations yet.</li>}
        </ul>
        <button type="button" className="btn-ghost m-2 text-xs" onClick={onOpenSettings}>
          ⚙ Settings
        </button>
      </aside>

      {/* ----------------------------------------------------------- chat */}
      <main className="flex min-w-0 flex-1 flex-col">
        {error && (
          <div className="border-b border-danger/40 bg-danger/10 px-3 py-1 text-xs text-danger">{error}</div>
        )}
        {!activeId ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-muted">
            <p className="text-sm">Select or create a conversation to start.</p>
          </div>
        ) : (
          <ChatPane
            conversation={activeConversation}
            events={events}
            connected={connected}
            onRefresh={async () => {
              const fresh = await api.getConversation(activeId);
              setConversation(fresh);
              await loadConversations();
            }}
            onOpenDiff={openDiff}
            onRename={async (title) => {
              const updated = await api.patchConversation(activeId, { title });
              setConversation(updated);
              await loadConversations();
            }}
          />
        )}
      </main>

      {/* --------------------------------------------------------- panels */}
      {activeId && (
        <aside className="flex w-[38%] min-w-[380px] shrink-0 flex-col border-l border-border bg-panel">
          <nav className="flex gap-1 border-b border-border p-1 text-xs">
            {(['explorer', 'terminal', 'editor'] as Panel[]).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setPanel(p)}
                className={`rounded px-2 py-1 capitalize ${panel === p ? 'bg-accentSoft text-accent' : 'text-muted hover:text-slate-200'}`}
              >
                {p === 'editor' ? 'diff / editor' : p}
              </button>
            ))}
            {diffPath && (
              <button type="button" className="ml-auto text-muted hover:text-slate-200" onClick={() => setDiffPath(null)}>
                clear
              </button>
            )}
          </nav>
          <div className="min-h-0 flex-1">
            {panel === 'explorer' && (
              <FileExplorer
                conversation_id={activeId}
                refreshKey={events.length}
                onOpen={(path) => {
                  setEditorPath(path);
                  setPanel('editor');
                }}
              />
            )}
            {panel === 'terminal' && <TerminalPanel conversationId={activeId} />}
            {panel === 'editor' && (
              <EditorPane
                conversation_id={activeId}
                diffPath={diffPath}
                file_path={editorPath}
                onClose={() => {
                  setDiffPath(null);
                  setEditorPath(null);
                }}
                onDiffOpen={(path) => setDiffPath(path)}
              />
            )}
          </div>
        </aside>
      )}

      {activeConversation?.pending_approval && (
        <ApprovalDialog
          summary={String((activeConversation.pending_approval.action as { summary?: string } | null)?.summary ?? '')}
          reason={activeConversation.pending_approval.reason}
          onDecide={async (approved, remember) => {
            await api.approve(activeId!, activeConversation.pending_approval!.id, approved, remember);
            const fresh = await api.getConversation(activeId!);
            setConversation(fresh);
          }}
        />
      )}
    </div>
  );
}

function ChatPane({
  conversation,
  events,
  connected,
  onRefresh,
  onOpenDiff,
  onRename,
}: {
  conversation: Conversation | null;
  events: ReturnType<typeof useConversationStream>['events'];
  connected: boolean;
  onRefresh: () => Promise<void>;
  onOpenDiff: (path: string) => void;
  onRename: (title: string) => Promise<void>;
}) {
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events.length]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key.toLowerCase() === 'l') {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const busy = conversation?.status === 'running' || conversation?.status === 'waiting_approval';
  const queued = conversation?.queued_messages ?? 0;

  const send = async () => {
    const content = input.trim();
    if (!content || !conversation) return;
    setSending(true);
    try {
      await api.sendMessage(conversation.id, content);
      setInput('');
      await onRefresh();
    } finally {
      setSending(false);
    }
  };

  if (!conversation) {
    return <div className="flex flex-1 items-center justify-center text-xs text-muted">Connecting…</div>;
  }

  return (
    <>
      <header className="flex items-center gap-2 border-b border-border px-3 py-2">
        {editingTitle ? (
          <input
            className="input py-1 text-sm"
            value={titleDraft}
            autoFocus
            onChange={(e) => setTitleDraft(e.target.value)}
            onBlur={async () => {
              setEditingTitle(false);
              if (titleDraft.trim()) await onRename(titleDraft.trim());
            }}
            onKeyDown={async (e) => {
              if (e.key === 'Enter') {
                setEditingTitle(false);
                if (titleDraft.trim()) await onRename(titleDraft.trim());
              }
              if (e.key === 'Escape') setEditingTitle(false);
            }}
          />
        ) : (
          <button
            type="button"
            className="truncate text-sm font-medium hover:text-accent"
            onClick={() => {
              setTitleDraft(conversation.title);
              setEditingTitle(true);
            }}
            title="Rename conversation"
          >
            {conversation.title}
          </button>
        )}
        <span className={`chip ${connected ? 'text-ok' : 'text-warn'}`}>{connected ? 'live' : 'offline'}</span>
        <span className="chip">{conversation.status}</span>
        {conversation.tokens_total > 0 && (
          <span className="chip">
            {conversation.tokens_total.toLocaleString()} tok · ${conversation.cost_total.toFixed(4)}
          </span>
        )}
        <div className="ml-auto flex items-center gap-1">
          {busy && (
            <button
              type="button"
              className="btn-secondary px-2 py-1 text-xs"
              onClick={async () => {
                await api.pause(conversation.id);
                await onRefresh();
              }}
            >
              Pause
            </button>
          )}
          {conversation.status === 'paused' && (
            <button
              type="button"
              className="btn-secondary px-2 py-1 text-xs"
              onClick={async () => {
                await api.resume(conversation.id);
                await onRefresh();
              }}
            >
              Resume
            </button>
          )}
          {busy && (
            <button
              type="button"
              className="btn-danger px-2 py-1 text-xs"
              onClick={async () => {
                await api.stop(conversation.id);
                await onRefresh();
              }}
            >
              Stop
            </button>
          )}
          <a
            className="btn-ghost px-2 py-1 text-xs"
            href={`#export-${conversation.id}`}
            onClick={async (e) => {
              e.preventDefault();
              const url = await api.exportUrl(conversation.id, 'markdown');
              const blob = await fetch(url).then((r) => r.text());
              const anchor = document.createElement('a');
              anchor.href = URL.createObjectURL(new Blob([blob], { type: 'text/markdown' }));
              anchor.download = `${conversation.title || 'conversation'}.md`;
              anchor.click();
            }}
          >
            Export
          </a>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto p-4" data-testid="timeline">
        <Timeline events={events} onOpenDiff={onOpenDiff} onRetry={onRefresh} />
        <div ref={bottomRef} />
      </div>

      <footer className="border-t border-border p-3">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            className="input max-h-40 min-h-[44px] resize-y"
            placeholder={busy ? 'Queue your next instruction… (agent is working)' : 'Describe a task… (Ctrl+L to focus)'}
            value={input}
            rows={1}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            aria-label="Message"
          />
          <button type="button" className="btn-primary h-[38px]" onClick={send} disabled={sending || !input.trim()}>
            {busy ? 'Queue' : 'Send'}
          </button>
        </div>
        {queued > 0 && <p className="mt-1 text-[11px] text-muted">{queued} message(s) queued</p>}
      </footer>
    </>
  );
}

function EditorPane({
  conversation_id,
  diffPath,
  file_path,
  onClose,
  onDiffOpen,
}: {
  conversation_id: string;
  diffPath: string | null;
  file_path: string | null;
  onClose: () => void;
  onDiffOpen: (path: string) => void;
}) {
  const [content, setContent] = useState('');
  const [original, setOriginal] = useState('');
  const [loading, setLoading] = useState(false);
  const path = diffPath ?? file_path;

  useEffect(() => {
    if (!path) return;
    setLoading(true);
    void api
      .readFile(conversation_id, path)
      .then((file) => {
        setContent(file.content);
        setOriginal(file.content);
      })
      .catch(() => {
        setContent('');
        setOriginal('');
      })
      .finally(() => setLoading(false));
  }, [conversation_id, path]);

  const dirty = useMemo(() => content !== original, [content, original]);

  if (!path) {
    return <div className="p-3 text-xs text-muted">Pick a file in the explorer to view or edit it.</div>;
  }

  if (diffPath) {
    return <DiffViewer conversation_id={conversation_id} path={diffPath} onClose={onClose} />;
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border px-3 py-1 text-xs">
        <span className="flex-1 truncate font-mono text-muted">{path}</span>
        {dirty && <span className="text-warn">modified</span>}
        <button type="button" className="btn-secondary px-2 py-0.5" onClick={() => onDiffOpen(path)}>
          Diff
        </button>
        <button
          type="button"
          className="btn-primary px-2 py-0.5"
          disabled={!dirty}
          onClick={async () => {
            await api.writeFile(conversation_id, path, content);
            setOriginal(content);
          }}
        >
          Save
        </button>
        <button type="button" className="btn-ghost px-2 py-0.5" onClick={onClose}>
          ✕
        </button>
      </div>
      {loading ? (
        <div className="p-3 text-xs text-muted">Loading…</div>
      ) : (
        <textarea
          className="flex-1 resize-none bg-canvas p-3 font-mono text-xs text-slate-200 outline-none"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          spellCheck={false}
          aria-label={`Edit ${path}`}
        />
      )}
    </div>
  );
}

export { DiffViewer };
