/**
 * Thin client for the sidecar's PTY terminal WebSocket.
 *
 * Frames in:  {kind:"output", data} | {kind:"exit"} | {kind:"error", message} | {kind:"ping"}
 * Frames out: {kind:"input", data} | {kind:"resize", cols, rows} | {kind:"close"}
 */

export interface TerminalHandlers {
  onData: (chunk: string) => void;
  onExit: () => void;
  onError: (message: string) => void;
  onStatus?: (status: 'connecting' | 'open' | 'closed') => void;
}

export interface TerminalHandle {
  send: (data: string) => void;
  resize: (cols: number, rows: number) => void;
  close: () => void;
  readonly ready: boolean;
}

export async function openTerminal(
  conversationId: string,
  cols: number,
  rows: number,
  handlers: TerminalHandlers,
  shell?: string,
): Promise<TerminalHandle> {
  const { api } = await import('./api');
  const config = await api.getSidecarConfig();
  const wsBase = config.baseUrl.replace(/^http/, 'ws');
  const params = new URLSearchParams({ cols: String(cols), rows: String(rows) });
  if (shell) params.set('shell', shell);
  if (config.token) params.set('token', config.token);

  handlers.onStatus?.('connecting');
  const socket = new WebSocket(`${wsBase}/api/conversations/${conversationId}/terminal?${params}`);
  let ready = false;
  const pending: string[] = [];

  socket.onopen = () => {
    ready = true;
    handlers.onStatus?.('open');
    for (const chunk of pending.splice(0)) socket.send(JSON.stringify({ kind: 'input', data: chunk }));
  };

  socket.onmessage = (event) => {
    let message: { kind?: string; data?: string; message?: string };
    try {
      message = JSON.parse(String(event.data));
    } catch {
      return;
    }
    switch (message.kind) {
      case 'output':
        handlers.onData(message.data ?? '');
        break;
      case 'exit':
        handlers.onExit();
        break;
      case 'error':
        handlers.onError(message.message ?? 'Terminal error');
        break;
      default:
        break;
    }
  };

  socket.onclose = () => {
    ready = false;
    handlers.onStatus?.('closed');
  };
  socket.onerror = () => handlers.onStatus?.('closed');

  return {
    get ready() {
      return ready;
    },
    send: (data: string) => {
      if (ready) socket.send(JSON.stringify({ kind: 'input', data }));
      else pending.push(data);
    },
    resize: (nextCols: number, nextRows: number) => {
      if (ready) socket.send(JSON.stringify({ kind: 'resize', cols: nextCols, rows: nextRows }));
    },
    close: () => {
      if (ready) socket.send(JSON.stringify({ kind: 'close' }));
      socket.close();
    },
  };
}
