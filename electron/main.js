const { app, BrowserWindow, dialog, ipcMain, Menu, Notification, powerMonitor, shell, Tray } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

const core = require("./core");
const storage = require("./storage");

const APP_NAME = "干啥来着";
let tray = null;
let state = null;
let recordWindow = null;
let dashboardWindow = null;
let tickTimer = null;
let recordingLock = false;

function getIconPath() {
  const png = path.join(__dirname, "..", "resourse", "icn.png");
  const icns = path.join(__dirname, "..", "icon.icns");
  return fs.existsSync(png) ? png : icns;
}

function loadState() {
  let rawConfig = {};
  try {
    rawConfig = storage.migrateLegacyStorage() || storage.loadJsonFile(storage.CONFIG_FILE) || {};
  } catch (error) {
    storage.logError("加载配置失败", error);
  }

  let activities = [];
  try {
    activities = storage.loadActivitiesFile();
  } catch (error) {
    storage.logError("加载活动历史失败", error);
  }

  state = {
    config: core.normalizeConfig(rawConfig),
    activities,
  };
}

function saveConfig() {
  storage.atomicWriteJson(storage.CONFIG_FILE, state.config);
}

function saveActivities() {
  storage.writeActivitiesFile(state.activities);
}

function buildSnapshot() {
  const summary = core.buildActivitySummary(state.activities);
  const nextReminderTime = core.calculateNextReminderTime(
    state.config.last_check_time,
    state.config.interval_minutes,
  );

  return {
    config: state.config,
    activities: state.activities,
    summary,
    nextReminderTime,
    paths: {
      config: storage.CONFIG_FILE,
      activities: storage.ACTIVITIES_FILE,
      logs: storage.ERROR_LOG_DIR,
    },
  };
}

function notify(title, body) {
  if (Notification.isSupported()) {
    new Notification({ title, body }).show();
  }
}

function sendSnapshot() {
  const snapshot = buildSnapshot();
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send("state:changed", snapshot);
  }
}

function updateTrayMenu() {
  if (!tray) {
    return;
  }

  const last = state.activities[state.activities.length - 1];
  const nextReminderTime = core.calculateNextReminderTime(
    state.config.last_check_time,
    state.config.interval_minutes,
  );

  tray.setTitle(process.platform === "darwin" ? `${state.config.interval_minutes}min` : "");
  tray.setToolTip(`${APP_NAME} - 每 ${state.config.interval_minutes} 分钟提醒`);
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "立即记录", click: () => showRecordWindow("manual") },
    { type: "separator" },
    { label: last ? `上次记录: ${last.activity}` : "暂无记录", enabled: false },
    {
      label: `上次提醒: ${core.formatMenuDatetime(state.config.last_reminder_time)}`,
      enabled: false,
    },
    {
      label: `下次提醒: ${core.formatMenuDatetime(nextReminderTime)}`,
      enabled: false,
    },
    { type: "separator" },
    { label: "打开面板", click: () => showDashboardWindow() },
    { label: "今日汇总", click: () => showDashboardWindow("today") },
    { label: "本周汇总", click: () => showDashboardWindow("week") },
    { label: "全部记录", click: () => showDashboardWindow("all") },
    { type: "separator" },
    {
      label: "开机自启",
      type: "checkbox",
      checked: app.getLoginItemSettings().openAtLogin,
      click: (item) => app.setLoginItemSettings({ openAtLogin: item.checked }),
    },
    { label: "打开错误日志文件夹", click: () => shell.openPath(storage.ERROR_LOG_DIR) },
    { type: "separator" },
    { label: "退出", click: () => app.quit() },
  ]));
}

