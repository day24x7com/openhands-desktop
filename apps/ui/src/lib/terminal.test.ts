import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { openTerminal } from '../lib/terminal';

class FakeSocket {
  static instances: FakeSocket[] = [];
  static OPEN = 1;
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }

  send(payload: string) {
    this.sent.push(payload);
  }

  open() {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }

  emit(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}

vi.mock('../lib/api', () => ({
  api: {
    getSidecarConfig: vi.fn(async () => ({ baseUrl: 'http://127.0.0.1:1234', token: 'tok-1' })),
  },
}));

describe('terminal client', () => {
  beforeEach(() => {
    FakeSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeSocket as unknown as typeof WebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('connects with the token, size and shell in the query string', async () => {
    await openTerminal('conv-1', 100, 30, { onData: vi.fn(), onExit: vi.fn(), onError: vi.fn() }, 'bash');
    const socket = FakeSocket.instances[0];
    expect(socket.url).toContain('ws://127.0.0.1:1234/api/conversations/conv-1/terminal');
    expect(socket.url).toContain('token=tok-1');
    expect(socket.url).toContain('cols=100');
    expect(socket.url).toContain('rows=30');
    expect(socket.url).toContain('shell=bash');
  });

  it('queues input until the socket opens, then flushes it', async () => {
    const handle = await openTerminal('conv-1', 80, 24, { onData: vi.fn(), onExit: vi.fn(), onError: vi.fn() });
    const socket = FakeSocket.instances[0];
    handle.send('ls\n');
    expect(socket.sent).toHaveLength(0);
    socket.open();
    expect(socket.sent).toEqual([JSON.stringify({ kind: 'input', data: 'ls\n' })]);
    handle.send('pwd\n');
    expect(socket.sent).toHaveLength(2);
  });

  it('routes output, exit and error frames to their handlers', async () => {
    const onData = vi.fn();
    const onExit = vi.fn();
    const onError = vi.fn();
    await openTerminal('conv-1', 80, 24, { onData, onExit, onError });
    const socket = FakeSocket.instances[0];
    socket.open();

    socket.emit({ kind: 'output', data: 'hello' });
    socket.emit({ kind: 'ping' });
    expect(onData).toHaveBeenCalledWith('hello');
    expect(onData).toHaveBeenCalledTimes(1);

    socket.emit({ kind: 'exit' });
    expect(onExit).toHaveBeenCalled();

    socket.emit({ kind: 'error', message: 'boom' });
    expect(onError).toHaveBeenCalledWith('boom');
  });

  it('reports status transitions and stops sending after close', async () => {
    const onStatus = vi.fn();
    const handle = await openTerminal('conv-1', 80, 24, { onData: vi.fn(), onExit: vi.fn(), onError: vi.fn(), onStatus });
    const socket = FakeSocket.instances[0];
    expect(onStatus).toHaveBeenCalledWith('connecting');
    socket.open();
    expect(onStatus).toHaveBeenCalledWith('open');
    handle.resize(120, 40);
    expect(socket.sent).toContain(JSON.stringify({ kind: 'resize', cols: 120, rows: 40 }));
    socket.close();
    expect(onStatus).toHaveBeenCalledWith('closed');
    expect(handle.ready).toBe(false);
  });
});
