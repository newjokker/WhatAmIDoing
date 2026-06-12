# ⏰ 干啥来着

macOS 菜单栏活动记录器 — 定时提醒你记录当前在做什么。

## 功能

### 核心机制
- **定时弹窗**：每 N 分钟（默认 5 分钟）自动弹出窗口询问"当前在做什么"
- **智能跳过**：检测电脑空闲状态（如锁屏、离开），空闲时自动跳过（可关闭）
- **快速选择**：预设选项显示为**复选框按钮**，点击即可勾选，支持多选
- **多活动记录**：一次可记录多个事情——勾选多个预设 + 自定义输入逗号分隔
- **每条 20 字上限**：每条活动名称最多 20 个字
- **每日回顾**：可在每天指定时间自动弹出今日汇总，默认 17:30
- **开机自启**：可在设置中开启，登录 macOS 后自动启动

### 预设选项
默认预设：`写代码`、`开会`、`阅读`、`学习`、`思考`、`摸鱼`

支持在设置菜单中**添加/删除/恢复默认**预设。

### 汇总功能
- 📅 **今日汇总** — 今天各项活动频率统计 + 时间线
- 📆 **本周汇总** — 本周活动分布概览
- 📊 **全部记录** — 所有历史记录统计
- 📤 **导出 JSON** — 保留完整元数据和活动列表，适合备份或程序读取
- 📄 **导出 CSV** — 可用 Numbers、Excel 或数据分析工具打开

### 技术特性
- 纯 Python 实现，基于 [rumps](https://github.com/jaredks/rumps) 框架
- 配置原子写入，防止崩溃损坏
- 配置保存至 `~/.time_recorder_config.json`
- 活动历史保存至 `~/.time_recorder_activities.jsonl`
- 错误日志保存至 `~/Library/Logs/TimeRecorder/error.log`
- 版本号统一维护在 `app_version.py`
- 支持检查 GitHub 更新
- ARM64 原生构建

## 安装

### 下载 DMG

从 [GitHub Releases](https://github.com/newjokker/WhatAmIDoing/releases) 下载最新 DMG 安装包。

### 从源码构建

```bash
# 克隆仓库
git clone https://github.com/newjokker/WhatAmIDoing.git
cd WhatAmIDoing

# 安装依赖
pip install rumps py2app

# 构建 .app
make app

# 打包 DMG
make dmg
```

详见 [BUILD_LOCAL.md](BUILD_LOCAL.md) 本机构建指南。

## 使用

1. 启动应用后，菜单栏出现 ⏰ 图标
2. 每 5 分钟（可调至 1~120 分钟）自动弹出记录窗口
3. 可随时点击菜单栏 → 「🔍 立即记录」手动记录
4. 在「⚙ 设置」中调整记录间隔、空闲阈值、预设选项
5. 通过「📅 今日汇总」「📆 本周汇总」查看统计
6. 通过「📤 导出 JSON」或「📄 导出 CSV」导出全部记录
7. 🧪 测试菜单可「重置计时器」立即触发弹窗，或「清空记录」方便反复测试

## 数据文件

应用会自动从旧版 `~/.time_recorder.json` 迁移到新的分离存储：

| 文件 | 作用 |
|------|------|
| `~/.time_recorder_config.json` | 记录间隔、空闲阈值、预设选项、每日汇总时间等配置 |
| `~/.time_recorder_activities.jsonl` | 活动历史，每行一条 JSON 记录 |
| `~/Library/Logs/TimeRecorder/error.log` | 异常日志，方便排查菜单操作或弹窗问题 |

JSON 导出文件会包含应用版本、导出时间、记录总数和完整活动列表。CSV 导出文件包含 `timestamp`、`date`、`time`、`activity` 四列。

## 发布维护

版本号只需要修改 [app_version.py](app_version.py)。运行时代码、`setup.py`、`Makefile` 和 `build_dmg.sh` 都会读取同一个版本来源。

```bash
# 运行测试
python -m unittest tests/test_time_recorder.py

# 查看当前打包版本
python setup.py --version

# 构建发布包
make dmg
```

## 许可

MIT License
