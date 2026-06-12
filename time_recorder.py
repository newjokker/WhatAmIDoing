#!/usr/bin/env python3
"""
⏰ 干啥来着 - macOS 菜单栏活动记录器
基于 rumps 实现

功能:
    - 每 N 分钟（默认 5 分钟）弹窗询问"当前在做什么"
    - 检测电脑是否在使用中（空闲超过阈值则跳过，可关闭）
    - 简化弹窗：勾选复选框 + 输入自定义，点记录统一提交
    - 今日 / 本周 / 全部活动汇总
    - 自定义预设活动列表
    - 设置持久化（重启后保留）
"""

__app_name__ = "⏰ 干啥来着"
__bundle_id__ = "com.timerecorder.app"
__repo_url__ = "https://github.com/newjokker/WhatAmIDoing"
__github_api__ = "https://api.github.com/repos/newjokker/WhatAmIDoing/releases/latest"

import rumps
import csv
import json
import os
import sys
import datetime
import tempfile
import subprocess
import re
import traceback
import urllib.request
import urllib.error
import plistlib

from app_version import __version__

try:
    import threading
except Exception:
    threading = None

# ═══════════════════════════════════════
#  ObjC 面板回调处理类（模块级，只定义一次）
# ═══════════════════════════════════════
try:
    import AppKit
    import objc

    class _SimplePanelHandler(AppKit.NSObject):
        """简化面板回调：只负责结束模态，不读取控件内容"""

        def recordClicked_(self, sender):
            """点记录 → 直接结束模态，返回 code=1"""
            AppKit.NSApplication.sharedApplication().stopModalWithCode_(1)

        def skipClicked_(self, sender):
            """点击跳过 → 直接结束模态，返回 code=0"""
            AppKit.NSApplication.sharedApplication().stopModalWithCode_(0)

        def closeClicked_(self, sender):
            """关闭统计窗口"""
            AppKit.NSApplication.sharedApplication().stopModalWithCode_(0)

        def windowWillClose_(self, notification):
            """用户点窗口关闭按钮时也要结束模态，否则菜单栏会像卡死一样不可点。"""
            AppKit.NSApplication.sharedApplication().stopModalWithCode_(0)

    _PANEL_HANDLER_CLS = _SimplePanelHandler
except Exception:
    _PANEL_HANDLER_CLS = None

# ═══════════════════════════════════════
#  默认配置
# ═══════════════════════════════════════
DEFAULT_INTERVAL = 5           # 弹窗间隔（分钟，默认 5min 方便测试）
DEFAULT_IDLE_THRESHOLD = 5     # 空闲阈值（分钟），超过此值视为电脑无人使用
DEFAULT_DAILY_SUMMARY_TIME = "17:30"
DEFAULT_PRESETS = ["写代码", "开会", "阅读", "学习", "思考", "摸鱼"]
MAX_ACTIVITY_LENGTH = 20
MAX_PRESETS = 12

CONFIG_DIR = os.path.expanduser("~")
LEGACY_CONFIG_FILE = os.path.join(CONFIG_DIR, ".time_recorder.json")
CONFIG_FILE = os.path.join(CONFIG_DIR, ".time_recorder_config.json")
ACTIVITIES_FILE = os.path.join(CONFIG_DIR, ".time_recorder_activities.jsonl")
ERROR_LOG_DIR = os.path.expanduser("~/Library/Logs/TimeRecorder")
ERROR_LOG_FILE = os.path.join(ERROR_LOG_DIR, "error.log")
DOWNLOAD_DIR = os.path.expanduser("~/Downloads")
LAUNCH_AGENT_LABEL = __bundle_id__
LAUNCH_AGENT_DIR = os.path.expanduser("~/Library/LaunchAgents")
LAUNCH_AGENT_FILE = os.path.join(LAUNCH_AGENT_DIR, f"{LAUNCH_AGENT_LABEL}.plist")


def ensure_error_log_dir(log_dir=None):
    """确保错误日志目录存在，并返回目录路径。"""
    if log_dir is None:
        log_dir = ERROR_LOG_DIR
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def get_error_log_path():
    """返回错误日志文件路径，调用时会先创建日志目录。"""
    ensure_error_log_dir()
    return ERROR_LOG_FILE


def get_running_app_path():
    """返回当前打包 .app 路径；开发模式下返回 None。"""
    marker = ".app/Contents/"
    executable = os.path.abspath(sys.argv[0])
    if marker not in executable:
        return None
    return executable.split(marker, 1)[0] + ".app"


def build_launch_agent_plist(app_path):
    """生成用户 LaunchAgent 配置。"""
    return {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": ["/usr/bin/open", "-gj", app_path],
        "RunAtLoad": True,
        "KeepAlive": False,
    }


def install_launch_agent(app_path=None, plist_path=LAUNCH_AGENT_FILE):
    """安装开机自启 LaunchAgent。"""
    if app_path is None:
        app_path = get_running_app_path()
    if not app_path:
        raise RuntimeError("当前不是打包后的 .app，无法设置开机自启")
    os.makedirs(os.path.dirname(plist_path), exist_ok=True)
    with open(plist_path, "wb") as f:
        plistlib.dump(build_launch_agent_plist(app_path), f)
    return plist_path


def uninstall_launch_agent(plist_path=LAUNCH_AGENT_FILE):
    """移除开机自启 LaunchAgent。"""
    if os.path.exists(plist_path):
        os.remove(plist_path)


def is_launch_agent_enabled(plist_path=LAUNCH_AGENT_FILE):
    """检查是否已启用开机自启。"""
    return os.path.exists(plist_path)


def split_config_and_activities(data):
    """把旧格式数据拆成配置和活动记录。"""
    data = dict(data or {})
    activities = data.pop("activities", [])
    return data, activities if isinstance(activities, list) else []


def atomic_write_json(path, data):
    """原子写入 JSON 文件。"""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".json", dir=directory, delete=False,
    )
    try:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        tmp.close()
    os.replace(tmp.name, path)


def write_activities_file(activities, path=ACTIVITIES_FILE):
    """以 JSON Lines 格式重写活动历史文件。"""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".jsonl", dir=directory, delete=False,
    )
    try:
        for activity in activities or []:
            tmp.write(json.dumps(activity, ensure_ascii=False) + "\n")
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        tmp.close()
    os.replace(tmp.name, path)


def append_activity_file(activity, path=ACTIVITIES_FILE):
    """追加一条活动记录到 JSON Lines 文件。"""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(activity, ensure_ascii=False) + "\n")


def load_activities_file(path=ACTIVITIES_FILE):
    """读取 JSON Lines 活动历史；兼容 JSON 数组文件。"""
    if not os.path.exists(path):
        return []
    activities = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            first = f.read(1)
            f.seek(0)
            if first == "[":
                data = json.load(f)
                return data if isinstance(data, list) else []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                if isinstance(item, dict):
                    activities.append(item)
        return activities
    except (json.JSONDecodeError, OSError) as e:
        log_exception("加载活动历史失败", e)
        return []


def migrate_legacy_storage(
    legacy_path=LEGACY_CONFIG_FILE,
    config_path=CONFIG_FILE,
    activities_path=ACTIVITIES_FILE,
):
    """从旧的单文件存储迁移到配置/历史分离存储。"""
    if os.path.exists(config_path) or not os.path.exists(legacy_path):
        return None
    with open(legacy_path, "r", encoding="utf-8") as f:
        legacy_data = json.load(f)
    config, activities = split_config_and_activities(legacy_data)
    atomic_write_json(config_path, config)
    if activities and not os.path.exists(activities_path):
        write_activities_file(activities, activities_path)
    return config


