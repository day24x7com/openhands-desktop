/**
 * Interactive terminal panel: xterm.js in the renderer, a real PTY in the
 * sidecar (ConPTY on Windows, `pty` elsewhere) over WebSocket (FR-7).
 */
import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { useEffect, useRef, useState } from 'react';
import { openTerminal, type TerminalHandle } from '../lib/terminal';

const THEME = {
  background: '#0b0e14',
  foreground: '#d6dbe5',
  cursor: '#4f8cff',
  selectionBackground: '#25406b',
  black: '#1b1f27',
  red: '#f85149',
  green: '#3fb950',
  yellow: '#d29922',
  blue: '#4f8cff',
  magenta: '#bc8cff',
  cyan: '#39c5cf',
  white: '#d6dbe5',
};

export function TerminalPanel({ conversationId }: { conversationId: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const handleRef = useRef<TerminalHandle | null>(null);
  const [status, setStatus] = useState<'connecting' | 'open' | 'closed'>('connecting');
  const [error, setError] = useState<string | null>(null);
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const term = new Terminal({
      convertEol: false,
      cursorBlink: true,
      fontFamily: "'JetBrains Mono', 'Cascadia Code', Consolas, monospace",
      fontSize: 12,
      lineHeight: 1.2,
      theme: THEME,
      scrollback: 5000,
      allowProposedApi: true,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(container);
    fit.fit();

    let disposed = false;
    let resizeTimer: number | undefined;

    const syncSize = () => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => {
        try {
          fit.fit();
          handleRef.current?.resize(term.cols, term.rows);
        } catch {
          /* container may be hidden */
        }
      }, 60);
    };

    const observer = new ResizeObserver(syncSize);
    observer.observe(container);

    void openTerminal(
      conversationId,
      term.cols,
      term.rows,
      {
        onData: (chunk) => term.write(chunk),
        onExit: () => {
          term.writeln('\r\n\x1b[90m[process exited]\x1b[0m');
          setStatus('closed');
        },
        onError: (message) => {
          setError(message);
          term.writeln(`\r\n\x1b[31m${message}\x1b[0m`);
        },
        onStatus: setStatus,
      },
    ).then((handle) => {
      if (disposed) {
        handle.close();
        return;
      }
      handleRef.current = handle;
      term.focus();
    });

    const onData = term.onData((data) => handleRef.current?.send(data));
    const onResize = term.onResize(({ cols, rows }) => handleRef.current?.resize(cols, rows));

    return () => {
      disposed = true;
      window.clearTimeout(resizeTimer);
      observer.disconnect();
      onData.dispose();
      onResize.dispose();
      handleRef.current?.close();
      handleRef.current = null;
      term.dispose();
    };
  }, [conversationId, generation]);

  const statusColor = status === 'open' ? 'text-ok' : status === 'connecting' ? 'text-warn' : 'text-danger';

  return (
    <div className="flex h-full flex-col bg-canvas">
      <div className="flex items-center gap-2 border-b border-border px-2 py-1 text-[11px]">
        <span className={`flex items-center gap-1 ${statusColor}`}>
          <span className="h-1.5 w-1.5 rounded-full bg-current" />
          {status === 'open' ? 'shell connected' : status}
        </span>
        {error && <span className="truncate text-danger">{error}</span>}
        <button
          type="button"
          className="btn-ghost ml-auto px-2 py-0.5 text-[11px]"
          onClick={() => setGeneration((g) => g + 1)}
        >
          Restart shell
        </button>
      </div>
      <div ref={containerRef} className="min-h-0 flex-1 px-1 py-1" data-testid="terminal-host" />
    </div>
  );
}
