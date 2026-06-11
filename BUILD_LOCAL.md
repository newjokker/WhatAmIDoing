# 本机构建指南 (BUILD_LOCAL.md)

> 适用于当前 macOS 机器（Apple Silicon / ARM64）。

## 环境概述

| 项目 | 值 |
|------|-----|
| 构建用 Python | Managed Python 3.13.12（arm64） |
| Python 路径 | `/Users/jokkerling/.workbuddy/binaries/python/versions/3.13.12/bin/python3` |
| 虚拟环境（site-packages） | `/Users/jokkerling/.workbuddy/binaries/python/envs/default/` |
| pip 路径 | `/Users/jokkerling/.workbuddy/binaries/python/envs/default/bin/pip` |
| 依赖 | rumps, py2app |
| 构建产物 | `dist/干啥来着.app`（arm64 原生） |
| DMG 产物 | `releases/WhatAmIDoing-v{VERSION}.dmg` |

## 一次性环境准备

### 1. 安装依赖

```bash
/Users/jokkerling/.workbuddy/binaries/python/envs/default/bin/pip install rumps py2app
```

### 2. 修复签名

```bash
# 重签 Python 解释器
codesign -f -s - /Users/jokkerling/.workbuddy/binaries/python/versions/3.13.12/bin/python3

# 重签所有 .so
find /Users/jokkerling/.workbuddy/binaries/python/envs/default/lib/python3.13/site-packages -name "*.so" | xargs codesign -f -s -

# 验证
/Users/jokkerling/.workbuddy/binaries/python/envs/default/bin/python -c "import rumps; print('rumps OK')"
# 必须输出: rumps OK
```

### 3. 修复 py2app 的 zlib.__file__ bug（Python 3.13+）

Python 3.13 移除了 `zlib.__file__` 属性，py2app 0.28.10 构建时崩溃。
需要打补丁到 `py2app/build_app.py`。

```bash
PY2APP_BUILD=/Users/jokkerling/.workbuddy/binaries/python/envs/default/lib/python3.13/site-packages/py2app/build_app.py
```

找到约 2440 行，将：

```python
        self.copy_file(arcname, arcdir)
        if sys.version_info[0] != 2:
            import zlib

            self.copy_file(zlib.__file__, os.path.dirname(arcdir))
```

替换为：

```python
        self.copy_file(arcname, arcdir)
        if sys.version_info[0] != 2:
            import zlib

            if hasattr(zlib, '__file__') and zlib.__file__ is not None:
                self.copy_file(zlib.__file__, os.path.dirname(arcdir))
```

## 每次构建步骤

### 前置检查

```bash
# 1. 确认 Python 是 arm64
/Users/jokkerling/.workbuddy/binaries/python/envs/default/bin/python -c "import platform; print(platform.machine())"
# 必须输出: arm64

# 2. 确认 rumps 能正常导入
/Users/jokkerling/.workbuddy/binaries/python/envs/default/bin/python -c "import rumps; print('rumps OK')"
# 必须输出: rumps OK

# 3. 确认 py2app zlib 补丁已打
grep -c "hasattr(zlib" /Users/jokkerling/.workbuddy/binaries/python/envs/default/lib/python3.13/site-packages/py2app/build_app.py
# 必须输出: 1
```

### 构建 .app

```bash
cd /Volumes/Jokker/Code/干啥来着
rm -rf build dist
/Users/jokkerling/.workbuddy/binaries/python/envs/default/bin/python make_icon.py
/Users/jokkerling/.workbuddy/binaries/python/envs/default/bin/python setup.py py2app
```

### 验证构建产物

```bash
file dist/干啥来着.app/Contents/MacOS/time_recorder
# 必须输出: Mach-O 64-bit executable arm64
```

### 打包 DMG

```bash
make dmg
```

## 完整一键构建

```bash
cd /Volumes/Jokker/Code/干啥来着
rm -rf build dist

/Users/jokkerling/.workbuddy/binaries/python/envs/default/bin/python make_icon.py
/Users/jokkerling/.workbuddy/binaries/python/envs/default/bin/python setup.py py2app

# 验证
file dist/干啥来着.app/Contents/MacOS/time_recorder

# 打包 DMG
make dmg
```

## 排障速查

| 现象 | 原因 | 解决 |
|------|------|------|
| `No module named 'rumps'` | 依赖未安装 | `pip install rumps py2app` |
| `code signature ... different Team IDs` | 签名不匹配 | `codesign -f -s -` 重签 |
| `AttributeError: module 'zlib' has no attribute '__file__'` | py2app 补丁丢失 | 重新打补丁 |
| `Python 架构为 x86_64` | 用错了 Python | 确认使用 managed Python 3.13 |
| 构建 App 被 Gatekeeper 阻止 | 未签名 App | `xattr -cr dist/干啥来着.app` |
