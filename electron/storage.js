const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const CONFIG_FILE = path.join(os.homedir(), ".time_recorder_config.json");
const ACTIVITIES_FILE = path.join(os.homedir(), ".time_recorder_activities.jsonl");
const LEGACY_CONFIG_FILE = path.join(os.homedir(), ".time_recorder.json");
const ERROR_LOG_DIR = path.join(os.homedir(), "Library", "Logs", "TimeRecorder");
const ERROR_LOG_FILE = path.join(ERROR_LOG_DIR, "error.log");

function ensureDir(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
}

function atomicWriteJson(filePath, data) {
  ensureDir(filePath);
  const tmpPath = `${filePath}.${process.pid}.tmp`;
  fs.writeFileSync(tmpPath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
  fs.renameSync(tmpPath, filePath);
}

function writeActivitiesFile(activities, filePath = ACTIVITIES_FILE) {
  ensureDir(filePath);
  const tmpPath = `${filePath}.${process.pid}.tmp`;
  const body = (activities || []).map((activity) => JSON.stringify(activity)).join("\n");
  fs.writeFileSync(tmpPath, body ? `${body}\n` : "", "utf8");
  fs.renameSync(tmpPath, filePath);
}

function appendActivityFile(activity, filePath = ACTIVITIES_FILE) {
  ensureDir(filePath);
  fs.appendFileSync(filePath, `${JSON.stringify(activity)}\n`, "utf8");
}

function loadJsonFile(filePath) {
  if (!fs.existsSync(filePath)) {
    return null;
  }
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function loadActivitiesFile(filePath = ACTIVITIES_FILE) {
  if (!fs.existsSync(filePath)) {
    return [];
  }

  const body = fs.readFileSync(filePath, "utf8").trim();
  if (!body) {
    return [];
  }
  if (body.startsWith("[")) {
    const data = JSON.parse(body);
    return Array.isArray(data) ? data : [];
  }

  return body
    .split(/\n+/)
    .map((line) => {
      try {
        const item = JSON.parse(line);
        return item && typeof item === "object" ? item : null;
      } catch {
        return null;
      }
    })
    .filter(Boolean);
}

function migrateLegacyStorage() {
  if (fs.existsSync(CONFIG_FILE) || !fs.existsSync(LEGACY_CONFIG_FILE)) {
    return null;
  }

  const legacy = loadJsonFile(LEGACY_CONFIG_FILE) || {};
  const { activities, ...config } = legacy;
  atomicWriteJson(CONFIG_FILE, config);
  if (Array.isArray(activities) && activities.length && !fs.existsSync(ACTIVITIES_FILE)) {
    writeActivitiesFile(activities);
  }
  return config;
}

function logError(context, error) {
  fs.mkdirSync(ERROR_LOG_DIR, { recursive: true });
  const message = [
    "=".repeat(80),
    `[${new Date().toISOString()}] ${context}`,
    error?.stack || error?.message || String(error),
    "",
  ].join("\n");
  fs.appendFileSync(ERROR_LOG_FILE, message, "utf8");
}

module.exports = {
  CONFIG_FILE,
  ACTIVITIES_FILE,
  LEGACY_CONFIG_FILE,
  ERROR_LOG_DIR,
  ERROR_LOG_FILE,
  atomicWriteJson,
  writeActivitiesFile,
  appendActivityFile,
  loadJsonFile,
  loadActivitiesFile,
  migrateLegacyStorage,
  logError,
};
