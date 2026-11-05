/**
 * Integration test for the sidecar supervisor: it must spawn a real Python
 * process, expose a token-protected API on a free port, and leave nothing
 * running after `stop()`.
 *
 * Run with: node --test dist/  (after `npm run build`)
 */
import assert from 'node:assert/strict';
import { get } from 'node:http';
import path from 'node:path';
import { after, before, describe, it } from 'node:test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { Sidecar } from './sidecar';

// `__dirname` works because the test bundle is compiled to CommonJS.
const sidecarDir = path.resolve(__dirname, '../../../sidecar');
const workDir = mkdtempSync(path.join(tmpdir(), 'ohd-supervisor-'));

let sidecar: Sidecar;
let baseUrl: string;
let token: string;

function request(url: string, bearer?: string): Promise<number | 'refused'> {
  return new Promise((resolve) => {
    const req = get(url, bearer ? { headers: { Authorization: `Bearer ${bearer}` } } : {}, (res) => {
      res.resume();
      resolve(res.statusCode ?? 0);
    });
    req.on('error', () => resolve('refused'));
  });
}

describe('Sidecar supervisor', () => {
  before(async () => {
    sidecar = new Sidecar({
      sidecarDir,
      pythonPath: process.env.OHD_PYTHON ?? 'python',
      dataDir: path.join(workDir, 'data'),
      logFile: path.join(workDir, 'sidecar.log'),
    });
    const info = await sidecar.start(90_000);
    baseUrl = info.baseUrl;
    token = info.token;
  });

  after(async () => {
    await sidecar?.stop();
  });

  it('serves health without a token', async () => {
    assert.equal(await request(`${baseUrl}/health`), 200);
  });

  it('rejects authenticated endpoints without the token', async () => {
    assert.equal(await request(`${baseUrl}/api/settings`), 401);
    assert.equal(await request(`${baseUrl}/api/settings`, 'wrong-token'), 401);
  });

  it('accepts the generated session token', async () => {
    assert.equal(await request(`${baseUrl}/api/settings`, token), 200);
  });

  it('generates a strong random token', () => {
    assert.equal(token.length, 64);
    assert.match(token, /^[0-9a-f]+$/);
  });
});

describe('Sidecar supervisor shutdown', () => {
  it('closes the port and releases the process', async () => {
    const local = new Sidecar({
      sidecarDir,
      pythonPath: process.env.OHD_PYTHON ?? 'python',
      dataDir: path.join(workDir, 'data2'),
      logFile: path.join(workDir, 'sidecar2.log'),
    });
    const info = await local.start(90_000);
    assert.equal(await request(`${info.baseUrl}/health`), 200);
    await local.stop();
    assert.equal(await request(`${info.baseUrl}/health`), 'refused');
  });
});
