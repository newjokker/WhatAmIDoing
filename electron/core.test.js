const test = require("node:test");
const assert = require("node:assert/strict");

const core = require("./core");

test("parseActivityInput supports numbers and separators", () => {
  assert.deepEqual(
    core.parseActivityInput("1，开会、  自定义任务\n3", ["写代码", "开会", "阅读"]),
    ["写代码", "开会", "自定义任务", "阅读"],
  );
});

test("parseActivityInput trims, limits and deduplicates", () => {
  assert.deepEqual(
    core.parseActivityInput("  很长很长很长很长很长很长很长的活动名称  , 1, 写代码", ["写代码"]),
    ["很长很长很长很长很长很长很长的活动名称".slice(0, core.MAX_ACTIVITY_LENGTH), "写代码"],
  );
});

test("normalizePresets deduplicates and limits", () => {
  const presets = [" 写代码 ", "写代码", "", "开会", ...Array.from({ length: 20 }, (_, index) => `活动${index}`)];
  const normalized = core.normalizePresets(presets);

  assert.equal(normalized.length, core.MAX_PRESETS);
  assert.deepEqual(normalized.slice(0, 2), ["写代码", "开会"]);
});

test("buildActivitySummary returns counts and recent records", () => {
  const summary = core.buildActivitySummary([
    { date: "2026-06-10", time: "09:00", activity: "写代码" },
    { date: "2026-06-10", time: "10:00", activity: "开会" },
    { date: "2026-06-11", time: "11:00", activity: "写代码" },
  ]);

  assert.equal(summary.total, 3);
  assert.equal(summary.activeDays, 2);
  assert.equal(summary.topActivity, "写代码");
  assert.deepEqual(summary.counts, [["写代码", 2], ["开会", 1]]);
  assert.equal(summary.recent[0].time, "11:00");
});

test("daily summary time normalization and due checks", () => {
  assert.equal(core.normalizeDailySummaryTime("7:5"), "07:05");
  assert.equal(core.normalizeDailySummaryTime("17:30"), "17:30");
  assert.equal(core.normalizeDailySummaryTime("24:00"), null);
  assert.equal(core.normalizeDailySummaryTime("关闭"), null);

  const now = new Date("2026-06-11T17:30:00");
  assert.equal(core.isDailySummaryDue(now, "17:30", "2026-06-10"), true);
  assert.equal(core.isDailySummaryDue(now, "17:31", "2026-06-10"), false);
  assert.equal(core.isDailySummaryDue(now, "17:30", "2026-06-11"), false);
  assert.equal(core.isDailySummaryDue(now, null, "2026-06-10"), false);
});
