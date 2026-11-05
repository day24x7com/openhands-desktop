import { app, BrowserWindow, dialog, ipcMain, Menu, shell as electronShell } from 'electron';
import log from 'electron-log';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { Sidecar } from './sidecar';

// Dev mode loads the Vite dev server instead of the packaged bundle.
const isDev = !app.isPackaged && (process.env.OHD_DEV === '1' || process.argv.includes('--dev'));
const DEV_UI_URL = process.env.OHD_DEV_URL ?? 'http://localhost:5173';

let mainWindow: BrowserWindow | null = null;
let sidecar: Sidecar | null = null;

app.setName('OpenHands Desktop');
log.transports.file.level = 'info';

/** Resolve the sidecar package root, and the interpreter that can run it. */
function resolveSidecarPaths(): { sidecarDir: string; pythonPath: string } {
  if (isDev) {
    // scripts/setup_dev.py installs the sidecar into .venv, so prefer that over
    // whatever `python` resolves to on PATH.
    const sidecarDir = path.resolve(__dirname, '../../../sidecar');
    const venvPython = path.resolve(
      __dirname,
      '../../../.venv',
      process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
    );
    const pythonPath = process.env.OHD_PYTHON ?? (existsSync(venvPython) ? venvPython : 'python');
    return { sidecarDir, pythonPath };
  }
  const resources = process.resourcesPath;
  const bundledPython = path.join(resources, 'sidecar-runtime', 'python.exe');
  return {
    sidecarDir: path.join(resources, 'sidecar'),
    pythonPath: existsSync(bundledPython) ? bundledPython : 'python',
  };
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 940,
    minHeight: 620,
    show: false,
    backgroundColor: '#0b0e14',
    title: 'OpenHands Desktop',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      webSecurity: true,
      spellcheck: false,
    },
  });

  mainWindow.once('ready-to-show', () => mainWindow?.show());
  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // External links open in the user's browser, never inside the app shell.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    void electronShell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, url) => {
    const allowed = isDev ? DEV_UI_URL : 'file://';
    if (!url.startsWith(allowed)) {
      event.preventDefault();
      void electronShell.openExternal(url);
    }
  });

  if (isDev) {
    void mainWindow.loadURL(DEV_UI_URL);
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    void mainWindow.loadFile(path.join(__dirname, '../../ui/dist/index.html'));
  }
}

function buildMenu(): void {
  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: 'File',
      submenu: [
        {
          label: 'Open Logs Folder',
          click: () => {
            if (sidecar) void electronShell.openPath(path.dirname(sidecar.logPath()));
          },
        },
        { type: 'separator' },
        { role: 'quit' },
      ],
    },
    { label: 'Edit', submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
    {
      label: 'Help',
      submenu: [
        { label: 'Documentation', click: () => void electronShell.openExternal('https://docs.all-hands.dev') },
        {
          label: 'Sidecar Logs',
          click: () => {
            if (sidecar) void electronShell.openPath(sidecar.logPath());
          },
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function registerIpc(): void {
  ipcMain.handle('sidecar:config', () => ({
    baseUrl: sidecar?.baseUrl ?? '',
    token: sidecar?.token ?? null,
  }));

  ipcMain.handle('dialog:pick-directory', async () => {
    if (!mainWindow) return null;
    const result = await dialog.showOpenDialog(mainWindow, {
      title: 'Select a project folder',
      properties: ['openDirectory', 'createDirectory'],
    });
    return result.canceled || !result.filePaths[0] ? null : result.filePaths[0];
  });

  ipcMain.handle('shell:open-external', async (_event, url: string) => {
    if (/^https?:\/\//i.test(url)) await electronShell.openExternal(url);
  });

  ipcMain.handle('app:version', () => app.getVersion());
  ipcMain.handle('app:data-dir', () => app.getPath('userData'));
}

async function boot(): Promise<void> {
  const { sidecarDir, pythonPath } = resolveSidecarPaths();
  const dataDir = path.join(app.getPath('userData'), 'data');
  const logFile = path.join(app.getPath('userData'), 'logs', 'sidecar.log');

  sidecar = new Sidecar({ sidecarDir, pythonPath, dataDir, logFile });
  sidecar.onUnexpectedExit = (code) => {
    log.error(`sidecar exited unexpectedly (code ${code})`);
    mainWindow?.webContents.send('sidecar:exited', code);
  };

  try {
    const info = await sidecar.start();
    log.info(`sidecar ready at ${info.baseUrl} (pid ${info.pid})`);
  } catch (error) {
    log.error('sidecar failed to start', error);
    dialog.showErrorBox(
      'Could not start the agent service',
      `${(error as Error).message}\n\nLogs: ${logFile}\n\nMake sure Python 3.11+ is installed.`,
    );
  }

  registerIpc();
  buildMenu();
  createWindow();
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  void app.whenReady().then(boot);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
  });

  // Never leave an orphaned Python process behind.
  app.on('before-quit', async (event) => {
    if (!sidecar) return;
    event.preventDefault();
    await sidecar.stop();
    sidecar = null;
    app.quit();
  });

  process.on('exit', () => {
    void sidecar?.stop();
  });
}