function createWindow(options = {}) {
  return new BrowserWindow({
    width: options.width || 860,
    height: options.height || 620,
    minWidth: 420,
    minHeight: 480,
    title: APP_NAME,
    show: false,
    icon: getIconPath(),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
}

function showRecordWindow(reason = "timer") {
  if (recordingLock && recordWindow && !recordWindow.isDestroyed()) {
    recordWindow.focus();
    return;
  }

  recordingLock = true;
  state.config.last_reminder_time = core.toLocalIso();
  saveConfig();
  updateTrayMenu();

  recordWindow = createWindow({ width: 560, height: 560 });
  recordWindow.loadFile(path.join(__dirname, "renderer", "index.html"), {
    query: { view: "record", reason },
  });
  recordWindow.once("ready-to-show", () => recordWindow.show());
  recordWindow.on("closed", () => {
    recordingLock = false;
    recordWindow = null;
  });
}

function showDashboardWindow(view = "all") {
  if (dashboardWindow && !dashboardWindow.isDestroyed()) {
    dashboardWindow.focus();
    dashboardWindow.webContents.send("view:set", view);
    return;
  }

  dashboardWindow = createWindow({ width: 980, height: 720 });
  dashboardWindow.loadFile(path.join(__dirname, "renderer", "index.html"), {
    query: { view },
  });
  dashboardWindow.once("ready-to-show", () => dashboardWindow.show());
  dashboardWindow.on("closed", () => {
    dashboardWindow = null;
  });
}

function recordActivities(activities) {
  const now = new Date();
  const rows = activities.map((activity) => ({
    timestamp: core.toLocalIso(now),
    date: core.formatDate(now),
    time: core.formatTime(now),
    activity,
  }));

  for (const row of rows) {
    state.activities.push(row);
    storage.appendActivityFile(row);
  }

  state.config.last_check_time = core.toLocalIso(now);
  saveConfig();
  notify(APP_NAME, `已记录: ${activities.join("、")}`);
  updateTrayMenu();
  sendSnapshot();
}

function maybeShowDailySummary(now) {
  if (!core.isDailySummaryDue(now, state.config.daily_summary_time, state.config.last_daily_summary_date)) {
    return;
  }

  state.config.last_daily_summary_date = core.formatDate(now);
  saveConfig();
  showDashboardWindow("today");
}

function tick() {
  if (!state || recordingLock) {
    return;
  }

  const now = new Date();
  maybeShowDailySummary(now);

  if (!state.config.last_check_time) {
    state.config.last_check_time = core.toLocalIso(now);
    saveConfig();
    updateTrayMenu();
    return;
  }

  const lastCheck = core.parseIsoDate(state.config.last_check_time);
  if (!lastCheck) {
    state.config.last_check_time = core.toLocalIso(now);
    saveConfig();
    return;
  }

  const elapsedMinutes = (now.getTime() - lastCheck.getTime()) / 60000;
  if (elapsedMinutes < state.config.interval_minutes) {
    return;
  }

  const idleMinutes = powerMonitor.getSystemIdleTime() / 60;
  if (state.config.idle_threshold_minutes === 0 || idleMinutes < state.config.idle_threshold_minutes) {
    showRecordWindow("timer");
  }
}

function exportJson() {
  const now = new Date();
  const filePath = path.join(app.getPath("downloads"), `TimeRecorder-activities-${now.toISOString().replace(/[-:]/g, "").slice(0, 15)}.json`);
  const payload = {
    app: APP_NAME,
    version: app.getVersion(),
    exported_at: core.toLocalIso(now),
    total: state.activities.length,
    activities: state.activities,
  };
  fs.writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  return filePath;
}

function exportCsv() {
  const now = new Date();
  const filePath = path.join(app.getPath("downloads"), `TimeRecorder-activities-${now.toISOString().replace(/[-:]/g, "").slice(0, 15)}.csv`);
  const header = "timestamp,date,time,activity\n";
  const rows = state.activities.map((activity) => (
    ["timestamp", "date", "time", "activity"]
      .map((key) => `"${String(activity[key] || "").replace(/"/g, '""')}"`)
      .join(",")
  ));
  fs.writeFileSync(filePath, `${header}${rows.join("\n")}${rows.length ? "\n" : ""}`, "utf8");
  return filePath;
}

function registerIpc() {
  ipcMain.handle("state:get", () => buildSnapshot());
  ipcMain.handle("record:submit", (_event, payload) => {
    const activities = core.parseActivityInput(
      [...(payload.selected || []), payload.custom || ""].join("、"),
      state.config.presets,
    );
    if (!activities.length) {
      return { ok: false, message: "请选择或输入至少一个活动" };
    }
    recordActivities(activities);
    recordWindow?.close();
    return { ok: true };
  });
  ipcMain.handle("record:skip", () => {
    state.config.last_check_time = core.toLocalIso();
    saveConfig();
    recordWindow?.close();
    updateTrayMenu();
    return { ok: true };
  });
  ipcMain.handle("settings:update", (_event, patch) => {
    state.config = core.normalizeConfig({ ...state.config, ...patch });
    saveConfig();
    updateTrayMenu();
    sendSnapshot();
    return buildSnapshot();
  });
  ipcMain.handle("presets:add", (_event, name) => {
    state.config.presets = core.normalizePresets([...state.config.presets, name]);
    saveConfig();
    updateTrayMenu();
    sendSnapshot();
    return buildSnapshot();
  });
  ipcMain.handle("presets:delete", (_event, index) => {
    state.config.presets = state.config.presets.filter((_preset, presetIndex) => presetIndex !== index);
    state.config = core.normalizeConfig(state.config);
    saveConfig();
    sendSnapshot();
    return buildSnapshot();
  });
  ipcMain.handle("presets:reset", () => {
    state.config.presets = [...core.DEFAULT_PRESETS];
    saveConfig();
    sendSnapshot();
    return buildSnapshot();
  });
  ipcMain.handle("activities:clear", async () => {
    const result = await dialog.showMessageBox({
      type: "warning",
      buttons: ["取消", "清空"],
      defaultId: 0,
      cancelId: 0,
      message: "确定清空全部记录吗？",
    });
    if (result.response === 1) {
      state.activities = [];
      saveActivities();
      updateTrayMenu();
      sendSnapshot();
    }
    return buildSnapshot();
  });
  ipcMain.handle("export:json", () => exportJson());
  ipcMain.handle("export:csv", () => exportCsv());
  ipcMain.handle("logs:open", () => shell.openPath(storage.ERROR_LOG_DIR));
}

app.whenReady().then(() => {
  loadState();
  registerIpc();

  tray = new Tray(getIconPath());
  tray.on("click", () => showRecordWindow("tray"));
  updateTrayMenu();

  tickTimer = setInterval(tick, 1000);
  app.on("activate", () => showDashboardWindow());
});

app.on("window-all-closed", (event) => {
  event.preventDefault();
});

app.on("before-quit", () => {
  if (tickTimer) {
    clearInterval(tickTimer);
  }
});
