import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


class _FakeApp:
    def __init__(self, *args, **kwargs):
        pass


fake_rumps = types.SimpleNamespace(
    App=_FakeApp,
    Timer=lambda *args, **kwargs: None,
    MenuItem=lambda *args, **kwargs: None,
    alert=lambda **kwargs: True,
    notification=lambda **kwargs: None,
    quit_application=lambda: None,
)
sys.modules.setdefault("rumps", fake_rumps)

import time_recorder


class ActivityParsingTests(unittest.TestCase):
    def test_parse_activity_input_supports_numbers_and_separators(self):
        presets = ["写代码", "开会", "阅读"]

        self.assertEqual(
            time_recorder.parse_activity_input("1，开会、  自定义任务\n3", presets),
            ["写代码", "开会", "自定义任务", "阅读"],
        )

    def test_parse_activity_input_trims_limits_and_deduplicates(self):
        presets = ["写代码"]

        self.assertEqual(
            time_recorder.parse_activity_input(
                "  很长很长很长很长很长很长很长的活动名称  , 1, 写代码",
                presets,
            ),
            ["很长很长很长很长很长很长很长的活动名称"[: time_recorder.MAX_ACTIVITY_LENGTH], "写代码"],
        )


class PresetTests(unittest.TestCase):
    def test_normalize_presets_deduplicates_and_limits_to_12(self):
        presets = [" 写代码 ", "写代码", "", "开会"] + [f"活动{i}" for i in range(20)]

        normalized = time_recorder.normalize_presets(presets)

        self.assertEqual(len(normalized), time_recorder.MAX_PRESETS)
        self.assertEqual(time_recorder.MAX_PRESETS, 12)
        self.assertEqual(normalized[:2], ["写代码", "开会"])

    def test_add_preset_stops_at_maximum(self):
        app = object.__new__(time_recorder.TimeRecorder)
        app.presets = [f"活动{i}" for i in range(time_recorder.MAX_PRESETS)]

        with mock.patch.object(time_recorder, "safe_alert") as alert, \
                mock.patch.object(time_recorder.rumps, "Window", create=True) as window:
            app._on_add_preset(None)

        alert.assert_called_once()
        window.assert_not_called()


class ActivitySummaryTests(unittest.TestCase):
    def test_build_activity_summary(self):
        activities = [
            {"date": "2026-06-10", "time": "09:00", "activity": "写代码"},
            {"date": "2026-06-10", "time": "10:00", "activity": "开会"},
            {"date": "2026-06-11", "time": "11:00", "activity": "写代码"},
        ]

        summary = time_recorder.build_activity_summary(activities)

        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["active_days"], 2)
        self.assertEqual(summary["top_activity"], "写代码")
        self.assertEqual(summary["counts"], [("写代码", 2), ("开会", 1)])
        self.assertEqual(summary["recent"][0]["time"], "11:00")


class ReminderTimeTests(unittest.TestCase):
    def test_calculate_next_reminder_time(self):
        next_time = time_recorder.calculate_next_reminder_time("2026-06-11T09:00:00", 15)

        self.assertEqual(next_time.isoformat(), "2026-06-11T09:15:00")

    def test_calculate_next_reminder_time_handles_invalid_value(self):
        self.assertIsNone(time_recorder.calculate_next_reminder_time("bad-time", 15))

    def test_format_menu_datetime_for_empty_value(self):
        self.assertEqual(time_recorder.format_menu_datetime(None), "暂无")

    def test_save_config_persists_last_reminder_time(self):
        old_dir = time_recorder.CONFIG_DIR
        old_file = time_recorder.CONFIG_FILE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                time_recorder.CONFIG_DIR = tmp
                time_recorder.CONFIG_FILE = str(Path(tmp) / ".time_recorder.json")
                app = object.__new__(time_recorder.TimeRecorder)
                app.interval_minutes = 5
                app.idle_threshold_minutes = 0
                app.presets = ["写代码"]
                app.last_check_time = "2026-06-11T09:00:00"
                app.last_reminder_time = "2026-06-11T08:55:00"
                app.activities = []

                app._save_config()
                data = json.loads(Path(time_recorder.CONFIG_FILE).read_text(encoding="utf-8"))

            self.assertEqual(data["last_reminder_time"], "2026-06-11T08:55:00")
        finally:
            time_recorder.CONFIG_DIR = old_dir
            time_recorder.CONFIG_FILE = old_file


class VersionTests(unittest.TestCase):
    def test_compare_versions(self):
        compare = time_recorder.TimeRecorder._compare_versions

        self.assertGreater(compare("1.4.3", "1.4.2"), 0)
        self.assertEqual(compare("v1.4.2", "1.4.2"), 0)
        self.assertLess(compare("1.4.1", "1.4.2"), 0)

    def test_pyproject_version_matches_app_version(self):
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        version_line = next(
            line for line in pyproject.read_text(encoding="utf-8").splitlines()
            if line.startswith("version = ")
        )

        self.assertEqual(version_line, f'version = "{time_recorder.__version__}"')


