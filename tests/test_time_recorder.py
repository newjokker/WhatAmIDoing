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


if __name__ == "__main__":
    unittest.main()
