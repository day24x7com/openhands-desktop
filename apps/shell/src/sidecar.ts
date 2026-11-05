/**
 * Sidecar supervisor.
 *
 * The desktop shell owns the Python backend's lifecycle: it picks a free port,
 * generates a per-session bearer token, spawns the bundled interpreter, waits
 * for `/health` to answer, and shuts the process down with the app.
 */
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { createWriteStream } from 'node:fs';
import { get as httpGet } from 'node:http';
import type { AddressInfo } from 'node:net';
import { createServer } from 'node:net';
import path from 'node:path';

export interface SidecarInfo {
  baseUrl: string;
  token: string;
  pid: number;
}

export interface SidecarOptions {
  /** Directory containing `app/` (the sidecar package root). */
  sidecarDir: string;
  /** Python interpreter; defaults to the bundled runtime in production. */
  pythonPath: string;
  dataDir: string;
  logFile: string;
  /** Force a port (tests/dev). */
  port?: number;
}

async function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address() as AddressInfo;
      server.close(() => resolve(port));
    });
  });
}

function probeHealth(baseUrl: string, token: string): Promise<boolean> {
  return new Promise((resolve) => {
    const request = httpGet(
      `${baseUrl}/health`,
      { headers: { Authorization: `Bearer ${token}` }, timeout: 1500 },
      (response) => {
        response.resume();
        resolve(response.statusCode === 200);
      },
    );
    request.on('error', () => resolve(false));
    request.on('timeout', () => {
      request.destroy();
      resolve(false);
    });
  });
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export class Sidecar {
  private child: ChildProcessWithoutNullStreams | null = null;
  private info: SidecarInfo | null = null;
  private stopping = false;

  constructor(private readonly options: SidecarOptions) {}

  get baseUrl(): string | null {
    return this.info?.baseUrl ?? null;
  }

  get token(): string | null {
    return this.info?.token ?? null;
  }

  async start(timeoutMs = 60_000): Promise<SidecarInfo> {
    if (this.info) return this.info;

    const port = this.options.port ?? (await findFreePort());
    const token = randomBytes(32).toString('hex');
    const log = createWriteStream(this.options.logFile, { flags: 'a' });

    const child = spawn(
      this.options.pythonPath,
      ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port), '--log-level', 'info'],
      {
        cwd: this.options.sidecarDir,
        env: {
          ...process.env,
          PYTHONUNBUFFERED: '1',
          PYTHONUTF8: '1',
          OHD_DATA_DIR: this.options.dataDir,
          OHD_SESSION_TOKEN: token,
          OHD_DESKTOP: '1',
        },
        windowsHide: true,
      },
    );
    this.child = child as ChildProcessWithoutNullStreams;

    child.stdout?.pipe(log);
    child.stderr?.pipe(log);
    child.on('exit', (code, signal) => {
      log.write(`\n[sidecar] exited code=${code} signal=${signal}\n`);
      this.info = null;
      if (!this.stopping) {
        this.onUnexpectedExit?.(code);
      }
    });

    const baseUrl = `http://127.0.0.1:${port}`;
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (child.exitCode !== null) {
        throw new Error(`The agent service exited during startup (code ${child.exitCode}).`);
      }
      if (await probeHealth(baseUrl, token)) {
        this.info = { baseUrl, token, pid: child.pid ?? -1 };
        return this.info;
      }
      await sleep(250);
    }
    this.stop();
    throw new Error('The agent service did not become ready in time.');
  }

  /** Called when the process dies without `stop()` (crash) so the UI can react. */
  onUnexpectedExit?: (code: number | null) => void;

  async stop(): Promise<void> {
    this.stopping = true;
    const child = this.child;
    this.child = null;
    this.info = null;
    if (!child || child.exitCode !== null) return;

    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        try {
          child.kill('SIGKILL');
        } catch {
          /* already gone */
        }
        resolve();
      }, 5000);
      child.once('exit', () => {
        clearTimeout(timer);
        resolve();
      });
      child.kill();
    });
  }

  logPath(): string {
    return path.resolve(this.options.logFile);
  }
}
