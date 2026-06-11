import sys
import types
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