class UpdateDownloadTests(unittest.TestCase):
    def test_select_release_asset_prefers_dmg(self):
        assets = [
            {"name": "source.zip", "browser_download_url": "https://example.com/source.zip"},
            {"name": "WhatAmIDoing-v1.4.9.dmg", "browser_download_url": "https://example.com/app.dmg"},
        ]

        selected = time_recorder.select_release_asset(assets)

        self.assertEqual(selected["name"], "WhatAmIDoing-v1.4.9.dmg")

    def test_select_release_asset_ignores_assets_without_download_url(self):
        assets = [
            {"name": "broken.dmg"},
            {"name": "fallback.zip", "browser_download_url": "https://example.com/fallback.zip"},
        ]

        selected = time_recorder.select_release_asset(assets)

        self.assertEqual(selected["name"], "fallback.zip")

    def test_unique_download_path_sanitizes_and_avoids_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "update.dmg"
            existing.write_text("old", encoding="utf-8")

            path = time_recorder.unique_download_path(tmp, "../update.dmg")

        self.assertTrue(path.endswith("update (1).dmg"))


class ExportJsonTests(unittest.TestCase):
    def test_build_export_payload_includes_metadata_and_activities(self):
        activities = [
            {"date": "2026-06-11", "time": "09:00", "activity": "写代码"},
        ]

        payload = time_recorder.build_export_payload(activities, exported_at="2026-06-11T09:30:00")

        self.assertEqual(payload["app"], time_recorder.__app_name__)
        self.assertEqual(payload["version"], time_recorder.__version__)
        self.assertEqual(payload["exported_at"], "2026-06-11T09:30:00")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["activities"], activities)

    def test_export_activities_json_writes_file(self):
        activities = [
            {"date": "2026-06-11", "time": "09:00", "activity": "写代码"},
            {"date": "2026-06-11", "time": "10:00", "activity": "开会"},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            path = time_recorder.export_activities_json(activities, directory=tmp)
            data = json.loads(Path(path).read_text(encoding="utf-8"))

        self.assertTrue(path.endswith(".json"))
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["activities"], activities)


class ErrorLogTests(unittest.TestCase):
    def test_write_error_log_creates_file_with_traceback(self):
        old_dir = time_recorder.ERROR_LOG_DIR
        old_file = time_recorder.ERROR_LOG_FILE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                time_recorder.ERROR_LOG_DIR = tmp
                time_recorder.ERROR_LOG_FILE = str(Path(tmp) / "error.log")

                try:
                    raise RuntimeError("boom")
                except RuntimeError as exc:
                    log_path = time_recorder.log_exception("测试异常", exc)

                content = Path(log_path).read_text(encoding="utf-8")

            self.assertIn("测试异常", content)
            self.assertIn("RuntimeError: boom", content)
            self.assertIn("Traceback:", content)
        finally:
            time_recorder.ERROR_LOG_DIR = old_dir
            time_recorder.ERROR_LOG_FILE = old_file

    def test_open_error_logs_opens_log_directory(self):
        old_dir = time_recorder.ERROR_LOG_DIR
        old_file = time_recorder.ERROR_LOG_FILE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                time_recorder.ERROR_LOG_DIR = tmp
                time_recorder.ERROR_LOG_FILE = str(Path(tmp) / "error.log")
                app = object.__new__(time_recorder.TimeRecorder)

                with mock.patch.object(time_recorder.subprocess, "run") as run:
                    app.open_error_logs(None)

                run.assert_called_once_with(["open", tmp], check=False)
        finally:
            time_recorder.ERROR_LOG_DIR = old_dir
            time_recorder.ERROR_LOG_FILE = old_file

    def test_safe_on_tick_writes_log_when_timer_fails(self):
        old_dir = time_recorder.ERROR_LOG_DIR
        old_file = time_recorder.ERROR_LOG_FILE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                time_recorder.ERROR_LOG_DIR = tmp
                time_recorder.ERROR_LOG_FILE = str(Path(tmp) / "error.log")
                app = object.__new__(time_recorder.TimeRecorder)
                app.on_tick = mock.Mock(side_effect=RuntimeError("tick boom"))

                app._safe_on_tick(None)

                content = Path(time_recorder.ERROR_LOG_FILE).read_text(encoding="utf-8")

            self.assertIn("定时检查失败", content)
            self.assertIn("RuntimeError: tick boom", content)
        finally:
            time_recorder.ERROR_LOG_DIR = old_dir
            time_recorder.ERROR_LOG_FILE = old_file


if __name__ == "__main__":
    unittest.main()