def write_error_log(context, exc_info=None, message=None):
    """把异常详情追加写入固定日志文件，便于后续排查。"""
    try:
        log_path = get_error_log_path()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "=" * 80,
            f"[{now}] {context}",
            f"Version: {__version__}",
        ]
        if message:
            lines.append(str(message))
        if exc_info:
            lines.append("Traceback:")
            lines.extend(traceback.format_exception(*exc_info))
        lines.append("")

        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return log_path
    except Exception as log_error:
        sys.stderr.write(f"[TimeRecorder] 写入错误日志失败: {log_error}\n")
        return None


def log_exception(context, exc):
    """记录已捕获异常。"""
    return write_error_log(context, (type(exc), exc, exc.__traceback__))


def install_exception_logging():
    """安装全局异常记录，捕获未处理的主线程和后台线程异常。"""
    original_excepthook = sys.excepthook

    def _excepthook(exc_type, exc, tb):
        if exc_type is KeyboardInterrupt:
            original_excepthook(exc_type, exc, tb)
            return
        write_error_log("未处理异常", (exc_type, exc, tb))
        original_excepthook(exc_type, exc, tb)

    sys.excepthook = _excepthook

    if threading is not None and hasattr(threading, "excepthook"):
        original_threading_excepthook = threading.excepthook

        def _threading_excepthook(args):
            write_error_log(
                f"线程未处理异常: {getattr(args.thread, 'name', 'unknown')}",
                (args.exc_type, args.exc_value, args.exc_traceback),
            )
            original_threading_excepthook(args)

        threading.excepthook = _threading_excepthook


def normalize_activity_name(text):
    """清洗单条活动名称，返回最多 MAX_ACTIVITY_LENGTH 个字符。"""
    return re.sub(r"\s+", " ", str(text or "").strip())[:MAX_ACTIVITY_LENGTH]


def normalize_presets(presets, limit=MAX_PRESETS):
    """清洗预设列表：去空、去重、限制数量。"""
    cleaned = []
    seen = set()
    for preset in presets or []:
        name = normalize_activity_name(preset)
        if name and name not in seen:
            cleaned.append(name)
            seen.add(name)
        if len(cleaned) >= limit:
            break
    return cleaned


def parse_activity_input(text, presets):
    """解析逗号/换行/顿号分隔的活动输入，支持预设编号并自动去重。"""
    activities = []
    seen = set()
    parts = re.split(r"[,，、\n]+", text or "")
    for part in parts:
        raw = part.strip()
        if not raw:
            continue

        activity = raw
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(presets):
                activity = presets[idx]

        activity = normalize_activity_name(activity)
        if activity and activity not in seen:
            activities.append(activity)
            seen.add(activity)
    return activities


def parse_iso_datetime(value):
    """安全解析 ISO 时间字符串。"""
    try:
        return datetime.datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def format_menu_datetime(value):
    """格式化菜单里展示的提醒时间。"""
    dt = parse_iso_datetime(value)
    if dt is None:
        return "暂无"
    today = datetime.date.today()
    if dt.date() == today:
        return dt.strftime("今天 %H:%M")
    if dt.date() == today + datetime.timedelta(days=1):
        return dt.strftime("明天 %H:%M")
    return dt.strftime("%m-%d %H:%M")


def calculate_next_reminder_time(last_check_time, interval_minutes):
    """根据上次计时基准计算下次提醒时间。"""
    last_check = parse_iso_datetime(last_check_time)
    if last_check is None:
        return None
    return last_check + datetime.timedelta(minutes=interval_minutes)


