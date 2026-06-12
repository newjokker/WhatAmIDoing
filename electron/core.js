const DEFAULT_INTERVAL = 5;
const DEFAULT_IDLE_THRESHOLD = 5;
const DEFAULT_DAILY_SUMMARY_TIME = "17:30";
const DEFAULT_PRESETS = ["写代码", "开会", "阅读", "学习", "思考", "摸鱼"];
const MAX_ACTIVITY_LENGTH = 20;
const MAX_PRESETS = 12;

function normalizeActivityName(text) {
  return String(text || "").trim().replace(/\s+/g, " ").slice(0, MAX_ACTIVITY_LENGTH);
}

function normalizePresets(presets, limit = MAX_PRESETS) {
  const cleaned = [];
  const seen = new Set();

  for (const preset of presets || []) {
    const name = normalizeActivityName(preset);
    if (name && !seen.has(name)) {
      cleaned.push(name);
      seen.add(name);
    }
    if (cleaned.length >= limit) {
      break;
    }
  }

  return cleaned;
}

function parseActivityInput(text, presets) {
  const activities = [];
  const seen = new Set();
  const parts = String(text || "").split(/[,，、\n]+/);

  for (const part of parts) {
    const raw = part.trim();
    if (!raw) {
      continue;
    }

    let activity = raw;
    if (/^\d+$/.test(raw)) {
      const index = Number(raw) - 1;
      if (index >= 0 && index < presets.length) {
        activity = presets[index];
      }
    }

    activity = normalizeActivityName(activity);
    if (activity && !seen.has(activity)) {
      activities.push(activity);
      seen.add(activity);
    }
  }

  return activities;
}

function parseIsoDate(value) {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime()) ? date : null;
}

function toLocalIso(date = new Date()) {
  const pad = (value) => String(value).padStart(2, "0");
  return [
    date.getFullYear(),
    "-",
    pad(date.getMonth() + 1),
    "-",
    pad(date.getDate()),
    "T",
    pad(date.getHours()),
    ":",
    pad(date.getMinutes()),
    ":",
    pad(date.getSeconds()),
  ].join("");
}

function formatDate(date = new Date()) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function formatTime(date = new Date()) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatMenuDatetime(value, now = new Date()) {
  const date = parseIsoDate(value);
  if (!date) {
    return "暂无";
  }

  const today = formatDate(now);
  const tomorrowDate = new Date(now);
  tomorrowDate.setDate(tomorrowDate.getDate() + 1);

  if (formatDate(date) === today) {
    return `今天 ${formatTime(date)}`;
  }
  if (formatDate(date) === formatDate(tomorrowDate)) {
    return `明天 ${formatTime(date)}`;
  }
  return `${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${formatTime(date)}`;
}

function calculateNextReminderTime(lastCheckTime, intervalMinutes) {
  const lastCheck = parseIsoDate(lastCheckTime);
  if (!lastCheck) {
    return null;
  }
  return toLocalIso(new Date(lastCheck.getTime() + Number(intervalMinutes) * 60 * 1000));
}

function normalizeDailySummaryTime(value) {
  if (value === null || value === undefined) {
    return null;
  }

  const text = String(value).trim();
  if (!text || ["off", "none", "false", "关闭"].includes(text.toLowerCase())) {
    return null;
  }

  const match = text.match(/^(\d{1,2}):(\d{1,2})$/);
  if (!match) {
    return null;
  }

  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) {
    return null;
  }

  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function isDailySummaryDue(now, dailySummaryTime, lastDailySummaryDate) {
  const summaryTime = normalizeDailySummaryTime(dailySummaryTime);
  if (!summaryTime) {
    return false;
  }

  const today = formatDate(now);
  if (lastDailySummaryDate === today) {
    return false;
  }

  const [hour, minute] = summaryTime.split(":").map(Number);
  const target = new Date(now);
  target.setHours(hour, minute, 0, 0);

  return now >= target;
}

function buildActivitySummary(activities) {
  const counts = new Map();

  for (const activity of activities || []) {
    const name = activity.activity || "";
    counts.set(name, (counts.get(name) || 0) + 1);
  }

  const sortedCounts = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const activeDays = new Set((activities || []).map((activity) => activity.date).filter(Boolean)).size;

  return {
    total: (activities || []).length,
    activeDays,
    topActivity: sortedCounts[0]?.[0] || "暂无",
    counts: sortedCounts,
    recent: [...(activities || [])].slice(-30).reverse(),
  };
}

function normalizeConfig(config = {}) {
  const presets = normalizePresets(config.presets || DEFAULT_PRESETS);
  const rawDailyTime = Object.prototype.hasOwnProperty.call(config, "daily_summary_time")
    ? config.daily_summary_time
    : DEFAULT_DAILY_SUMMARY_TIME;

  return {
    interval_minutes: Number(config.interval_minutes) || DEFAULT_INTERVAL,
    idle_threshold_minutes: Number.isFinite(Number(config.idle_threshold_minutes))
      ? Number(config.idle_threshold_minutes)
      : DEFAULT_IDLE_THRESHOLD,
    presets: presets.length ? presets : [...DEFAULT_PRESETS],
    last_check_time: config.last_check_time || null,
    last_reminder_time: config.last_reminder_time || null,
    daily_summary_time: rawDailyTime === null
      ? null
      : normalizeDailySummaryTime(rawDailyTime) || DEFAULT_DAILY_SUMMARY_TIME,
    last_daily_summary_date: config.last_daily_summary_date || null,
  };
}

module.exports = {
  DEFAULT_INTERVAL,
  DEFAULT_IDLE_THRESHOLD,
  DEFAULT_DAILY_SUMMARY_TIME,
  DEFAULT_PRESETS,
  MAX_ACTIVITY_LENGTH,
  MAX_PRESETS,
  normalizeActivityName,
  normalizePresets,
  parseActivityInput,
  parseIsoDate,
  toLocalIso,
  formatDate,
  formatTime,
  formatMenuDatetime,
  calculateNextReminderTime,
  normalizeDailySummaryTime,
  isDailySummaryDue,
  buildActivitySummary,
  normalizeConfig,
};
