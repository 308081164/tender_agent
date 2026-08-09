const { app, BrowserWindow, dialog } = require("electron");
const path = require("path");
const fs = require("fs");
const http = require("http");
const { spawn } = require("child_process");

const DEFAULT_PORT = 18766;
const WINDOW_TITLE = "标书智能体";
const WINDOW_WIDTH = 1360;
const WINDOW_HEIGHT = 860;

function resolveAppIcon() {
  const name = process.platform === "win32" ? "icon.ico" : "icon.png";
  const candidates = [];
  if (process.execPath) {
    candidates.push(path.join(path.dirname(process.execPath), name));
  }
  if (process.resourcesPath) {
    candidates.push(path.join(process.resourcesPath, name));
  }
  candidates.push(path.join(__dirname, name));
  for (const candidate of candidates) {
    try {
      if (candidate && fs.existsSync(candidate)) {
        return candidate;
      }
    } catch (_) {
      /* ignore */
    }
  }
  return path.join(__dirname, name);
}

const APP_ICON = resolveAppIcon();
const HEALTH_TIMEOUT_MS = 120000;
const LOADING_ERROR_TIMEOUT_MS = 120000;
const ELECTRON_LOG_FILE = "electron.log";

let mainWindow = null;
let loadingWindow = null;
let backendProc = null;
let backendOwned = false;
let installDir = null;
let dataDir = null;
let logStream = null;
let isQuitting = false;
let bootstrapDone = false;
let loadingErrorTimer = null;

function resolveInstallDir() {
  if (process.env.TENDER_INSTALL_DIR) {
    return path.resolve(process.env.TENDER_INSTALL_DIR);
  }
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "tender-agent");
  }
  return path.resolve(__dirname, "..", "..");
}

function resolveDataDir() {
  if (process.env.TENDER_DATA_DIR) {
    return path.resolve(process.env.TENDER_DATA_DIR);
  }
  const local = process.env.LOCALAPPDATA || path.join(require("os").homedir(), "AppData", "Local");
  return path.join(local, "TenderAgent", "data");
}

function initLog() {
  try {
    fs.mkdirSync(dataDir, { recursive: true });
    const logPath = path.join(dataDir, ELECTRON_LOG_FILE);
    logStream = fs.createWriteStream(logPath, { flags: "a", encoding: "utf8" });
    logStream.write(
      `\n--- TenderAgent Electron ${new Date().toISOString()} pid=${process.pid} ---\n`
    );
  } catch (_err) {
    logStream = null;
  }
}

function log(message) {
  const line = `[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] ${message}`;
  if (logStream) {
    logStream.write(`${line}\n`);
  }
}