def normalize_daily_summary_time(value):
    """清洗每日汇总时间，返回 HH:MM 或 None（关闭）。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"off", "none", "false", "关闭"}:
        return None
    match = re.fullmatch(r"(\d{1,2}):(\d{1,2})", text)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def is_daily_summary_due(now, daily_summary_time, last_daily_summary_date):
    """判断当前是否应该弹出每日汇总。"""
    summary_time = normalize_daily_summary_time(daily_summary_time)
    if summary_time is None:
        return False
    today = now.date().isoformat()
    if last_daily_summary_date == today:
        return False
    hour, minute = [int(part) for part in summary_time.split(":")]
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return now >= target


def build_activity_summary(activities):
    """生成统计页使用的聚合数据。"""
    counts = {}
    for activity in activities:
        name = activity.get("activity", "")
        counts[name] = counts.get(name, 0) + 1

    total = len(activities)
    sorted_counts = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    top_activity = sorted_counts[0][0] if sorted_counts else "暂无"
    active_days = len({activity.get("date") for activity in activities if activity.get("date")})
    recent = list(reversed(activities[-30:]))

    return {
        "total": total,
        "active_days": active_days,
        "top_activity": top_activity,
        "counts": sorted_counts,
        "recent": recent,
    }


def select_release_asset(assets):
    """从 GitHub Release assets 中优先选择 DMG 安装包。"""
    candidates = [
        asset for asset in assets or []
        if asset.get("browser_download_url") and asset.get("name")
    ]
    dmg_assets = [
        asset for asset in candidates
        if asset.get("name", "").lower().endswith(".dmg")
    ]
    return (dmg_assets or candidates or [None])[0]


def safe_download_filename(filename):
    """清理下载文件名，避免路径穿越和 macOS 文件名问题。"""
    name = os.path.basename(str(filename or "").strip())
    name = re.sub(r'[/:\\\0]+', "-", name)
    return name or "TimeRecorder-update.dmg"


def unique_download_path(directory, filename):
    """生成不会覆盖已有文件的下载路径。"""
    safe_name = safe_download_filename(filename)
    base, ext = os.path.splitext(safe_name)
    path = os.path.join(directory, safe_name)
    i = 1
    while os.path.exists(path):
        path = os.path.join(directory, f"{base} ({i}){ext}")
        i += 1
    return path


def build_export_payload(activities, exported_at=None):
    """构建导出 JSON 内容。"""
    if exported_at is None:
        exported_at = datetime.datetime.now().isoformat()
    return {
        "app": __app_name__,
        "version": __version__,
        "exported_at": exported_at,
        "total": len(activities or []),
        "activities": list(activities or []),
    }


def export_activities_json(activities, directory=DOWNLOAD_DIR):
    """导出活动记录为 JSON 文件，并返回保存路径。"""
    os.makedirs(directory, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"TimeRecorder-activities-{timestamp}.json"
    dest_path = unique_download_path(directory, filename)
    tmp_path = f"{dest_path}.tmp"
    payload = build_export_payload(activities)
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, dest_path)
        return dest_path
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def export_activities_csv(activities, directory=DOWNLOAD_DIR):
    """导出活动记录为 CSV 文件，并返回保存路径。"""
    os.makedirs(directory, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"TimeRecorder-activities-{timestamp}.csv"
    dest_path = unique_download_path(directory, filename)
    tmp_path = f"{dest_path}.tmp"
    fieldnames = ["timestamp", "date", "time", "activity"]
    try:
        with open(tmp_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for activity in activities or []:
                writer.writerow(activity)
        os.replace(tmp_path, dest_path)
        return dest_path
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def download_release_asset(url, dest_path):
    """把 Release asset 下载到本地，成功后返回保存路径。"""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp_path = f"{dest_path}.download"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"TimeRecorder/{__version__}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
        os.replace(tmp_path, dest_path)
        return dest_path
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def safe_alert(**kwargs):
    """显示提示框；在非打包/无通知权限环境下避免异常影响主流程。"""
    try:
        return rumps.alert(**kwargs)
    except Exception as e:
        log_exception("显示提示框失败", e)
        return None


def safe_notification(**kwargs):
    """发送系统通知；失败时静默跳过，记录数据不能因此丢失。"""
    try:
        rumps.notification(**kwargs)
    except Exception as e:
        log_exception("发送系统通知失败", e)
        pass


def get_idle_time():
    """获取系统空闲时间（秒），使用 ioreg 查询 IOHIDSystem 的 HIDIdleTime"""
    try:
        result = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem", "-r", "-d", "1"],
            capture_output=True, text=True, timeout=3,
        )
        for line in result.stdout.split("\n"):
            if "HIDIdleTime" in line:
                # 格式可能是 0xHEX 或纯十进制数
                m = re.search(r'"HIDIdleTime"\s*=\s*(0x[0-9a-fA-F]+|\d+)', line)
                if m:
                    raw = m.group(1)
                    if raw.startswith("0x") or raw.startswith("0X"):
                        idle_ns = int(raw, 16)
                    else:
                        idle_ns = int(raw)
                    return idle_ns / 1_000_000_000  # 纳秒 → 秒
    except Exception as e:
        log_exception("获取系统空闲时间失败", e)
        pass
    return 0


class TimeRecorder(rumps.App):
    """菜单栏干啥来着"""

    def __init__(self):
        super().__init__("📝 待命", quit_button=None)

        # ── 从文件加载配置 ──
        config = self._load_config()

        # ── 状态 ──
        self.timer = rumps.Timer(self._safe_on_tick, 1)
        self.interval_minutes = config.get("interval_minutes", DEFAULT_INTERVAL)
        self.idle_threshold_minutes = config.get("idle_threshold_minutes", DEFAULT_IDLE_THRESHOLD)
        self.presets = normalize_presets(config.get("presets", DEFAULT_PRESETS))
        if not self.presets:
            self.presets = list(DEFAULT_PRESETS)
        self.last_check_time = config.get("last_check_time", None)
        self.last_reminder_time = config.get("last_reminder_time", None)
        if "daily_summary_time" in config and config.get("daily_summary_time") is None:
            self.daily_summary_time = None
        else:
            raw_daily_time = config.get("daily_summary_time", DEFAULT_DAILY_SUMMARY_TIME)
            self.daily_summary_time = normalize_daily_summary_time(raw_daily_time) or DEFAULT_DAILY_SUMMARY_TIME
        self.last_daily_summary_date = config.get("last_daily_summary_date", None)
        self.activities = self._load_activities()
        self.recording_lock = False  # 防止重复弹窗

        # ── 更新菜单栏标题 ──
        self.title = f"📝 {self.interval_minutes}min"

        # ── 构建菜单 ──
        self._build_menu()

        # ── 启动定时器 ──
        self.timer.start()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  配置持久化
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _load_config(self):
        """从 JSON 文件加载配置"""
        try:
            migrated = migrate_legacy_storage()
            if migrated is not None:
                return migrated
        except (json.JSONDecodeError, OSError) as e:
            log_exception("迁移旧配置失败", e)

        if not os.path.exists(CONFIG_FILE):
            return {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log_exception("加载配置失败", e)
            return {}

    def _load_activities(self):
        """从独立历史文件加载活动记录。"""
        return load_activities_file()

    def _save_config(self):
        """原子写入配置"""
        self.presets = normalize_presets(self.presets)
        if not self.presets:
            self.presets = list(DEFAULT_PRESETS)
        config = {
            "interval_minutes": self.interval_minutes,
            "idle_threshold_minutes": self.idle_threshold_minutes,
            "presets": self.presets,
            "last_check_time": self.last_check_time,
            "last_reminder_time": self.last_reminder_time,
            "daily_summary_time": self.daily_summary_time,
            "last_daily_summary_date": self.last_daily_summary_date,
        }
        try:
            atomic_write_json(CONFIG_FILE, config)
        except OSError as e:
            log_exception("保存配置失败", e)
            pass

    def _save_activities(self):
        """重写活动历史文件，用于清空/修复等批量操作。"""
        try:
            write_activities_file(self.activities)
        except OSError as e:
            log_exception("保存活动历史失败", e)
            pass

    def _append_activity(self, activity):
        """追加活动历史，避免记录增长后反复重写大文件。"""
        try:
            append_activity_file(activity)
        except OSError as e:
            log_exception("追加活动历史失败", e)
            pass

    def _menu_callback(self, label, callback):
        """包一层菜单回调，避免 rumps 静默吞掉异常。"""
        def _wrapped(sender):
            try:
                return callback(sender)
            except Exception as e:
                log_exception(f"菜单操作失败: {label}", e)
                safe_alert(
                    title="操作失败",
                    message=f"「{label}」执行失败，详情已写入错误日志。",
                )
                return None
        return _wrapped

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  菜单构建
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _build_menu(self):
        """组装菜单结构"""
        # ── 立即记录 ──
        self.check_now_item = rumps.MenuItem("🔍 立即记录", callback=self._menu_callback("立即记录", self.trigger_record))

        # ── 上次活动 ──
        self.last_activity_item = rumps.MenuItem("⏳ 暂无记录", callback=None)
        self.last_reminder_item = rumps.MenuItem("🔔 上次提醒: 暂无", callback=None)
        self.next_reminder_item = rumps.MenuItem("⏭ 下次提醒: 暂无", callback=None)

        # ── 汇总菜单 ──
        self.today_item = rumps.MenuItem("📅 今日汇总", callback=self._menu_callback("今日汇总", self.show_today_summary))
        self.week_item = rumps.MenuItem("📆 本周汇总", callback=self._menu_callback("本周汇总", self.show_week_summary))
        self.all_item = rumps.MenuItem("📊 全部记录", callback=self._menu_callback("全部记录", self.show_all_summary))
        self.export_json_item = rumps.MenuItem("📤 导出 JSON", callback=self._menu_callback("导出 JSON", self.export_json))
        self.export_csv_item = rumps.MenuItem("📄 导出 CSV", callback=self._menu_callback("导出 CSV", self.export_csv))

        # ── 设置子菜单 ──
        self.settings_menu = rumps.MenuItem("⚙ 设置")

        # 记录间隔（含 1min / 2min 方便测试）
        self.interval_submenu = rumps.MenuItem("⏱ 记录间隔")
        self._setup_duration_menu(self.interval_submenu, self.interval_minutes,
                                  [1, 2, 5, 15, 30, 45, 60, 90, 120], self._on_set_interval)
        self.settings_menu.add(self.interval_submenu)

        # 空闲阈值（含 0 = 关闭空闲检测，始终弹窗）
        self.idle_submenu = rumps.MenuItem("💤 空闲阈值")
        self._setup_duration_menu(self.idle_submenu, self.idle_threshold_minutes,
                                  [0, 1, 3, 5, 10, 15, 30], self._on_set_idle_threshold)
        self.settings_menu.add(self.idle_submenu)

        # 每日汇总提醒
        self.daily_summary_submenu = rumps.MenuItem("📅 每日汇总提醒")
        self._rebuild_daily_summary_menu()
        self.settings_menu.add(self.daily_summary_submenu)

        self.launch_at_login_item = rumps.MenuItem("🚀 开机自启", callback=self._menu_callback("开机自启", self._toggle_launch_at_login))
        self._update_launch_at_login_item()
        self.settings_menu.add(self.launch_at_login_item)

        # 预设选项管理
        self.presets_submenu = rumps.MenuItem("📋 预设选项")
        self._rebuild_presets_menu()
        self.settings_menu.add(self.presets_submenu)

        # 错误日志
        self.logs_item = rumps.MenuItem("🧾 打开错误日志文件夹", callback=self._menu_callback("打开错误日志文件夹", self.open_error_logs))

        # ── 检查更新 ──
        self.update_item = rumps.MenuItem("🔄 检查更新", callback=self._menu_callback("检查更新", self.check_update))

        # ── 测试工具（开发用） ──
        self.test_menu = rumps.MenuItem("🧪 测试")
        reset_timer = rumps.MenuItem("⏱ 重置计时器（下次立即弹窗）", callback=self._menu_callback("重置计时器", self._reset_timer))
        clear_acts = rumps.MenuItem("🗑 清空全部记录", callback=self._menu_callback("清空全部记录", self._clear_all_activities))
        self.test_menu.add(reset_timer)
        self.test_menu.add(clear_acts)

        # ── 组装主菜单 ──
        self.menu = [
            self.check_now_item,
            None,
            self.last_activity_item,
            self.last_reminder_item,
            self.next_reminder_item,
            None,
            self.today_item,
            self.week_item,
            self.all_item,
            self.export_json_item,
            self.export_csv_item,
            None,
            self.settings_menu,
            self.test_menu,
            self.logs_item,
            self.update_item,
            None,
            rumps.MenuItem("❓ 关于", callback=self._menu_callback("关于", self.show_about)),
            None,
            rumps.MenuItem("🚪 退出", callback=self._menu_callback("退出", self.quit_app)),
        ]

        self._update_last_activity()
        self._update_reminder_items()

    def _setup_duration_menu(self, parent, current_value, values, callback):
        """为子菜单添加时长选项列表"""
        for v in values:
            label = "关闭（始终弹窗）" if v == 0 else f"{v} 分钟"
            item = rumps.MenuItem(label, callback=self._menu_callback(label, callback))
            item.state = (v == current_value)
            item._setting_value = v
            parent.add(item)

    def _on_set_interval(self, sender):
        """设置记录间隔"""
        for item in self.interval_submenu.values():
            if isinstance(item, rumps.MenuItem):
                item.state = False
        sender.state = True
        self.interval_minutes = sender._setting_value
        self.title = f"📝 {self.interval_minutes}min"
        self._save_config()
        self._update_reminder_items()

    def _on_set_idle_threshold(self, sender):
        """设置空闲阈值"""
        for item in self.idle_submenu.values():
            if isinstance(item, rumps.MenuItem):
                item.state = False
        sender.state = True
        self.idle_threshold_minutes = sender._setting_value
        self._save_config()

    # ── 每日汇总提醒 ──

    def _rebuild_daily_summary_menu(self):
        """重建每日汇总提醒设置菜单。"""
        for key in list(self.daily_summary_submenu.keys()):
            del self.daily_summary_submenu[key]

        current = self.daily_summary_time or "已关闭"
        status = rumps.MenuItem(f"当前: {current}", callback=None)
        self.daily_summary_submenu.add(status)
        self.daily_summary_submenu.add(rumps.MenuItem(None))

        for value in ["17:30", "18:00", "19:00", "21:00"]:
            item = rumps.MenuItem(value, callback=self._menu_callback(f"每日汇总 {value}", self._on_set_daily_summary_time))
            item.state = (self.daily_summary_time == value)
            item._setting_value = value
            self.daily_summary_submenu.add(item)

        custom = rumps.MenuItem("自定义时间…", callback=self._menu_callback("自定义每日汇总时间", self._on_custom_daily_summary_time))
        self.daily_summary_submenu.add(custom)

        close_item = rumps.MenuItem("关闭每日汇总", callback=self._menu_callback("关闭每日汇总", self._on_disable_daily_summary))
        close_item.state = (self.daily_summary_time is None)
        self.daily_summary_submenu.add(close_item)

    def _on_set_daily_summary_time(self, sender):
        """设置每日汇总提醒时间。"""
        self.daily_summary_time = normalize_daily_summary_time(sender._setting_value)
        self.last_daily_summary_date = None
        self._save_config()
        self._rebuild_daily_summary_menu()

    def _on_custom_daily_summary_time(self, _):
        """输入自定义每日汇总时间。"""
        win = rumps.Window(
            title="每日汇总提醒",
            message="请输入提醒时间（24 小时制 HH:MM）：",
            default_text=self.daily_summary_time or DEFAULT_DAILY_SUMMARY_TIME,
            cancel=True,
        )
        response = win.run()
        if response.clicked:
            summary_time = normalize_daily_summary_time(response.text)
            if summary_time is None:
                safe_alert(title="每日汇总提醒", message="时间格式不正确，请输入例如 17:30")
                return
            self.daily_summary_time = summary_time
            self.last_daily_summary_date = None
            self._save_config()
            self._rebuild_daily_summary_menu()

    def _on_disable_daily_summary(self, _):
        """关闭每日汇总提醒。"""
        self.daily_summary_time = None
        self.last_daily_summary_date = None
        self._save_config()
        self._rebuild_daily_summary_menu()

    # ── 开机自启 ──

    def _update_launch_at_login_item(self):
        """刷新开机自启菜单状态。"""
        if hasattr(self, "launch_at_login_item"):
            self.launch_at_login_item.state = is_launch_agent_enabled()

    def _toggle_launch_at_login(self, _):
        """切换开机自启。"""
        try:
            if is_launch_agent_enabled():
                uninstall_launch_agent()
                safe_alert(title="开机自启", message="已关闭开机自启")
            else:
                install_launch_agent()
                safe_alert(title="开机自启", message="已开启开机自启")
        except Exception as e:
            log_exception("切换开机自启失败", e)
            safe_alert(
                title="开机自启",
                message=(
                    f"设置失败：{e}\n\n"
                    "请先把应用安装到 Applications 后，再从菜单中开启。"
                ),
            )
        finally:
            self._update_launch_at_login_item()

    # ── 预设选项管理 ──

    def _rebuild_presets_menu(self):
        """重建预设选项子菜单"""
        # 清除旧项
        for key in list(self.presets_submenu.keys()):
            del self.presets_submenu[key]

        # 添加预设选项
        for i, preset in enumerate(self.presets):
            item = rumps.MenuItem(
                f"删除「{preset}」",
                callback=self._menu_callback(f"删除预设 {preset}", self._on_delete_preset),
            )
            item._preset_index = i
            self.presets_submenu.add(item)

        if self.presets:
            self.presets_submenu.add(rumps.MenuItem(None))

        # 管理按钮
        add_item = rumps.MenuItem(
            f"✚ 添加预设（{len(self.presets)}/{MAX_PRESETS}）",
            callback=self._menu_callback("添加预设", self._on_add_preset),
        )
        self.presets_submenu.add(add_item)
        reset_item = rumps.MenuItem("↺ 恢复默认", callback=self._menu_callback("恢复默认预设", self._on_reset_presets))
        self.presets_submenu.add(reset_item)

    def _on_delete_preset(self, sender):
        """删除预设（点击预设项即删除）"""
        idx = sender._preset_index
        if not 0 <= idx < len(self.presets):
            write_error_log("删除预设失败", message=f"预设索引失效: {idx}, 当前数量: {len(self.presets)}")
            self._rebuild_presets_menu()
            return
        name = self.presets[idx]
        result = safe_alert(
            title="确认删除",
            message=f"确定删除预设「{name}」？",
            ok="删除",
            cancel="取消",
        )
        if result:
            del self.presets[idx]
            self._rebuild_presets_menu()
            self._save_config()

    def _on_add_preset(self, _):
        """添加新预设"""
        if len(self.presets) >= MAX_PRESETS:
            safe_alert(title="提示", message=f"最多支持 {MAX_PRESETS} 个预设选项")
            return

        win = rumps.Window(
            title="添加预设",
            message="请输入新的预设活动名称：",
            default_text="",
            cancel=True,
        )
        response = win.run()
        if response.clicked:
            name = normalize_activity_name(response.text)
            if not name:
                safe_alert(title="提示", message="名称不能为空")
                return
            if name in self.presets:
                safe_alert(title="提示", message=f"「{name}」已存在")
                return
            self.presets = normalize_presets([*self.presets, name])
            self._rebuild_presets_menu()
            self._save_config()

    def _on_reset_presets(self, _):
        """恢复默认预设"""
        result = safe_alert(
            title="确认恢复默认",
            message="将恢复默认预设选项列表，确认？",
            ok="确认",
            cancel="取消",
        )
        if result:
            self.presets = list(DEFAULT_PRESETS)
            self._rebuild_presets_menu()
            self._save_config()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  核心逻辑：定时检查 & 弹窗记录
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _safe_on_tick(self, sender):
        """定时器入口：记录异常，避免定时器故障后悄悄失效。"""
        try:
            self.on_tick(sender)
        except Exception as e:
            log_exception("定时检查失败", e)

    def on_tick(self, _):
        """每秒触发 — 检查是否该弹窗记录了"""
        if self.recording_lock:
            return

        now = datetime.datetime.now()
        self._maybe_show_daily_summary(now)

        # 首次启动：记录时间但不弹窗
        if self.last_check_time is None:
            self.last_check_time = now.isoformat()
            self._save_config()
            self._update_reminder_items()
            return

        try:
            last_check = datetime.datetime.fromisoformat(self.last_check_time)
        except (ValueError, TypeError):
            self.last_check_time = now.isoformat()
            self._save_config()
            self._update_reminder_items()
            return

        elapsed = (now - last_check).total_seconds() / 60

        if elapsed >= self.interval_minutes:
            # idle_threshold = 0 表示关闭空闲检测，始终弹窗
            if self.idle_threshold_minutes == 0:
                self._show_recording_dialog()
                return

            idle_seconds = get_idle_time()
            idle_minutes = idle_seconds / 60

            if idle_minutes < self.idle_threshold_minutes:
                # 电脑正在使用 → 弹窗
                self._show_recording_dialog()

    def _maybe_show_daily_summary(self, now):
        """到达每日指定时间后自动展示今日汇总，每天只展示一次。"""
        if not is_daily_summary_due(now, self.daily_summary_time, self.last_daily_summary_date):
            return
        self._activate_app_for_prompt()
        self.show_today_summary(None)
        self.last_daily_summary_date = now.date().isoformat()
        self._save_config()

    def _activate_app_for_prompt(self):
        """自动弹窗前把菜单栏应用激活到前台。"""
        try:
            import AppKit

            AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception as e:
            log_exception("激活应用窗口失败", e)

    def _show_recording_dialog(self):
        """弹出记录窗口——复选框勾选 + 自定义输入，点记录统一提交"""
        self.recording_lock = True
        reminder_time = datetime.datetime.now().isoformat()
        self.last_check_time = reminder_time
        self.last_reminder_time = reminder_time
        self._save_config()
        self._update_reminder_items()

        try:
            # 尝试原生面板，失败时回退到文本对话框
            if not self._try_panel_dialog():
                self._show_fallback_dialog()
        finally:
            self.recording_lock = False

    @staticmethod
    def _make_label(AppKit, Foundation, text, x, y, w, h, color=None, font=None, align=None):
        """创建不可编辑文本标签。"""
        label = AppKit.NSTextField.alloc().initWithFrame_(Foundation.NSMakeRect(x, y, w, h))
        label.setStringValue_(text)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        if color is not None:
            label.setTextColor_(color)
        if font is not None:
            label.setFont_(font)
        if align is not None:
            label.setAlignment_(align)
        if hasattr(label.cell(), "setLineBreakMode_") and hasattr(AppKit, "NSLineBreakByTruncatingTail"):
            label.cell().setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
        return label

    @staticmethod
    def _make_button(AppKit, Foundation, text, x, y, w, h, handler, action, bold=False):
        """创建原生按钮并绑定 handler。"""
        button = AppKit.NSButton.alloc().initWithFrame_(Foundation.NSMakeRect(x, y, w, h))
        button.setTitle_(text)
        button.setBezelStyle_(AppKit.NSBezelStyleRounded)
        button.setFont_(
            AppKit.NSFont.boldSystemFontOfSize_(13)
            if bold else AppKit.NSFont.systemFontOfSize_(13)
        )
        button.setTarget_(handler)
        button.setAction_(action)
        return button

    @staticmethod
    def _ui_color(AppKit, red, green, blue, alpha=1.0):
        """按 sRGB 分量创建颜色，兼容较旧的 macOS/PyObjC。"""
        return AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(red, green, blue, alpha)

    @staticmethod
    def _style_panel(AppKit, panel, content, background_color):
        """统一面板的基础外观。"""
        panel.setBackgroundColor_(background_color)
        content.setWantsLayer_(True)
        content.layer().setBackgroundColor_(background_color.CGColor())

    @classmethod
    def _make_card(cls, AppKit, Foundation, x, y, w, h, fill_color, border_color=None, radius=8):
        """创建克制的浅色卡片容器。"""
        box = AppKit.NSBox.alloc().initWithFrame_(Foundation.NSMakeRect(x, y, w, h))
        box.setBoxType_(AppKit.NSBoxCustom)
        box.setBorderType_(AppKit.NSLineBorder)
        box.setCornerRadius_(radius)
        if hasattr(box, "setFillColor_"):
            box.setFillColor_(fill_color)
        if border_color is not None and hasattr(box, "setBorderColor_"):
            box.setBorderColor_(border_color)
        return box

    @classmethod
    def _make_divider(cls, AppKit, Foundation, x, y, w):
        """创建一条轻量分隔线。"""
        line = AppKit.NSBox.alloc().initWithFrame_(Foundation.NSMakeRect(x, y, w, 1))
        separator_type = getattr(AppKit, "NSBoxSeparator", None)
        if separator_type is not None:
            line.setBoxType_(separator_type)
        else:
            line.setBoxType_(AppKit.NSBoxCustom)
            line.setBorderType_(AppKit.NSNoBorder)
            if hasattr(line, "setFillColor_"):
                line.setFillColor_(AppKit.NSColor.separatorColor())
        return line

    def _try_panel_dialog(self):
        """原生记录面板：更稳定的生命周期 + 更清爽的输入布局。"""
        import AppKit
        import Foundation

        panel = None
        checkboxes = []
        input_field = None
        result_list = []

        try:
            max_cols = 3
            cb_w, cb_h = 136, 30
            gap_x, gap_y = 10, 8
            rows = max(1, (len(self.presets) + max_cols - 1) // max_cols)
            preset_h = rows * cb_h + max(0, rows - 1) * gap_y

            panel_w = 560
            margin = 24
            section_w = panel_w - margin * 2
            preset_box_h = 42 + preset_h
            input_box_h = 58
            footer_h = 54
            gap = 10
            panel_h = int(margin + preset_box_h + gap + input_box_h + footer_h)
            bg_color = self._ui_color(AppKit, 0.965, 0.965, 0.95, 1.0)
            card_color = self._ui_color(AppKit, 1.0, 1.0, 0.985, 1.0)
            border_color = self._ui_color(AppKit, 0.84, 0.84, 0.80, 1.0)
            accent_color = self._ui_color(AppKit, 0.12, 0.28, 0.42, 1.0)

            panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                Foundation.NSMakeRect(0, 0, panel_w, panel_h),
                AppKit.NSTitledWindowMask | AppKit.NSClosableWindowMask,
                AppKit.NSBackingStoreBuffered,
                False,
            )
            panel.setTitle_("时间记录")
            panel.setFloatingPanel_(True)
            panel.setReleasedWhenClosed_(False)
            panel.center()
            panel.makeKeyAndOrderFront_(None)

            content = panel.contentView()
            self._style_panel(AppKit, panel, content, bg_color)

            preset_box_y = panel_h - margin - preset_box_h
            preset_box = self._make_card(
                AppKit, Foundation, margin, preset_box_y, section_w, preset_box_h,
                card_color, border_color,
            )
            content.addSubview_(preset_box)

            content.addSubview_(self._make_label(
                AppKit,
                Foundation,
                "常用活动",
                margin + 16,
                preset_box_y + preset_box_h - 28,
                section_w - 32,
                18,
                color=accent_color,
                font=AppKit.NSFont.boldSystemFontOfSize_(13.5),
            ))

            preset_start_y = preset_box_y + preset_box_h - 60
            for i, preset in enumerate(self.presets):
                col = i % max_cols
                row = i // max_cols
                cb = AppKit.NSButton.alloc().initWithFrame_(
                    Foundation.NSMakeRect(
                        margin + 16 + col * (cb_w + gap_x),
                        preset_start_y - row * (cb_h + gap_y),
                        cb_w,
                        cb_h,
                    )
                )
                cb.setTitle_(preset)
                cb.setButtonType_(AppKit.NSButtonTypeSwitch)
                cb.setFont_(AppKit.NSFont.systemFontOfSize_(13.5))
                cb.setState_(AppKit.NSOffState)
                content.addSubview_(cb)
                checkboxes.append(cb)

            input_box_y = preset_box_y - gap - input_box_h
            input_box = self._make_card(
                AppKit, Foundation, margin, input_box_y, section_w, input_box_h,
                card_color, border_color,
            )
            content.addSubview_(input_box)

            input_field = AppKit.NSTextField.alloc().initWithFrame_(
                Foundation.NSMakeRect(margin + 16, input_box_y + 13, section_w - 32, 32)
            )
            input_field.setFont_(AppKit.NSFont.systemFontOfSize_(13.5))
            content.addSubview_(input_field)

            handler = _SimplePanelHandler.alloc().init()
            retained_controls = [handler]

            record_btn = AppKit.NSButton.alloc().initWithFrame_(
                Foundation.NSMakeRect(panel_w - margin - 98, 14, 98, 34)
            )
            record_btn.setTitle_("记录")
            record_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
            record_btn.setFont_(AppKit.NSFont.boldSystemFontOfSize_(13))
            record_btn.setKeyEquivalent_("\r")
            record_btn.setTarget_(handler)
            record_btn.setAction_("recordClicked:")
            content.addSubview_(record_btn)

            skip_btn = AppKit.NSButton.alloc().initWithFrame_(
                Foundation.NSMakeRect(panel_w - margin - 98 - 12 - 78, 14, 78, 34)
            )
            skip_btn.setTitle_("跳过")
            skip_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
            skip_btn.setFont_(AppKit.NSFont.systemFontOfSize_(13))
            skip_btn.setTarget_(handler)
            skip_btn.setAction_("skipClicked:")
            content.addSubview_(skip_btn)

            retained_controls.extend([record_btn, skip_btn])
            panel.setDelegate_(handler)
            panel.makeFirstResponder_(input_field)

            result = AppKit.NSApplication.sharedApplication().runModalForWindow_(panel)

            if result == 1:
                for cb in checkboxes:
                    try:
                        if cb.state() == AppKit.NSOnState:
                            name = normalize_activity_name(cb.title())
                            if name:
                                result_list.append(name)
                    except Exception as e:
                        log_exception("读取记录面板勾选项失败", e)
                        pass
                try:
                    result_list.extend(parse_activity_input(input_field.stringValue(), self.presets))
                except Exception as e:
                    log_exception("读取记录面板输入内容失败", e)
                    pass

            panel.setDelegate_(None)
            panel.orderOut_(None)
            panel = None

            if result == 1 and result_list:
                for act in dict.fromkeys(result_list):
                    self._record_activity(act)
            return True

        except Exception as e:
            if panel is not None:
                try:
                    AppKit.NSApplication.sharedApplication().stopModalWithCode_(0)
                    panel.setDelegate_(None)
                    panel.orderOut_(None)
                except Exception as close_error:
                    log_exception("关闭记录面板失败", close_error)
                    pass
            log_exception("原生记录面板失败，已回退到文本输入", e)
            sys.stderr.write(f"[TimeRecorder] NSPanel 回退: {e}\n")
            return False

    def _show_fallback_dialog(self):
        """回退方案——使用 rumps.Window（文本输入模式）"""
        preset_lines = []
        for i, p in enumerate(self.presets):
            preset_lines.append(f"  [{i+1}] {p}")
        presets_hint = "\n".join(preset_lines)
        try:
            last_check = datetime.datetime.fromisoformat(self.last_check_time)
        except (ValueError, TypeError):
            last_check = datetime.datetime.now()
        next_check_time = last_check + datetime.timedelta(minutes=self.interval_minutes)

        win = rumps.Window(
            title="⏰ 时间记录",
            message=(
                f"下次记录时间：{next_check_time.strftime('%H:%M')}\n"
                f"现在在做什么？多个活动用逗号、顿号或换行分隔\n\n"
                f"📋 预设选项（输入数字快速选择）：\n"
                f"{presets_hint}\n\n"
                f"或直接输入自定义活动："
            ),
            default_text="",
            dimensions=(400, 220),
            cancel=True,
        )

        response = win.run()
        if response.clicked:
            text = response.text.strip()
            if not text:
                return

            for act in parse_activity_input(text, self.presets):
                self._record_activity(act)

    def trigger_record(self, _):
        """手动触发立即记录"""
        self._show_recording_dialog()

    def _reset_timer(self, _):
        """重置计时器：将 last_check_time 设为 interval 之前，下次 tick 立即弹窗"""
        now = datetime.datetime.now()
        self.last_check_time = (now - datetime.timedelta(minutes=self.interval_minutes + 1)).isoformat()
        self._save_config()
        self._update_reminder_items()
        safe_notification(
            title="⏱ 计时器已重置",
            subtitle=f"将在 {self.interval_minutes} 分钟内弹窗",
            message="（若空闲检测开启且电脑空闲中则跳过）",
            sound=False,
        )

    def _clear_all_activities(self, _):
        """清空全部记录（测试用）"""
        result = safe_alert(
            title="⚠️ 确认清空",
            message=f"将删除全部 {len(self.activities)} 条活动记录，此操作不可撤销！",
            ok="清空",
            cancel="取消",
        )
        if result:
            self.activities = []
            self._save_activities()
            self._update_last_activity()
            safe_notification(
                title="🗑 已清空",
                subtitle="全部活动记录已删除",
                message="",
                sound=False,
            )

    def open_error_logs(self, _):
        """在 Finder 中打开错误日志文件夹。"""
        try:
            log_dir = ensure_error_log_dir()
            subprocess.run(["open", log_dir], check=False)
        except Exception as e:
            log_exception("打开错误日志文件夹失败", e)
            safe_alert(
                title="错误日志",
                message=f"无法自动打开日志文件夹，请手动打开：\n{ERROR_LOG_DIR}",
            )

    def export_json(self, _):
        """导出全部活动记录为 JSON 文件。"""
        if not self.activities:
            safe_alert(title="📤 导出 JSON", message="暂无记录可导出")
            return

        dest_path = export_activities_json(self.activities)
        open_folder = safe_alert(
            title="✅ 导出完成",
            message=f"已导出 {len(self.activities)} 条记录到：\n{dest_path}\n\n是否打开所在文件夹？",
            ok="打开",
            cancel="稍后",
        )
        if open_folder:
            subprocess.run(["open", os.path.dirname(dest_path)], check=False)

    def export_csv(self, _):
        """导出全部活动记录为 CSV 文件。"""
        if not self.activities:
            safe_alert(title="📄 导出 CSV", message="暂无记录可导出")
            return

        dest_path = export_activities_csv(self.activities)
        open_folder = safe_alert(
            title="✅ 导出完成",
            message=f"已导出 {len(self.activities)} 条记录到：\n{dest_path}\n\n是否打开所在文件夹？",
            ok="打开",
            cancel="稍后",
        )
        if open_folder:
            subprocess.run(["open", os.path.dirname(dest_path)], check=False)

    def _record_activity(self, activity):
        """记录一条活动"""
        now = datetime.datetime.now()
        entry = {
            "timestamp": now.isoformat(),
            "activity": activity,
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
        }
        self.activities.append(entry)
        self._append_activity(entry)
        self._update_last_activity()

        safe_notification(
            title="✅ 已记录",
            subtitle=f"当前活动: {activity}",
            message="",
            sound=False,
        )

    def _update_last_activity(self):
        """更新菜单栏中的最近活动显示"""
        if not self.activities:
            self.last_activity_item.title = "⏳ 暂无记录"
            return
        last = self.activities[-1]
        self.last_activity_item.title = f"🕐 最近: {last['activity']} ({last['time']})"

    def _update_reminder_items(self):
        """更新菜单栏中的上次/下次提醒时间。"""
        if hasattr(self, "last_reminder_item"):
            self.last_reminder_item.title = f"🔔 上次提醒: {format_menu_datetime(self.last_reminder_time)}"
        if hasattr(self, "next_reminder_item"):
            next_time = calculate_next_reminder_time(self.last_check_time, self.interval_minutes)
            text = "暂无" if next_time is None else format_menu_datetime(next_time.isoformat())
            self.next_reminder_item.title = f"⏭ 下次提醒: {text}"

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  汇总功能
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _get_today_activities(self):
        """获取今日活动记录"""
        today = datetime.date.today().isoformat()
        return [a for a in self.activities if a["date"] == today]

    def _get_week_activities(self):
        """获取本周活动记录（周一～周日）"""
        today = datetime.date.today()
        monday = today - datetime.timedelta(days=today.weekday())
        sunday = monday + datetime.timedelta(days=6)
        return [
            a for a in self.activities
            if monday.isoformat() <= a["date"] <= sunday.isoformat()
        ]

    def _summarize_activities(self, activities, title):
        """格式化展示活动汇总"""
        if not activities:
            safe_alert(title=title, message="暂无记录 🫥")
            return

        summary = build_activity_summary(activities)
        if not self._try_summary_panel(summary, title):
            safe_alert(title=title, message=self._format_summary_text(summary))

    def _format_summary_text(self, summary):
        """统计页原生窗口失败时的文本兜底。"""
        total = summary["total"]
        lines = [
            f"共 {total} 条记录",
            f"活跃天数: {summary['active_days']}",
            f"最高频: {summary['top_activity']}",
            "",
            "活动分布",
        ]
        for act, count in summary["counts"]:
            pct = count / total * 100
            bar = "█" * max(1, int(pct / 5))
            lines.append(f"{bar} {act}: {count}次 ({pct:.0f}%)")

        lines.append("\n最近记录")
        for activity in summary["recent"][:20]:
            lines.append(f"  {activity.get('date', '')} {activity.get('time', '')}  {activity.get('activity', '')}")
        return "\n".join(lines)

    def _try_summary_panel(self, summary, title):
        """原生统计窗口。"""
        import AppKit
        import Foundation

        panel = None
        try:
            panel_w, panel_h = 800, 570
            bg_color = self._ui_color(AppKit, 0.965, 0.965, 0.95, 1.0)
            card_color = self._ui_color(AppKit, 1.0, 1.0, 0.985, 1.0)
            subtle_card_color = self._ui_color(AppKit, 0.982, 0.982, 0.965, 1.0)
            border_color = self._ui_color(AppKit, 0.84, 0.84, 0.80, 1.0)
            accent_color = self._ui_color(AppKit, 0.12, 0.28, 0.42, 1.0)
            panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                Foundation.NSMakeRect(0, 0, panel_w, panel_h),
                AppKit.NSTitledWindowMask | AppKit.NSClosableWindowMask,
                AppKit.NSBackingStoreBuffered,
                False,
            )
            panel.setTitle_(title)
            panel.setFloatingPanel_(True)
            panel.setReleasedWhenClosed_(False)
            panel.center()
            panel.makeKeyAndOrderFront_(None)

            content = panel.contentView()
            controls = []
            self._style_panel(AppKit, panel, content, bg_color)

            metric_y = panel_h - 102
            metrics = [
                ("总记录", str(summary["total"])),
                ("活跃天数", str(summary["active_days"])),
                ("最高频", summary["top_activity"]),
            ]
            card_gap = 16
            card_w = int((panel_w - 64 - card_gap * 2) / 3)
            for i, (label, value) in enumerate(metrics):
                x = 32 + i * (card_w + card_gap)
                box = self._make_card(
                    AppKit, Foundation, x, metric_y, card_w, 70,
                    card_color, border_color,
                )
                content.addSubview_(box)
                controls.append(box)
                content.addSubview_(self._make_label(
                    AppKit, Foundation, label, x + 16, metric_y + 42, card_w - 32, 16,
                    color=AppKit.NSColor.secondaryLabelColor(),
                    font=AppKit.NSFont.systemFontOfSize_(11),
                ))
                content.addSubview_(self._make_label(
                    AppKit, Foundation, value, x + 16, metric_y + 12, card_w - 32, 26,
                    color=accent_color,
                    font=AppKit.NSFont.boldSystemFontOfSize_(18),
                ))

            total = max(1, summary["total"])
            section_y = 70
            section_h = metric_y - section_y - 26
            left_x = 32
            gap = 18
            left_w = int((panel_w - 64 - gap) * 0.58)
            right_x = left_x + left_w + gap
            right_w = panel_w - 32 - right_x

            for x, w, heading, subheading in [
                (left_x, left_w, "活动分布", f"{len(summary['counts'])} 个活动类型"),
                (right_x, right_w, "最近记录", f"最近 {len(summary['recent'])} 条"),
            ]:
                box = self._make_card(
                    AppKit, Foundation, x, section_y, w, section_h,
                    card_color, border_color,
                )
                content.addSubview_(box)
                controls.append(box)
                content.addSubview_(self._make_label(
                    AppKit, Foundation, heading, x + 16, section_y + section_h - 34, w - 32, 20,
                    color=accent_color,
                    font=AppKit.NSFont.boldSystemFontOfSize_(14.5),
                ))
                content.addSubview_(self._make_label(
                    AppKit, Foundation, subheading, x + 16, section_y + section_h - 54, w - 32, 16,
                    color=AppKit.NSColor.secondaryLabelColor(),
                    font=AppKit.NSFont.systemFontOfSize_(11),
                    align=AppKit.NSRightTextAlignment,
                ))
                content.addSubview_(self._make_divider(
                    AppKit, Foundation, x + 16, section_y + section_h - 64, w - 32
                ))

            dist_scroll_y = section_y + 16
            dist_scroll_h = section_h - 86
            dist_scroll = AppKit.NSScrollView.alloc().initWithFrame_(
                Foundation.NSMakeRect(left_x + 16, dist_scroll_y, left_w - 32, dist_scroll_h)
            )
            dist_scroll.setHasVerticalScroller_(True)
            dist_scroll.setBorderType_(AppKit.NSNoBorder)
            dist_scroll.setDrawsBackground_(False)
            dist_doc_h = max(dist_scroll_h, len(summary["counts"]) * 42 + 8)
            dist_doc = AppKit.NSView.alloc().initWithFrame_(
                Foundation.NSMakeRect(0, 0, left_w - 52, dist_doc_h)
            )
            row_y = dist_doc_h - 34
            for act, count in summary["counts"]:
                pct = count / total * 100
                dist_doc.addSubview_(self._make_label(
                    AppKit, Foundation, act, 0, row_y + 8, 158, 18,
                    font=AppKit.NSFont.systemFontOfSize_(12.5),
                ))
                bar = AppKit.NSProgressIndicator.alloc().initWithFrame_(
                    Foundation.NSMakeRect(166, row_y + 11, max(110, left_w - 314), 10)
                )
                bar.setIndeterminate_(False)
                bar.setMinValue_(0)
                bar.setMaxValue_(100)
                bar.setDoubleValue_(pct)
                bar.setStyle_(AppKit.NSProgressIndicatorBarStyle)
                dist_doc.addSubview_(bar)
                controls.append(bar)
                dist_doc.addSubview_(self._make_label(
                    AppKit, Foundation, f"{count}次  {pct:.0f}%", left_w - 138, row_y + 8, 86, 18,
                    color=AppKit.NSColor.secondaryLabelColor(),
                    font=AppKit.NSFont.systemFontOfSize_(12),
                    align=AppKit.NSRightTextAlignment,
                ))
                row_y -= 42
            dist_scroll.setDocumentView_(dist_doc)
            content.addSubview_(dist_scroll)

            scroll = AppKit.NSScrollView.alloc().initWithFrame_(
                Foundation.NSMakeRect(right_x + 16, section_y + 16, right_w - 32, section_h - 86)
            )
            scroll.setHasVerticalScroller_(True)
            scroll.setBorderType_(AppKit.NSNoBorder)
            scroll.setDrawsBackground_(False)
            recent_doc_h = max(section_h - 86, len(summary["recent"]) * 34 + 8)
            recent_doc = AppKit.NSView.alloc().initWithFrame_(
                Foundation.NSMakeRect(0, 0, right_w - 52, recent_doc_h)
            )
            row_y = recent_doc_h - 30
            for activity in summary["recent"]:
                row_bg = self._make_card(
                    AppKit, Foundation, 0, row_y - 3, right_w - 54, 28,
                    subtle_card_color, None, radius=6,
                )
                row_bg.setBorderType_(AppKit.NSNoBorder)
                recent_doc.addSubview_(row_bg)
                controls.append(row_bg)
                recent_doc.addSubview_(self._make_label(
                    AppKit, Foundation, activity.get("time", ""), 10, row_y + 2, 46, 18,
                    color=AppKit.NSColor.secondaryLabelColor(),
                    font=AppKit.NSFont.monospacedSystemFontOfSize_weight_(12, 0),
                ))
                recent_doc.addSubview_(self._make_label(
                    AppKit, Foundation, activity.get("activity", ""), 66, row_y + 2, right_w - 130, 18,
                    font=AppKit.NSFont.systemFontOfSize_(12.5),
                ))
                row_y -= 34
            scroll.setDocumentView_(recent_doc)
            content.addSubview_(scroll)

            handler = _SimplePanelHandler.alloc().init()
            close_btn = self._make_button(
                AppKit, Foundation, "关闭", panel_w - 108, 22, 76, 32,
                handler, "closeClicked:", bold=False,
            )
            content.addSubview_(close_btn)
            retained_controls = [handler, close_btn, scroll, recent_doc, dist_scroll, dist_doc] + controls
            panel.setDelegate_(handler)

            AppKit.NSApplication.sharedApplication().runModalForWindow_(panel)
            panel.setDelegate_(None)
            panel.orderOut_(None)
            return True
        except Exception as e:
            if panel is not None:
                try:
                    AppKit.NSApplication.sharedApplication().stopModalWithCode_(0)
                    panel.setDelegate_(None)
                    panel.orderOut_(None)
                except Exception as close_error:
                    log_exception("关闭统计窗口失败", close_error)
                    pass
            log_exception("原生统计窗口失败，已回退到文本汇总", e)
            sys.stderr.write(f"[TimeRecorder] Summary panel fallback: {e}\n")
            return False

    def show_today_summary(self, _):
        """显示今日汇总"""
        acts = self._get_today_activities()
        self._summarize_activities(acts, "📅 今日汇总")

    def show_week_summary(self, _):
        """显示本周汇总"""
        acts = self._get_week_activities()
        self._summarize_activities(acts, "📆 本周汇总")

    def show_all_summary(self, _):
        """显示全部记录"""
        self._summarize_activities(self.activities, "📊 全部记录")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  检查更新
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    def _compare_versions(v1, v2):
        def parse(v):
            v = v.lstrip("v")
            parts = v.split(".")
            return tuple(int(x) if x.isdigit() else 0 for x in parts)
        v1t, v2t = parse(v1), parse(v2)
        if v1t > v2t:
            return 1
        if v1t < v2t:
            return -1
        return 0

    def check_update(self, _):
        self.update_item.title = "🔄 检查中…"
        try:
            req = urllib.request.Request(
                __github_api__,
                headers={
                    "User-Agent": f"TimeRecorder/{__version__}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latest_tag = data.get("tag_name", "").lstrip("v")
                release_url = data.get("html_url", f"{__repo_url__}/releases")
                asset = select_release_asset(data.get("assets", []))

            if not latest_tag:
                safe_alert(title="🔄 检查更新", message="未能获取版本信息，请稍后重试")
                return

            cmp = self._compare_versions(latest_tag, __version__)
            if cmp > 0:
                if not asset:
                    safe_alert(
                        title="🔄 发现新版本！",
                        message=(
                            f"当前版本: v{__version__}\n"
                            f"最新版本: v{latest_tag}\n\n"
                            "这个 Release 没有可下载的安装包，请前往 GitHub Releases 查看：\n"
                            f"{release_url}"
                        ),
                    )
                    return

                asset_name = safe_download_filename(asset.get("name"))
                confirm = safe_alert(
                    title="🔄 发现新版本！",
                    message=(
                        f"当前版本: v{__version__}\n"
                        f"最新版本: v{latest_tag}\n\n"
                        f"将下载：{asset_name}\n"
                        "下载完成后需要手动打开安装。"
                    ),
                    ok="下载",
                    cancel="取消",
                )
                if not confirm:
                    return

                self.update_item.title = "⬇️ 下载中…"
                dest_path = unique_download_path(DOWNLOAD_DIR, asset_name)
                download_release_asset(asset.get("browser_download_url"), dest_path)
                open_folder = safe_alert(
                    title="✅ 下载完成",
                    message=f"已保存到：\n{dest_path}\n\n是否打开下载文件夹？",
                    ok="打开",
                    cancel="稍后",
                )
                if open_folder:
                    subprocess.run(["open", os.path.dirname(dest_path)], check=False)
            else:
                safe_alert(title="🔄 检查更新", message=f"当前版本: v{__version__}\n已是最新版本 🎉")
        except urllib.error.URLError:
            safe_alert(title="🔄 检查更新", message="网络连接失败，请检查网络后重试")
        except json.JSONDecodeError:
            safe_alert(title="🔄 检查更新", message="解析版本响应失败，请稍后重试")
        except Exception as e:
            log_exception("检查更新失败", e)
            safe_alert(title="🔄 检查更新", message=f"检查失败: {e}")
        finally:
            self.update_item.title = "🔄 检查更新"

    def show_about(self, _):
        """关于信息"""
        safe_alert(
            title=f"⏰ 干啥来着 v{__version__}",
            message=(
                "macOS 菜单栏活动记录器\n\n"
                f"默认每 {DEFAULT_INTERVAL} 分钟询问一次当前活动\n"
                "检测到电脑空闲超过阈值时自动跳过\n"
                "支持今日 / 本周 / 全部汇总\n"
                "🧪 测试菜单方便快速验证\n\n"
                "基于 Python rumps 构建\n"
                f"版本: v{__version__}"
            ),
        )

    def quit_app(self, _):
        """退出应用前保存配置"""
        self.timer.stop()
        self._save_config()
        rumps.quit_application()


if __name__ == "__main__":
    install_exception_logging()
    TimeRecorder().run()
