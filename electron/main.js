/**
 * LinkedIn Helper — Electron Main Process
 *
 * Spawns the bundled Python/Flask backend on a free port,
 * waits for it to become ready, then opens a BrowserWindow.
 */

const { app, BrowserWindow, dialog, shell } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const http = require("http");
const net = require("net");
const fs = require("fs");

// ─── Globals ─────────────────────────────────────────────────────────────────
let mainWindow = null;
let pythonProcess = null;
let serverPort = null;

// ─── Determine if we are running from a packaged .app or in dev ──────────────
const isPacked = app.isPackaged;

function getResourcesPath() {
  if (isPacked) {
    // Inside .app/Contents/Resources
    return process.resourcesPath;
  }
  // Dev mode — resources sit next to electron dir
  return path.join(__dirname, "..");
}

/**
 * Get the path to the Python backend executable.
 * In production: bundled PyInstaller folder at Resources/python_app/linkedin_helper
 * In dev: system python running app.py
 */
function getPythonCommand() {
  if (isPacked) {
    // On Windows: linkedin_helper.exe, on macOS/Linux: linkedin_helper
    const exeName =
      process.platform === "win32" ? "linkedin_helper.exe" : "linkedin_helper";

    // Try: Resources/python_app/linkedin_helper(.exe)
    const exePath = path.join(process.resourcesPath, "python_app", exeName);
    if (fs.existsSync(exePath)) return { exe: exePath, args: [] };

    // Fallback: Resources/python_app/linkedin_helper/linkedin_helper(.exe)
    const exePathAlt = path.join(
      process.resourcesPath,
      "python_app",
      "linkedin_helper",
      exeName
    );
    if (fs.existsSync(exePathAlt)) return { exe: exePathAlt, args: [] };
  }
  // Dev mode — use python3 on macOS/Linux, python on Windows
  const pythonExe = process.platform === "win32" ? "python" : "python3";
  return {
    exe: pythonExe,
    args: [path.join(__dirname, "..", "app.py")],
  };
}

/**
 * Find an available TCP port.
 */
function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
    server.on("error", reject);
  });
}

/**
 * Wait for the Flask server to respond on /health.
 */
function waitForServer(port, maxRetries = 60, interval = 500) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const check = () => {
      attempts++;
      const req = http.get(`http://127.0.0.1:${port}/health`, (res) => {
        if (res.statusCode === 200) {
          resolve();
        } else if (attempts < maxRetries) {
          setTimeout(check, interval);
        } else {
          reject(new Error(`Server responded with status ${res.statusCode}`));
        }
      });
      req.on("error", () => {
        if (attempts < maxRetries) {
          setTimeout(check, interval);
        } else {
          reject(
            new Error(`Server not reachable after ${maxRetries} attempts`)
          );
        }
      });
      req.setTimeout(2000, () => {
        req.destroy();
        if (attempts < maxRetries) {
          setTimeout(check, interval);
        } else {
          reject(new Error("Server timeout"));
        }
      });
    };
    check();
  });
}

/**
 * Start the Python Flask backend.
 */
async function startPythonServer() {
  serverPort = await getFreePort();
  const { exe, args } = getPythonCommand();

  console.log(`[Electron] Starting Python server on port ${serverPort}`);
  console.log(`[Electron] Command: ${exe} ${args.join(" ")}`);

  // Set up environment
  const env = {
    ...process.env,
    PORT: String(serverPort),
    FLASK_ENV: "production",
    ELECTRON_APP: "1",
    HEADLESS: "0",  // Desktop app: use headed browser (visible)
  };

  // For packaged app, set Playwright browser path
  if (isPacked) {
    const browsersPath = path.join(process.resourcesPath, "playwright_browsers");
    if (fs.existsSync(browsersPath)) {
      env.PLAYWRIGHT_BROWSERS_PATH = browsersPath;
    }
    // Set data directory for SQLite databases
    const dataDir = path.join(app.getPath("userData"), "data");
    if (!fs.existsSync(dataDir)) {
      fs.mkdirSync(dataDir, { recursive: true });
    }
    env.DATABASE_URL = `sqlite:///${path.join(dataDir, "web_app.db")}`;
    env.DATA_DIR = dataDir;
  }

  pythonProcess = spawn(exe, args, {
    env,
    stdio: ["pipe", "pipe", "pipe"],
    cwd: isPacked
      ? path.join(process.resourcesPath, "python_app")
      : path.join(__dirname, ".."),
  });

  pythonProcess.stdout.on("data", (data) => {
    console.log(`[Python] ${data.toString().trim()}`);
  });

  pythonProcess.stderr.on("data", (data) => {
    console.error(`[Python:err] ${data.toString().trim()}`);
  });

  pythonProcess.on("exit", (code, signal) => {
    console.log(`[Electron] Python process exited (code=${code}, signal=${signal})`);
    pythonProcess = null;
    // If the window is still open and Python crashed, show error
    if (mainWindow && !mainWindow.isDestroyed() && code !== 0 && code !== null) {
      dialog.showErrorBox(
        "Backend Error",
        `The LinkedIn Helper backend stopped unexpectedly (exit code ${code}).\n\nPlease restart the application.`
      );
    }
  });

  // Wait for server to be ready
  try {
    await waitForServer(serverPort);
    console.log(`[Electron] Python server is ready on port ${serverPort}`);
  } catch (err) {
    console.error("[Electron] Failed to start Python server:", err.message);
    dialog.showErrorBox(
      "Startup Error",
      `Could not start the LinkedIn Helper backend.\n\n${err.message}\n\nPlease try restarting the application.`
    );
    app.quit();
    return false;
  }
  return true;
}

/**
 * Create the main application window.
 */
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: "LinkedIn Helper",
    icon: path.join(__dirname, "icons", "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
    },
    show: false, // Show after content loads
  });

  // Load the Flask app
  mainWindow.loadURL(`http://127.0.0.1:${serverPort}/`);

  // Show window when ready
  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
    mainWindow.focus();
  });

  // Open external links in system browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("http") && !url.includes("127.0.0.1")) {
      shell.openExternal(url);
      return { action: "deny" };
    }
    return { action: "allow" };
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

/**
 * Gracefully shut down the Python server.
 */
function killPythonServer() {
  if (pythonProcess) {
    console.log("[Electron] Shutting down Python server...");
    if (process.platform === "win32") {
      // Windows: use taskkill to kill the process tree
      const { execSync } = require("child_process");
      try {
        execSync(`taskkill /pid ${pythonProcess.pid} /T /F`, {
          stdio: "ignore",
        });
      } catch (e) {
        // Process may have already exited
      }
    } else {
      pythonProcess.kill("SIGTERM");
      setTimeout(() => {
        if (pythonProcess) {
          console.log("[Electron] Force-killing Python server...");
          pythonProcess.kill("SIGKILL");
        }
      }, 5000);
    }
  }
}

// ─── App Lifecycle ───────────────────────────────────────────────────────────

app.on("ready", async () => {
  const started = await startPythonServer();
  if (started) {
    createWindow();
  }
});

app.on("window-all-closed", () => {
  killPythonServer();
  app.quit();
});

app.on("before-quit", () => {
  killPythonServer();
});

app.on("activate", () => {
  // macOS: re-create window when dock icon is clicked
  if (BrowserWindow.getAllWindows().length === 0 && serverPort) {
    createWindow();
  }
});
