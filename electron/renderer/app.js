const api = window.timeRecorder;
const params = new URLSearchParams(window.location.search);

let snapshot = null;
let currentView = params.get("view") || "all";

const elements = {
  statusLine: document.querySelector("#statusLine"),
  tabs: [...document.querySelectorAll(".tab")],
  views: {
    record: document.querySelector("#recordView"),
    today: document.querySelector("#summaryView"),
    week: document.querySelector("#summaryView"),
    all: document.querySelector("#summaryView"),
    settings: document.querySelector("#settingsView"),
  },
  presetGrid: document.querySelector("#presetGrid"),
  customActivity: document.querySelector("#customActivity"),
  recordError: document.querySelector("#recordError"),
  statTotal: document.querySelector("#statTotal"),
  statDays: document.querySelector("#statDays"),
  statTop: document.querySelector("#statTop"),
  summaryRange: document.querySelector("#summaryRange"),
  activityCounts: document.querySelector("#activityCounts"),
  recentList: document.querySelector("#recentList"),
  recentCount: document.querySelector("#recentCount"),
  intervalInput: document.querySelector("#intervalInput"),
  idleInput: document.querySelector("#idleInput"),
  dailyInput: document.querySelector("#dailyInput"),
  presetList: document.querySelector("#presetList"),
  presetLimit: document.querySelector("#presetLimit"),
  newPreset: document.querySelector("#newPreset"),
};

function todayKey(date = new Date()) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function startOfWeek(date = new Date()) {
  const copy = new Date(date);
  const day = copy.getDay() || 7;
  copy.setDate(copy.getDate() - day + 1);
  copy.setHours(0, 0, 0, 0);
  return todayKey(copy);
}

function buildSummary(activities) {
  const counts = new Map();
  for (const activity of activities) {
    counts.set(activity.activity, (counts.get(activity.activity) || 0) + 1);
  }
  const sortedCounts = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  return {
    total: activities.length,
    activeDays: new Set(activities.map((activity) => activity.date)).size,
    topActivity: sortedCounts[0]?.[0] || "暂无",
    counts: sortedCounts,
    recent: [...activities].slice(-30).reverse(),
  };
}

function filterActivities(view) {
  if (!snapshot) {
    return [];
  }
  if (view === "today") {
    const today = todayKey();
    return snapshot.activities.filter((activity) => activity.date === today);
  }
  if (view === "week") {
    const weekStart = startOfWeek();
    return snapshot.activities.filter((activity) => activity.date >= weekStart);
  }
  return snapshot.activities;
}

function setView(view) {
  currentView = view;
  for (const tab of elements.tabs) {
    tab.classList.toggle("active", tab.dataset.view === view);
  }
  const uniqueViews = new Set(Object.values(elements.views));
  for (const panel of uniqueViews) {
    panel.hidden = true;
  }
  elements.views[view].hidden = false;
  render();
}

function renderStatus() {
  const config = snapshot.config;
  const last = snapshot.activities.at(-1);
  const nextText = snapshot.nextReminderTime ? snapshot.nextReminderTime.replace("T", " ") : "暂无";
  elements.statusLine.textContent = `每 ${config.interval_minutes} 分钟提醒 · 下次 ${nextText}${last ? ` · 上次 ${last.activity}` : ""}`;
}

function renderRecord() {
  elements.presetGrid.innerHTML = "";
  for (const preset of snapshot.config.presets) {
    const label = document.createElement("label");
    label.className = "preset-option";
    label.innerHTML = `<input type="checkbox" value="${preset}"><span>${preset}</span>`;
    elements.presetGrid.append(label);
  }
}

