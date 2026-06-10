#!/usr/bin/env python3
"""
⏰ 时间记录器 - macOS 菜单栏活动记录器
基于 rumps 实现

功能:
    - 每 N 分钟（默认 45 分钟）弹窗询问"当前在做什么"
    - 检测电脑是否在使用中（空闲超过阈值则跳过）
    - 预设选项快速选择 + 自定义输入
    - 今日 / 本周 / 全部活动汇总
    - 自定义预设活动列表
    - 设置持久化（重启后保留）
"""

__version__ = "1.0.0"
__app_name__ = "⏰ 时间记录器"
__repo_url__ = "https://github.com/newjokker/TimeRecorder"
__github_api__ = "https://api.github.com/repos/newjokker/TimeRecorder/releases/latest"

import rumps
import json
import os
import datetime
import tempfile
import subprocess
import re
import urllib.request
import urllib.error

# ═══════════════════════════════════════
#  默认配置
# ═══════════════════════════════════════
DEFAULT_INTERVAL = 45          # 弹窗间隔（分钟）
DEFAULT_IDLE_THRESHOLD = 5     # 空闲阈值（分钟），超过此值视为电脑无人使用
DEFAULT_PRESETS = ["写代码", "开会", "阅读", "学习", "思考", "摸鱼"]

CONFIG_DIR = os.path.expanduser("~")
CONFIG_FILE = os.path.join(CONFIG_DIR, ".time_recorder.json")


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
    except Exception:
        pass
    return 0


