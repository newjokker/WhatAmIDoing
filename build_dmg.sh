#!/bin/bash
# build_dmg.sh — 构建时间记录器 DMG 并移动到 releases 目录
# 用法: ./build_dmg.sh
#
# 流程：
#   1. 从 time_recorder.py 读取版本号
#   2. 在可写临时目录中构建 .app（避免外接磁盘权限问题）
#   3. 打包为 DMG
#   4. 复制到项目 releases/ 目录（历史版本不删除）

set -euo pipefail

# ── 配置 ──
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="/Users/jokkerling/.workbuddy/binaries/python/envs/default/bin/python"
APP_NAME="时间记录器"

# ── 读取版本号 ──
VERSION=$(grep '__version__' "$SCRIPT_DIR/time_recorder.py" | head -1 | sed 's/.*= "//;s/".*//')
DMG_NAME="WhatAmIDoing-v${VERSION}.dmg"

echo "📦 构建 $APP_NAME v$VERSION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 检查 Python 架构 ──
ARCH=$($PYTHON -c 'import platform; print(platform.machine())')
if [ "$ARCH" != "arm64" ]; then
    echo "❌ Python 架构为 $ARCH，必须是 arm64"
    exit 1
fi
echo "✅ Python 架构: $ARCH"

# ── 准备临时构建目录 ──
BUILD_DIR=$(mktemp -d "/tmp/timerecorder_build_XXXXXX")
echo "📂 构建目录: $BUILD_DIR"

cleanup() {
    echo "🧹 清理临时目录..."
    rm -rf "$BUILD_DIR"
    hdiutil detach /tmp/timerecorder_mount -force 2>/dev/null || true
    rm -f /tmp/timerecorder_template.dmg
}
trap cleanup EXIT

# ── 复制源文件到临时目录 ──
echo "📋 复制项目文件..."
cp "$SCRIPT_DIR/time_recorder.py" "$BUILD_DIR/"
cp "$SCRIPT_DIR/setup.py" "$BUILD_DIR/"
cp "$SCRIPT_DIR/pyproject.toml" "$BUILD_DIR/"
cp "$SCRIPT_DIR/icon.icns" "$BUILD_DIR/"
cp "$SCRIPT_DIR/make_icon.py" "$BUILD_DIR/"

# ── 生成图标 ──
echo "🎨 生成图标..."
cd "$BUILD_DIR"
$PYTHON make_icon.py

# ── 构建 .app ──
echo "🔨 构建 .app（py2app）..."
$PYTHON setup.py py2app 2>&1 | tail -5

if [ ! -d "$BUILD_DIR/dist/$APP_NAME.app" ]; then
    echo "❌ .app 构建失败"
    exit 1
fi
echo "✅ .app 构建成功"

# ── 创建 DMG ──
echo "💿 创建 DMG..."
hdiutil create -size 200m -fs HFS+ -type UDIF -volname "$APP_NAME" /tmp/timerecorder_template.dmg
hdiutil attach -nobrowse -mountpoint /tmp/timerecorder_mount /tmp/timerecorder_template.dmg

echo "📦 打包 .app 到 DMG..."
ditto "$BUILD_DIR/dist/$APP_NAME.app" "/tmp/timerecorder_mount/$APP_NAME.app"
ln -sf /Applications "/tmp/timerecorder_mount/Applications"
cp "$BUILD_DIR/icon.icns" "/tmp/timerecorder_mount/.VolumeIcon.icns" 2>/dev/null || true
/usr/bin/SetFile -a C "/tmp/timerecorder_mount"

hdiutil detach /tmp/timerecorder_mount
echo "🗜️  压缩 DMG..."
hdiutil convert /tmp/timerecorder_template.dmg -format UDZO -ov -o "$BUILD_DIR/$APP_NAME.dmg"
rm -f /tmp/timerecorder_template.dmg

DMG_SIZE=$(du -h "$BUILD_DIR/$APP_NAME.dmg" | cut -f1)
echo "✅ DMG 生成成功 ($DMG_SIZE)"

# ── 移动到 releases 目录 ──
mkdir -p "$SCRIPT_DIR/releases"
TARGET="$SCRIPT_DIR/releases/$DMG_NAME"

if [ -f "$TARGET" ]; then
    echo "⚠️  $DMG_NAME 已存在，覆盖..."
    rm -f "$TARGET"
fi

cp "$BUILD_DIR/$APP_NAME.dmg" "$TARGET"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 完成！DMG 已保存到: releases/$DMG_NAME"
echo ""
echo "📁 releases 目录内容："
ls -lh "$SCRIPT_DIR/releases/"