function renderSummary() {
  const rangeLabel = {
    today: "今日记录",
    week: "本周记录",
    all: "全部记录",
  }[currentView] || "全部记录";
  const summary = buildSummary(filterActivities(currentView));
  const max = Math.max(1, ...summary.counts.map((item) => item[1]));

  elements.summaryRange.textContent = rangeLabel;
  elements.statTotal.textContent = summary.total;
  elements.statDays.textContent = summary.activeDays;
  elements.statTop.textContent = summary.topActivity;
  elements.recentCount.textContent = `${summary.recent.length} 条`;

  elements.activityCounts.innerHTML = summary.counts.length
    ? ""
    : '<p class="empty">暂无记录</p>';
  for (const [name, count] of summary.counts) {
    const row = document.createElement("div");
    row.className = "count-row";
    row.innerHTML = `
      <div><strong>${name}</strong><span>${count} 次</span></div>
      <meter min="0" max="${max}" value="${count}"></meter>
    `;
    elements.activityCounts.append(row);
  }

  elements.recentList.innerHTML = summary.recent.length
    ? ""
    : '<p class="empty">暂无记录</p>';
  for (const item of summary.recent) {
    const row = document.createElement("div");
    row.className = "recent-row";
    row.innerHTML = `<strong>${item.activity}</strong><span>${item.date} ${item.time}</span>`;
    elements.recentList.append(row);
  }
}

function renderSettings() {
  const config = snapshot.config;
  elements.intervalInput.value = config.interval_minutes;
  elements.idleInput.value = config.idle_threshold_minutes;
  elements.dailyInput.value = config.daily_summary_time || "关闭";
  elements.presetLimit.textContent = `${config.presets.length}/12`;

  elements.presetList.innerHTML = "";
  config.presets.forEach((preset, index) => {
    const row = document.createElement("div");
    row.className = "preset-row";
    row.innerHTML = `<span>${preset}</span><button type="button" data-index="${index}">删除</button>`;
    elements.presetList.append(row);
  });
}

function render() {
  if (!snapshot) {
    return;
  }
  renderStatus();
  renderRecord();
  renderSummary();
  renderSettings();
}

document.querySelector("#submitRecord").addEventListener("click", async () => {
  const selected = [...document.querySelectorAll("#presetGrid input:checked")].map((input) => input.value);
  const result = await api.submitRecord({
    selected,
    custom: elements.customActivity.value,
  });
  elements.recordError.textContent = result.ok ? "" : result.message;
});

document.querySelector("#skipRecord").addEventListener("click", () => api.skipRecord());
document.querySelector("#saveSettings").addEventListener("click", async () => {
  snapshot = await api.updateSettings({
    interval_minutes: Number(elements.intervalInput.value),
    idle_threshold_minutes: Number(elements.idleInput.value),
    daily_summary_time: elements.dailyInput.value.trim() === "关闭" ? null : elements.dailyInput.value.trim(),
  });
  render();
});
document.querySelector("#addPreset").addEventListener("click", async () => {
  snapshot = await api.addPreset(elements.newPreset.value);
  elements.newPreset.value = "";
  render();
});
document.querySelector("#presetList").addEventListener("click", async (event) => {
  if (event.target.matches("button[data-index]")) {
    snapshot = await api.deletePreset(Number(event.target.dataset.index));
    render();
  }
});
document.querySelector("#resetPresets").addEventListener("click", async () => {
  snapshot = await api.resetPresets();
  render();
});
document.querySelector("#clearActivities").addEventListener("click", async () => {
  snapshot = await api.clearActivities();
  render();
});
document.querySelector("#exportJson").addEventListener("click", async () => {
  elements.statusLine.textContent = `已导出到 ${await api.exportJson()}`;
});
document.querySelector("#exportCsv").addEventListener("click", async () => {
  elements.statusLine.textContent = `已导出到 ${await api.exportCsv()}`;
});
document.querySelector("#openLogs").addEventListener("click", () => api.openLogs());

for (const tab of elements.tabs) {
  tab.addEventListener("click", () => setView(tab.dataset.view));
}

api.onStateChanged((nextSnapshot) => {
  snapshot = nextSnapshot;
  render();
});
api.onViewSet((view) => setView(view));

api.getState().then((nextSnapshot) => {
  snapshot = nextSnapshot;
  setView(currentView);
});
