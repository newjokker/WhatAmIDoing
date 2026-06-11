#!/usr/bin/env python3
"""
⏰ 时间记录器 - macOS 菜单栏活动记录器
基于 rumps 实现

功能:
    - 每 N 分钟（默认 5 分钟）弹窗询问"当前在做什么"
    - 检测电脑是否在使用中（空闲超过阈值则跳过，可关闭）
    - 简化弹窗：勾选复选框 + 输入自定义，点记录统一提交
    - 今日 / 本周 / 全部活动汇总
    - 自定义预设活动列表
    - 设置持久化（重启后保留）
"""

__version__ = "1.4.4"
__app_name__ = "⏰ 时间记录器"
__repo_url__ = "https://github.com/newjokker/WhatAmIDoing"
__github_api__ = "https://api.github.com/repos/newjokker/WhatAmIDoing/releases/latest"

import rumps
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
DEFAULT_PRESETS = ["写代码", "开会", "阅读", "学习", "思考", "摸鱼"]
MAX_ACTIVITY_LENGTH = 20
MAX_PRESETS = 12

CONFIG_DIR = os.path.expanduser("~")
CONFIG_FILE = os.path.join(CONFIG_DIR, ".time_recorder.json")
ERROR_LOG_DIR = os.path.expanduser("~/Library/Logs/TimeRecorder")
ERROR_LOG_FILE = os.path.join(ERROR_LOG_DIR, "error.log")


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
    """菜单栏时间记录器"""

    def __init__(self):
        super().__init__("⏰ 待命", quit_button=None)

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
        self.activities = config.get("activities", [])
        self.recording_lock = False  # 防止重复弹窗

        # ── 更新菜单栏标题 ──
        self.title = f"⏰ {self.interval_minutes}min"

        # ── 构建菜单 ──
        self._build_menu()

        # ── 启动定时器 ──
        self.timer.start()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  配置持久化
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _load_config(self):
        """从 JSON 文件加载配置"""
        if not os.path.exists(CONFIG_FILE):
            return {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log_exception("加载配置失败", e)
            return {}

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
            "activities": self.activities,
        }
        try:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".json",
                dir=CONFIG_DIR, delete=False,
            )
            try:
                json.dump(config, tmp, indent=2, ensure_ascii=False)
                tmp.flush()
                os.fsync(tmp.fileno())
            finally:
                tmp.close()
            os.replace(tmp.name, CONFIG_FILE)
        except OSError as e:
            log_exception("保存配置失败", e)
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

        # ── 汇总菜单 ──
        self.today_item = rumps.MenuItem("📅 今日汇总", callback=self._menu_callback("今日汇总", self.show_today_summary))
        self.week_item = rumps.MenuItem("📆 本周汇总", callback=self._menu_callback("本周汇总", self.show_week_summary))
        self.all_item = rumps.MenuItem("📊 全部记录", callback=self._menu_callback("全部记录", self.show_all_summary))

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
            None,
            self.today_item,
            self.week_item,
            self.all_item,
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
        self.title = f"⏰ {self.interval_minutes}min"
        self._save_config()

    def _on_set_idle_threshold(self, sender):
        """设置空闲阈值"""
        for item in self.idle_submenu.values():
            if isinstance(item, rumps.MenuItem):
                item.state = False
        sender.state = True
        self.idle_threshold_minutes = sender._setting_value
        self._save_config()

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

        # 首次启动：记录时间但不弹窗
        if self.last_check_time is None:
            self.last_check_time = now.isoformat()
            self._save_config()
            return

        try:
            last_check = datetime.datetime.fromisoformat(self.last_check_time)
        except (ValueError, TypeError):
            self.last_check_time = now.isoformat()
            self._save_config()
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

    def _show_recording_dialog(self):
        """弹出记录窗口——复选框勾选 + 自定义输入，点记录统一提交"""
        self.recording_lock = True
        self.last_check_time = datetime.datetime.now().isoformat()
        self._save_config()

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
            cb_w, cb_h = 130, 28
            gap_x, gap_y = 12, 8
            rows = max(1, (len(self.presets) + max_cols - 1) // max_cols)
            preset_h = rows * cb_h + max(0, rows - 1) * gap_y

            panel_w = 520
            margin = 24
            section_w = panel_w - margin * 2
            header_h = 72
            preset_box_h = 56 + preset_h
            input_box_h = 88
            footer_h = 56
            gap = 14
            panel_h = int(margin + header_h + gap + preset_box_h + gap + input_box_h + footer_h)

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

            title_lbl = self._make_label(
                AppKit,
                Foundation,
                "现在在做什么？",
                margin,
                panel_h - 44,
                section_w,
                26,
                font=AppKit.NSFont.boldSystemFontOfSize_(20),
            )
            content.addSubview_(title_lbl)

            hint_lbl = self._make_label(
                AppKit,
                Foundation,
                "选择一个或多个预设，也可以补充自定义活动。",
                margin,
                panel_h - 68,
                section_w,
                18,
                color=AppKit.NSColor.secondaryLabelColor(),
                font=AppKit.NSFont.systemFontOfSize_(12),
            )
            content.addSubview_(hint_lbl)

            preset_box_y = panel_h - margin - header_h - gap - preset_box_h
            preset_box = AppKit.NSBox.alloc().initWithFrame_(
                Foundation.NSMakeRect(margin, preset_box_y, section_w, preset_box_h)
            )
            preset_box.setBoxType_(AppKit.NSBoxCustom)
            preset_box.setBorderType_(AppKit.NSLineBorder)
            preset_box.setCornerRadius_(8)
            content.addSubview_(preset_box)

            content.addSubview_(self._make_label(
                AppKit,
                Foundation,
                "常用活动",
                margin + 16,
                preset_box_y + preset_box_h - 30,
                section_w - 32,
                18,
                font=AppKit.NSFont.boldSystemFontOfSize_(13),
            ))
            content.addSubview_(self._make_label(
                AppKit,
                Foundation,
                "勾选后点击记录，可同时选择多项。",
                margin + 16,
                preset_box_y + preset_box_h - 50,
                section_w - 32,
                16,
                color=AppKit.NSColor.secondaryLabelColor(),
                font=AppKit.NSFont.systemFontOfSize_(11),
            ))

            preset_start_y = preset_box_y + preset_box_h - 84
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
                cb.setFont_(AppKit.NSFont.systemFontOfSize_(13))
                cb.setState_(AppKit.NSOffState)
                content.addSubview_(cb)
                checkboxes.append(cb)

            input_box_y = preset_box_y - gap - input_box_h
            input_box = AppKit.NSBox.alloc().initWithFrame_(
                Foundation.NSMakeRect(margin, input_box_y, section_w, input_box_h)
            )
            input_box.setBoxType_(AppKit.NSBoxCustom)
            input_box.setBorderType_(AppKit.NSLineBorder)
            input_box.setCornerRadius_(8)
            content.addSubview_(input_box)

            input_lbl = self._make_label(
                AppKit,
                Foundation,
                "自定义活动",
                margin + 16,
                input_box_y + input_box_h - 30,
                section_w - 32,
                18,
                font=AppKit.NSFont.boldSystemFontOfSize_(13),
            )
            content.addSubview_(input_lbl)

            input_field = AppKit.NSTextField.alloc().initWithFrame_(
                Foundation.NSMakeRect(margin + 16, input_box_y + 18, section_w - 32, 30)
            )
            input_field.setPlaceholderString_("例如：写文档，沟通需求；可用逗号、顿号或换行分隔")
            input_field.setFont_(AppKit.NSFont.systemFontOfSize_(13))
            content.addSubview_(input_field)

            handler = _SimplePanelHandler.alloc().init()
            retained_controls = [handler]

            record_btn = AppKit.NSButton.alloc().initWithFrame_(
                Foundation.NSMakeRect(panel_w - margin - 94, 18, 94, 32)
            )
            record_btn.setTitle_("记录")
            record_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
            record_btn.setFont_(AppKit.NSFont.boldSystemFontOfSize_(13))
            record_btn.setKeyEquivalent_("\r")
            record_btn.setTarget_(handler)
            record_btn.setAction_("recordClicked:")
            content.addSubview_(record_btn)

            skip_btn = AppKit.NSButton.alloc().initWithFrame_(
                Foundation.NSMakeRect(panel_w - margin - 94 - 12 - 74, 18, 74, 32)
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

        win = rumps.Window(
            title="⏰ 时间记录",
            message=(
                f"距离上次记录已过去 {self.interval_minutes} 分钟\n"
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
            self._save_config()
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
        self._save_config()
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
            panel_w, panel_h = 600, 560
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

            content.addSubview_(self._make_label(
                AppKit, Foundation, title, 24, panel_h - 44, panel_w - 48, 26,
                font=AppKit.NSFont.boldSystemFontOfSize_(20),
            ))
            content.addSubview_(self._make_label(
                AppKit, Foundation, "活动分布和最近记录", 24, panel_h - 68, panel_w - 48, 18,
                color=AppKit.NSColor.secondaryLabelColor(),
                font=AppKit.NSFont.systemFontOfSize_(12),
            ))

            metric_y = panel_h - 122
            metrics = [
                ("总记录", str(summary["total"])),
                ("活跃天数", str(summary["active_days"])),
                ("最高频", summary["top_activity"]),
            ]
            card_w = 176
            for i, (label, value) in enumerate(metrics):
                x = 24 + i * (card_w + 12)
                box = AppKit.NSBox.alloc().initWithFrame_(Foundation.NSMakeRect(x, metric_y, card_w, 52))
                box.setBoxType_(AppKit.NSBoxCustom)
                box.setBorderType_(AppKit.NSLineBorder)
                box.setCornerRadius_(8)
                content.addSubview_(box)
                content.addSubview_(self._make_label(
                    AppKit, Foundation, label, x + 12, metric_y + 28, card_w - 24, 16,
                    color=AppKit.NSColor.secondaryLabelColor(),
                    font=AppKit.NSFont.systemFontOfSize_(11),
                ))
                content.addSubview_(self._make_label(
                    AppKit, Foundation, value, x + 12, metric_y + 8, card_w - 24, 22,
                    font=AppKit.NSFont.boldSystemFontOfSize_(15),
                ))

            distribution_title_y = metric_y - 38
            content.addSubview_(self._make_label(
                AppKit, Foundation, "活动分布", 24, distribution_title_y, panel_w - 48, 20,
                font=AppKit.NSFont.boldSystemFontOfSize_(14),
            ))

            total = max(1, summary["total"])
            row_y = distribution_title_y - 32
            max_rows = 8
            for act, count in summary["counts"][:max_rows]:
                pct = count / total * 100
                content.addSubview_(self._make_label(
                    AppKit, Foundation, act, 24, row_y, 130, 18,
                    font=AppKit.NSFont.systemFontOfSize_(12),
                ))
                bar = AppKit.NSProgressIndicator.alloc().initWithFrame_(
                    Foundation.NSMakeRect(160, row_y + 2, 310, 12)
                )
                bar.setIndeterminate_(False)
                bar.setMinValue_(0)
                bar.setMaxValue_(100)
                bar.setDoubleValue_(pct)
                bar.setStyle_(AppKit.NSProgressIndicatorBarStyle)
                content.addSubview_(bar)
                content.addSubview_(self._make_label(
                    AppKit, Foundation, f"{count}次  {pct:.0f}%", 482, row_y, 88, 18,
                    color=AppKit.NSColor.secondaryLabelColor(),
                    font=AppKit.NSFont.systemFontOfSize_(12),
                    align=AppKit.NSRightTextAlignment,
                ))
                row_y -= 28

            timeline_y = row_y - 18
            content.addSubview_(self._make_label(
                AppKit, Foundation, "最近记录", 24, timeline_y, panel_w - 48, 20,
                font=AppKit.NSFont.boldSystemFontOfSize_(14),
            ))

            timeline_text = "\n".join(
                f"{activity.get('date', '')}  {activity.get('time', '')}    {activity.get('activity', '')}"
                for activity in summary["recent"]
            )
            scroll = AppKit.NSScrollView.alloc().initWithFrame_(
                Foundation.NSMakeRect(24, 66, panel_w - 48, max(120, timeline_y - 78))
            )
            scroll.setHasVerticalScroller_(True)
            scroll.setBorderType_(AppKit.NSBezelBorder)
            text_view = AppKit.NSTextView.alloc().initWithFrame_(
                Foundation.NSMakeRect(0, 0, panel_w - 58, max(120, timeline_y - 78))
            )
            text_view.setString_(timeline_text)
            text_view.setEditable_(False)
            text_view.setSelectable_(True)
            text_view.setFont_(AppKit.NSFont.monospacedSystemFontOfSize_weight_(12, 0))
            text_view.setTextColor_(AppKit.NSColor.labelColor())
            text_view.setBackgroundColor_(AppKit.NSColor.textBackgroundColor())
            scroll.setDocumentView_(text_view)
            content.addSubview_(scroll)

            handler = _SimplePanelHandler.alloc().init()
            close_btn = self._make_button(
                AppKit, Foundation, "关闭", panel_w - 96, 18, 72, 32,
                handler, "closeClicked:", bold=False,
            )
            content.addSubview_(close_btn)
            retained_controls = [handler, close_btn, text_view, scroll]
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

            if not latest_tag:
                safe_alert(title="🔄 检查更新", message="未能获取版本信息，请稍后重试")
                return

            cmp = self._compare_versions(latest_tag, __version__)
            if cmp > 0:
                safe_alert(
                    title="🔄 发现新版本！",
                    message=(
                        f"当前版本: v{__version__}\n"
                        f"最新版本: v{latest_tag}\n\n"
                        "请前往 GitHub Releases 下载：\n"
                        f"{release_url}"
                    ),
                )
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
            title=f"⏰ 时间记录器 v{__version__}",
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