class TimeRecorder(rumps.App):
    """菜单栏时间记录器"""

    def __init__(self):
        super().__init__("⏰ 待命", quit_button=None)

        # ── 从文件加载配置 ──
        config = self._load_config()

        # ── 状态 ──
        self.timer = rumps.Timer(self.on_tick, 1)
        self.interval_minutes = config.get("interval_minutes", DEFAULT_INTERVAL)
        self.idle_threshold_minutes = config.get("idle_threshold_minutes", DEFAULT_IDLE_THRESHOLD)
        self.presets = config.get("presets", list(DEFAULT_PRESETS))
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
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_config(self):
        """原子写入配置"""
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
        except OSError:
            pass

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  菜单构建
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _build_menu(self):
        """组装菜单结构"""
        # ── 立即记录 ──
        self.check_now_item = rumps.MenuItem("🔍 立即记录", callback=self.trigger_record)

        # ── 上次活动 ──
        self.last_activity_item = rumps.MenuItem("⏳ 暂无记录", callback=None)

        # ── 汇总菜单 ──
        self.today_item = rumps.MenuItem("📅 今日汇总", callback=self.show_today_summary)
        self.week_item = rumps.MenuItem("📆 本周汇总", callback=self.show_week_summary)
        self.all_item = rumps.MenuItem("📊 全部记录", callback=self.show_all_summary)

        # ── 设置子菜单 ──
        self.settings_menu = rumps.MenuItem("⚙ 设置")

        # 记录间隔
        self.interval_submenu = rumps.MenuItem("⏱ 记录间隔")
        self._setup_duration_menu(self.interval_submenu, self.interval_minutes,
                                  [15, 30, 45, 60, 90, 120], self._on_set_interval)
        self.settings_menu.add(self.interval_submenu)

        # 空闲阈值
        self.idle_submenu = rumps.MenuItem("💤 空闲阈值")
        self._setup_duration_menu(self.idle_submenu, self.idle_threshold_minutes,
                                  [1, 3, 5, 10, 15, 30], self._on_set_idle_threshold)
        self.settings_menu.add(self.idle_submenu)

        # 预设选项管理
        self.presets_submenu = rumps.MenuItem("📋 预设选项")
        self._rebuild_presets_menu()
        self.settings_menu.add(self.presets_submenu)

        # ── 检查更新 ──
        self.update_item = rumps.MenuItem("🔄 检查更新", callback=self.check_update)

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
            self.update_item,
            None,
            rumps.MenuItem("❓ 关于", callback=self.show_about),
            None,
            rumps.MenuItem("🚪 退出", callback=self.quit_app),
        ]

        self._update_last_activity()

    def _setup_duration_menu(self, parent, current_value, values, callback):
        """为子菜单添加时长选项列表"""
        for v in values:
            label = f"{v} 分钟"
            item = rumps.MenuItem(label, callback=callback)
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
            item = rumps.MenuItem(f"  {preset}", callback=self._on_delete_preset)
            item._preset_index = i
            self.presets_submenu.add(item)

        if self.presets:
            self.presets_submenu.add(rumps.MenuItem(None))

        # 管理按钮
        add_item = rumps.MenuItem("✚ 添加预设", callback=self._on_add_preset)
        self.presets_submenu.add(add_item)
        reset_item = rumps.MenuItem("↺ 恢复默认", callback=self._on_reset_presets)
        self.presets_submenu.add(reset_item)

    def _on_delete_preset(self, sender):
        """删除预设（点击预设项即删除）"""
        idx = sender._preset_index
        name = self.presets[idx]
        result = rumps.alert(
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
        if len(self.presets) >= 20:
            rumps.alert(title="提示", message="最多支持 20 个预设选项")
            return

        win = rumps.Window(
            title="添加预设",
            message="请输入新的预设活动名称：",
            default_text="",
            cancel=True,
        )
        response = win.run()
        if response.clicked:
            name = response.text.strip()
            if not name:
                rumps.alert(title="提示", message="名称不能为空")
                return
            if name in self.presets:
                rumps.alert(title="提示", message=f"「{name}」已存在")
                return
            self.presets.append(name)
            self._rebuild_presets_menu()
            self._save_config()

    def _on_reset_presets(self, _):
        """恢复默认预设"""
        result = rumps.alert(
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
            idle_seconds = get_idle_time()
            idle_minutes = idle_seconds / 60

            if idle_minutes < self.idle_threshold_minutes:
                # 电脑正在使用 → 弹窗
                self._show_recording_dialog()

    def _show_recording_dialog(self):
        """弹出记录窗口，询问当前活动"""
        self.recording_lock = True
        self.last_check_time = datetime.datetime.now().isoformat()
        self._save_config()

        # 构建预设提示文本
        preset_lines = []
        for i, p in enumerate(self.presets):
            preset_lines.append(f"  [{i+1}] {p}")
        presets_hint = "\n".join(preset_lines)

        win = rumps.Window(
            title="⏰ 时间记录",
            message=(
                f"距离上次记录已过去 {self.interval_minutes} 分钟\n"
                f"现在在做什么？\n\n"
                f"📋 预设选项（输入数字快速选择）：\n"
                f"{presets_hint}\n\n"
                f"或直接输入自定义活动描述："
            ),
            default_text="",
            dimensions=(400, 220),
            cancel=True,
        )

        response = win.run()
        if response.clicked:
            text = response.text.strip()
            if not text:
                self.recording_lock = False
                return

            # 检测是否为预设编号
            activity = text
            if text.isdigit():
                idx = int(text) - 1
                if 0 <= idx < len(self.presets):
                    activity = self.presets[idx]

            self._record_activity(activity)
        # 取消弹窗 ⇒ 不记录，但 last_check_time 已更新（避免连续弹窗）

        self.recording_lock = False

    def trigger_record(self, _):
        """手动触发立即记录"""
        self._show_recording_dialog()

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

        rumps.notification(
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
            rumps.alert(title=title, message="暂无记录 🫥")
            return

        # 按活动名称聚合统计
        counts = {}
        for a in activities:
            act = a["activity"]
            counts[act] = counts.get(act, 0) + 1

        sorted_acts = sorted(counts.items(), key=lambda x: -x[1])
        total = len(activities)

        lines = [f"共 {total} 条记录\n"]
        for act, count in sorted_acts:
            pct = count / total * 100
            bar_len = max(1, int(pct / 5))
            bar = "█" * bar_len
            lines.append(f"{bar} {act}: {count}次 ({pct:.0f}%)")

        # 时间线（最近 20 条）
        lines.append(f"\n── 时间线（最近）──")
        recent = activities[-20:]
        for a in recent:
            lines.append(f"  {a['time']}  {a['activity']}")
        if total > 20:
            lines.append(f"  ... 共 {total} 条")

        rumps.alert(title=title, message="\n".join(lines))

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
                rumps.alert(title="🔄 检查更新", message="未能获取版本信息，请稍后重试")
                return

            cmp = self._compare_versions(latest_tag, __version__)
            if cmp > 0:
                rumps.alert(
                    title="🔄 发现新版本！",
                    message=(
                        f"当前版本: v{__version__}\n"
                        f"最新版本: v{latest_tag}\n\n"
                        "请前往 GitHub Releases 下载：\n"
                        f"{release_url}"
                    ),
                )
            else:
                rumps.alert(title="🔄 检查更新", message=f"当前版本: v{__version__}\n已是最新版本 🎉")
        except urllib.error.URLError:
            rumps.alert(title="🔄 检查更新", message="网络连接失败，请检查网络后重试")
        except json.JSONDecodeError:
            rumps.alert(title="🔄 检查更新", message="解析版本响应失败，请稍后重试")
        except Exception as e:
            rumps.alert(title="🔄 检查更新", message=f"检查失败: {e}")
        finally:
            self.update_item.title = "🔄 检查更新"

    def show_about(self, _):
        """关于信息"""
        rumps.alert(
            title=f"⏰ 时间记录器 v{__version__}",
            message=(
                "macOS 菜单栏活动记录器\n\n"
                f"默认每 {DEFAULT_INTERVAL} 分钟询问一次当前活动\n"
                "检测到电脑空闲超过阈值时自动跳过\n"
                "支持今日 / 本周 / 全部汇总\n\n"
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
    TimeRecorder().run()