function runtimePython() {
  const candidates = [
    path.join(installDir, "runtime", "Scripts", "python.exe"),
    path.join(installDir, "runtime", "bin", "python.exe"),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return candidates[0];
}

function showError(title, message) {
  log(`ERROR: ${message.split("\n")[0]}`);
  dialog.showErrorBox(title, message);
}

function setLoadingStatus(text) {
  if (!loadingWindow || loadingWindow.isDestroyed()) {
    return;
  }
  const payload = JSON.stringify(String(text));
  loadingWindow.webContents
    .executeJavaScript(`window.__setStatus && window.__setStatus(${payload})`)
    .catch(() => {});
}

function clearLoadingErrorTimer() {
  if (loadingErrorTimer) {
    clearTimeout(loadingErrorTimer);
    loadingErrorTimer = null;
  }
}

function armLoadingErrorTimer(phase) {
  clearLoadingErrorTimer();
  loadingErrorTimer = setTimeout(() => {
    if (bootstrapDone || isQuitting) {
      return;
    }
    const logHint = path.join(dataDir, ELECTRON_LOG_FILE);
    const msg = `启动超时（${phase}）。\n\n请查看日志：\n${path.join(
      dataDir,
      "backend.log"
    )}\n${path.join(dataDir, "launcher.log")}\n${logHint}`;
    log(`ERROR: bootstrap timeout during ${phase}`);
    setLoadingStatus("启动超时，请查看日志…");
    showError("标书智能体启动失败", msg);
    killBackendTree();
    isQuitting = true;
    app.quit();
  }, LOADING_ERROR_TIMEOUT_MS);
}

function createLoadingWindow() {
  loadingWindow = new BrowserWindow({
    width: 480,
    height: 320,
    title: WINDOW_TITLE,
    icon: APP_ICON,
    resizable: false,
    minimizable: true,
    maximizable: false,
    autoHideMenuBar: true,
    show: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });
  loadingWindow.loadFile(path.join(__dirname, "loading.html"));
  loadingWindow.on("closed", () => {
    loadingWindow = null;
  });
}

function createMainWindow(url) {
  if (loadingWindow) {
    loadingWindow.close();
    loadingWindow = null;
  }

  mainWindow = new BrowserWindow({
    width: WINDOW_WIDTH,
    height: WINDOW_HEIGHT,
    title: WINDOW_TITLE,
    icon: APP_ICON,
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
    mainWindow.focus();
  });

  mainWindow.webContents.setWindowOpenHandler(({ url: targetUrl }) => {
    if (targetUrl.startsWith("http://127.0.0.1:") || targetUrl.startsWith("http://localhost:")) {
      return { action: "allow" };
    }
    return { action: "deny" };
  });

  mainWindow.loadURL(url);
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function focusExistingWindow() {
  if (mainWindow) {
    if (mainWindow.isMinimized()) {
      mainWindow.restore();
    }
    mainWindow.show();
    mainWindow.focus();
    return true;
  }
  if (loadingWindow) {
    loadingWindow.show();
    loadingWindow.focus();
    return true;
  }
  return false;
}

function healthCheck(port) {
  return new Promise((resolve) => {
    const req = http.get(
      {
        hostname: "127.0.0.1",
        port,
        path: "/api/health",
        timeout: 2000,
      },
      (res) => {
        res.resume();
        resolve(res.statusCode === 200);
      }
    );
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitForBackend(port, timeoutMs = HEALTH_TIMEOUT_MS) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (backendProc && backendProc.exitCode !== null) {
      return false;
    }
    if (await healthCheck(port)) {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

function startBackend(port) {
  const python = runtimePython();
  const script = path.join(installDir, "desktop", "backend_launcher.py");
  if (!fs.existsSync(python)) {
    throw new Error(`未找到运行时 Python：${python}`);
  }
  if (!fs.existsSync(script)) {
    throw new Error(`未找到后端启动脚本：${script}`);
  }

  const env = {
    ...process.env,
    TENDER_DESKTOP: "1",
    TENDER_INSTALL_DIR: installDir,
    TENDER_DATA_DIR: dataDir,
    PYTHONUTF8: "1",
  };

  log(`starting backend: ${python} ${script} --port ${port}`);
  backendProc = spawn(python, [script, "--port", String(port)], {
    cwd: installDir,
    env,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  backendOwned = true;

  backendProc.stdout?.on("data", (chunk) => {
    for (const line of chunk.toString().split(/\r?\n/)) {
      if (line.trim()) {
        log(`backend: ${line.trim()}`);
      }
    }
  });
  backendProc.stderr?.on("data", (chunk) => {
    for (const line of chunk.toString().split(/\r?\n/)) {
      if (line.trim()) {
        log(`backend stderr: ${line.trim()}`);
      }
    }
  });

  backendProc.on("error", (err) => {
    log(`backend spawn error: ${err.message}`);
    if (!isQuitting) {
      showError(
        "标书智能体",
        `无法启动后端进程。\n\n${err.message}\n\n日志：${path.join(dataDir, "electron.log")}`
      );
      app.quit();
    }
  });

  backendProc.on("exit", (code, signal) => {
    log(`backend exited code=${code} signal=${signal}`);
    backendProc = null;
    if (!isQuitting) {
      showError(
        "标书智能体",
        `后端已意外退出${code !== null ? `（代码 ${code}）` : ""}。\n\n请查看日志：\n${path.join(
          dataDir,
          "backend.log"
        )}\n${path.join(dataDir, "launcher.log")}\n${path.join(dataDir, "postgres.log")}\n\n若首次安装后仍失败，可尝试删除数据目录后重试：\n${dataDir}`
      );
      app.quit();
    }
  });
}

function readBackendPidFromState() {
  try {
    const statePath = path.join(dataDir, "server.json");
    if (!fs.existsSync(statePath)) {
      return null;
    }
    const state = JSON.parse(fs.readFileSync(statePath, "utf8"));
    const pid = Number(state.pid);
    return Number.isFinite(pid) && pid > 0 ? pid : null;
  } catch (_err) {
    return null;
  }
}

function killBackendTree() {
  const pid = backendProc?.pid || (backendOwned ? readBackendPidFromState() : null);
  if (!pid) {
    return;
  }
  log(`killing backend tree pid=${pid}`);
  spawn("taskkill", ["/F", "/T", "/PID", String(pid)], {
    windowsHide: true,
    stdio: "ignore",
  });
  backendProc = null;
  backendOwned = false;
}

async function attachToExistingBackend(port) {
  if (!(await healthCheck(port))) {
    return false;
  }
  log(`attaching to existing backend on port ${port}`);
  backendOwned = true;
  return true;
}

async function bootstrap() {
  installDir = resolveInstallDir();
  dataDir = resolveDataDir();
  initLog();
  log(`install_dir=${installDir} packaged=${app.isPackaged}`);

  createLoadingWindow();
  setLoadingStatus("正在启动数据库与存储服务…");
  armLoadingErrorTimer("后端启动");

  const port = DEFAULT_PORT;
  let ready = await attachToExistingBackend(port);
  if (!ready) {
    try {
      startBackend(port);
    } catch (err) {
      clearLoadingErrorTimer();
      showError(
        "标书智能体",
        `${err.message}\n\n请确认安装目录完整。\n日志：${path.join(dataDir, "electron.log")}`
      );
      isQuitting = true;
      app.quit();
      return;
    }
    setLoadingStatus("正在等待服务就绪…");
    ready = await waitForBackend(port);
  }

  if (!ready) {
    clearLoadingErrorTimer();
    showError(
      "标书智能体",
      `后端启动超时（端口 ${port}）。\n\n请查看：\n${path.join(dataDir, "backend.log")}\n${path.join(
        dataDir,
        "launcher.log"
      )}\n${path.join(dataDir, "electron.log")}`
    );
    killBackendTree();
    isQuitting = true;
    app.quit();
    return;
  }

  clearLoadingErrorTimer();
  bootstrapDone = true;
  log(`loading UI http://127.0.0.1:${port}`);
  createMainWindow(`http://127.0.0.1:${port}`);
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    log("second instance — focusing existing window");
    focusExistingWindow();
  });

  app.whenReady().then(bootstrap);

  app.on("before-quit", () => {
    isQuitting = true;
    killBackendTree();
    if (logStream) {
      logStream.end();
      logStream = null;
    }
  });

  app.on("window-all-closed", () => {
    app.quit();
  });
}
