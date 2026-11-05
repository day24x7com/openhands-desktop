/**
 * Preload bridge: the only surface the renderer can use to reach the shell.
 * Nothing else (no node, no ipcRenderer) is exposed to page scripts.
 */
import { contextBridge, ipcRenderer } from 'electron';

const api = {
  getSidecarConfig: () => ipcRenderer.invoke('sidecar:config'),
  pickDirectory: () => ipcRenderer.invoke('dialog:pick-directory'),
  openExternal: (url: string) => ipcRenderer.invoke('shell:open-external', url),
  getVersion: () => ipcRenderer.invoke('app:version'),
  getDataDir: () => ipcRenderer.invoke('app:data-dir'),
  onSidecarExit: (callback: (code: number | null) => void) => {
    const listener = (_event: unknown, code: number | null) => callback(code);
    ipcRenderer.on('sidecar:exited', listener);
    return () => ipcRenderer.removeListener('sidecar:exited', listener);
  },
  platform: process.platform,
};

contextBridge.exposeInMainWorld('openhands', api);

export type OpenHandsBridge = typeof api;
