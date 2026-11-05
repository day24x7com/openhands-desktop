import { useMemo, useState } from 'react';
import type { ConversationEvent, MessageEvent, PlanItem } from '@ohd/shared-types';

const TOOL_ICONS: Record<string, string> = {
  run_shell: '⌘',
  read_file: '📖',
  write_file: '✎',
  str_replace: '✎',
  list_files: '📁',
  web_fetch: '🌐',
  update_plan: '☑',
  think: '💭',
  finish: '✓',
};

function Collapsible({
  title,
  subtitle,
  badge,
  badgeClass,
  children,
  defaultOpen = false,
  mono = true,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  badge?: React.ReactNode;
  badgeClass?: string;
  children?: React.ReactNode;
  defaultOpen?: boolean;
  mono?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-panelAlt/60">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-panelAlt"
        aria-expanded={open}
      >
        <span className="mt-0.5 select-none text-muted">{open ? '▾' : '▸'}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm text-slate-200">{title}</span>
          {subtitle && <span className="mt-0.5 block truncate text-xs text-muted">{subtitle}</span>}
        </span>
        {badge && (
          <span className={`shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium ${badgeClass ?? 'bg-border text-muted'}`}>
            {badge}
          </span>
        )}
      </button>
      {open && children && (
        <div className={`max-h-72 overflow-auto border-t border-border bg-canvas/60 px-3 py-2 text-xs ${mono ? 'font-mono' : ''}`}>
          {children}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ event }: { event: MessageEvent }) {
  const isUser = event.role === 'user';
  return (
    <div className={`flex gap-2 ${isUser ? 'justify-end' : ''}`}>
      {!isUser && (
        <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accentSoft text-xs font-bold text-accent">
          OH
        </div>
      )}
      <div
        className={`max-w-[80%] whitespace-pre-wrap break-words rounded-lg px-3 py-2 text-sm ${
          isUser ? 'bg-accent text-white' : 'border border-border bg-panel text-slate-200'
        }`}
      >
        {event.content}
        {event.attachments?.map((att) =>
          att.mime_type.startsWith('image/') ? (
            <img
              key={att.id}
              src={`data:${att.mime_type};base64,${att.data}`}
              alt={att.name}
              className="mt-2 max-h-48 rounded border border-white/20"
            />
          ) : (
            <div key={att.id} className="mt-1 text-xs opacity-80">
              📎 {att.name}
            </div>
          ),
        )}
      </div>
    </div>
  );
}

export function PlanPanel({ items }: { items: PlanItem[] }) {
  if (!items.length) return null;
  return (
    <div className="card p-3">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Plan</h3>
      <ul className="space-y-1.5">
        {items.map((item, index) => (
          <li key={`${item.title}-${index}`} className="flex items-start gap-2 text-sm">
            <span
              className={
                item.status === 'done'
                  ? 'text-ok'
                  : item.status === 'in_progress'
                    ? 'animate-pulse text-accent'
                    : 'text-muted'
              }
            >
              {item.status === 'done' ? '●' : item.status === 'in_progress' ? '◐' : '○'}
            </span>
            <span className={item.status === 'done' ? 'text-muted line-through' : ''}>{item.title}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Timeline({
  events,
  onOpenDiff,
  onRetry,
}: {
  events: ConversationEvent[];
  onOpenDiff?: (path: string) => void;
  onRetry?: () => void;
}) {
  const plan = useMemo<PlanItem[]>(() => {
    for (let i = events.length - 1; i >= 0; i -= 1) {
      const candidate = events[i];
      if (candidate.type === 'plan') return candidate.items ?? [];
    }
    return [];
  }, [events]);

  if (!events.length) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-muted">
        <div className="text-3xl">🤖</div>
        <p className="text-sm">Describe a task and the agent will start working in your workspace.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {events.map((event) => {
        switch (event.type) {
          case 'message':
            return <MessageBubble key={event.id} event={event} />;
          case 'thinking':
            return (
              <Collapsible
                key={event.id}
                title="Thinking"
                subtitle={(event.content ?? '').slice(0, 120)}
                badge="reasoning"
                badgeClass="bg-accentSoft text-accent"
                mono={false}
              >
                <span className="whitespace-pre-wrap font-sans">{event.content}</span>
              </Collapsible>
            );
          case 'action':
            return (
              <Collapsible
                key={event.id}
                title={
                  <span className="flex items-center gap-2">
                    <span className="text-accent">{TOOL_ICONS[event.tool ?? ''] ?? '⚙'}</span>
                    <span className="font-mono text-xs text-slate-300">{event.tool}</span>
                    <span className="truncate">{event.summary}</span>
                  </span>
                }
                badge="action"
                badgeClass="bg-border text-muted"
              >
                <pre className="whitespace-pre-wrap">{JSON.stringify(event.args ?? {}, null, 2)}</pre>
              </Collapsible>
            );
          case 'observation': {
            const ok = event.ok !== false;
            return (
              <Collapsible
                key={event.id}
                title={
                  <span className="flex items-center gap-2">
                    <span className="text-muted">↳ result</span>
                    <span className="truncate text-xs text-muted">
                      {(event.content ?? '').split('\n')[0]?.slice(0, 110)}
                    </span>
                  </span>
                }
                badge={
                  event.exit_code !== null && event.exit_code !== undefined
                    ? `exit ${event.exit_code}`
                    : `${event.duration_ms ?? 0} ms`
                }
                badgeClass={ok ? 'bg-ok/15 text-ok' : 'bg-danger/15 text-danger'}
              >
                <pre className="whitespace-pre-wrap">{event.content}</pre>
                {event.file_path && onOpenDiff && (
                  <button
                    type="button"
                    className="mt-2 rounded border border-accent/40 px-2 py-0.5 text-[11px] text-accent hover:bg-accentSoft"
                    onClick={() => onOpenDiff(event.file_path!)}
                  >
                    View diff · {event.file_path}
                  </button>
                )}
              </Collapsible>
            );
          }
          case 'plan':
            return null;
          case 'usage':
            return (
              <div key={event.id} className="text-center text-[11px] text-muted">
                {event.prompt_tokens} in / {event.completion_tokens} out tokens · ${(event.cost_usd ?? 0).toFixed(4)}
                {event.total_cost_usd ? ` · total $${event.total_cost_usd.toFixed(4)}` : ''}
              </div>
            );
          case 'status':
            return (
              <div key={event.id} className="text-center text-[11px] uppercase tracking-wide text-muted">
                {event.detail ?? event.status}
              </div>
            );
          case 'error':
            return (
              <div
                key={event.id}
                className="flex items-start gap-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger"
              >
                <span>⚠</span>
                <span className="flex-1">{event.message}</span>
                {onRetry && (
                  <button type="button" className="text-xs underline" onClick={onRetry}>
                    retry
                  </button>
                )}
              </div>
            );
          default:
            return null;
        }
      })}
      {plan.length > 0 && <PlanPanel items={plan} />}
    </div>
  );
}
