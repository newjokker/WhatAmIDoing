# 变更日志

## v1.4.2 (2026-06-11)

### 修复（关键崩溃修复）
- **彻底修复勾选复选框 + 输入自定义内容时 app 崩溃消失的问题**
  - 根因：`_SimplePanelHandler`（ObjC 回调类）持有 `self._checkboxes` 列表中的 NSButton 对象引用，
    `recordClicked_` 回调中遍历并访问这些 ObjC 对象时，若面板正在关闭/对象状态异常，会触发 SegFault，导致整个 app 崩溃
  - 修复：`_SimplePanelHandler` 不再持有任何 ObjC 对象引用，`recordClicked_` / `skipClicked_` 只调用 `stopModalWithCode_`
  - 面板内容读取改为：模态结束后、面板释放前，在 Python 侧统一读取 checkbox 状态和输入框内容
  - 这是唯一安全的做法——ObjC 回调里不碰任何 ObjC 控件对象

### 技术细节
- `checkboxes` 和 `input_field` 改为 `_try_panel_dialog` 的局部变量
- `runModalForWindow_` 返回后、 `panel.release()` 之前读取结果
- handler 类变得极简，只负责结束模态，不再处理业务逻辑

## v1.4.1 (2026-06-10)

### 修复
- **预设按钮改为复选框**：v1.4.0 错误地将复选框改成了普通按钮，点击即记录导致闪退；恢复为 `NSButtonTypeSwitch` 复选框，勾选后需点「记录」统一提交
- 修复点击第一个预设按钮闪退问题（原因为 push button 的 `presetClicked:` action 在 handler 中未正确处理）

### 变更
- 复选框 + 自定义输入可同时使用，点「记录」统一提交
- handler 从 `_SimplePanelHandler` 重构，支持 `setup(checkboxes, input_field, result_list)` 接收复选框列表

## v1.4.0 (2026-06-10) [已撤回]

### 变更（有缺陷，v1.4.1 修复）
- 错误地将预设复选框改为普通按钮，导致交互不符合预期且存在闪退问题
- 此版本不应使用，请直接使用 v1.4.1

## v1.3.1 (2026-06-10)

### 修复
- **闪退问题**：修复 `_try_panel_dialog` 中 `clear_btn` 引用顺序错误（`cb.clear_btn = clear_btn` 在 `clear_btn` 定义之前），导致 `NameError` 闪退
- **「+ 添加」按钮无响应**：原来用普通 Python 函数作为 ObjC `action`，PyObjC 无法自动注册为 ObjC 消息，按钮点击无任何反应；改为在模块顶层定义 `_PanelButtonHandler(NSObject)` 子类，用 `addTask_` / `clearTasks_` 方法正确注册为 ObjC selector，`setup()` 方法用 `@objc.python_method` 标记以传递 Python 对象引用

### 技术改进
- ObjC handler 类改为模块级定义（只注册一次），每次弹窗时复用，避免运行时重复创建 ObjC 类导致崩溃
- `_try_panel_dialog` 中移除重复的 `import objc`（已在模块顶层导入）



### 新增
- **全新界面布局**：简洁面板，预设复选框 + 单独的自定义任务输入区
- **「+ 添加」按钮**：输入任务名点击添加，支持多次添加多个自定义任务
- **已添加任务展示**：实时显示已添加的自定义任务列表
- **「清除」按钮**：一键清除所有自定义任务
- 输入完成后焦点自动回到输入框，方便连续添加

### 变更
- 界面宽度固定 420px，视觉更紧凑
- 按钮文案改为「记录」「取消」

### 修复
- 修复双弹窗残留问题（面板销毁在回退之前）

### 修复
- **双弹窗问题**：NSPanel 失败时面板未销毁直接回退，导致两个窗口同时出现。改为 `_try_panel_dialog` 模式——面板销毁后再触发回退
- 回退逻辑优化：即使面板中途出错，也确保 `orderOut_` + `release` 被调用，不留残留窗口
- checkbox 状态读取加容错，单个按钮失败不影响整体

### 修复
- **`ok_btn.tag = 1` 报 `read-only` 错误**：PyObjC 中 NSButton 的 `tag` 是只读属性，需用 `setTag_()` 方法
- **回退通知也崩溃**：`rumps.notification` 在非打包环境下（直接跑 Python 脚本时）因缺少 Info.plist 也会报错，改为 `stderr` 打印

### 修复
- **修复打包后无弹窗问题**：NSPanel 改用 `NSButtonTypeSwitch` / `NSBezelStyleRounded` 等新 API 常量名
- 增加 `AppKit`、`Foundation`、`objc` 到 py2app 的显式 includes，确保打包时模块完整
- `_show_recording_dialog` 增加 try/except，NSPanel 出错时自动回退到文本输入模式
- 回退方案同样支持逗号分隔多活动记录
- 分离为 `_show_panel_dialog`（原生面板）和 `_show_fallback_dialog`（rumps.Window）两个方法

## v1.2.0 (2026-06-10)

### 新增
- 全新弹窗界面——使用原生 Cocoa 面板（NSPanel），告别文字输入框
- 预设选项改为**复选框按钮**，点击即可勾选，支持多选
- 自定义输入支持**逗号分隔多条活动**，一次记录多个事情
- 每条活动自动截断至最多 20 字
- 记录后系统通知显示本次记录的活动列表（最多展示 3 项）

### 变更
- 弹窗面板自适应高度，根据预设数量自动调整布局
- 弹窗界面文字提示更清晰，带灰色提示文本

## v1.1.0 (2026-06-10)

### 新增
- 记录间隔新增 1min / 2min 选项，方便测试验证
- 空闲阈值新增「关闭（始终弹窗）」选项，跳过空闲检测
- 🧪 测试菜单：重置计时器（下次 tick 立即弹窗）/ 清空全部记录

### 变更
- 默认记录间隔从 45 分钟改为 5 分钟，降低首次使用门槛

## v1.0.0 (2026-06-10)

🎉 首次发布

### 功能
- macOS 菜单栏应用，无 Dock 图标
- 每 N 分钟（可配置）自动弹窗询问当前活动
- 检测电脑是否在使用中，空闲时自动跳过
- 预设活动选项（写代码/开会/阅读/学习/思考/摸鱼），支持自定义
- 可通过输入预设编号快速选择
- 今日活动汇总
- 本周活动汇总（周一至周日）
- 全部历史记录查看
- 手动"立即记录"按钮
- 设置持久化（重启后保留）
- 检查 GitHub 更新
