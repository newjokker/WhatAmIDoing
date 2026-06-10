SHELL   := /bin/bash
# 必须使用 ARM64 原生 Python
PYTHON  := /Users/jokkerling/.workbuddy/binaries/python/versions/3.13.12/bin/python3
PYTHON_ENV := /Users/jokkerling/.workbuddy/binaries/python/envs/default
NAME    := 时间记录器
VERSION := $(shell grep '__version__' time_recorder.py | head -1 | sed "s/.*= \"//;s/\".*//")
.DEFAULT_GOAL := help

# 构建前检查架构
define check_arch
	@ARCH=$$($(PYTHON) -c 'import platform; print(platform.machine())'); \
	if [ "$$ARCH" != "arm64" ]; then \
		echo "❌ 错误: Python 架构为 $$ARCH，必须是 arm64"; \
		echo "   当前 Python: $(PYTHON)"; \
		exit 1; \
	fi
endef

.PHONY: help app dmg clean release tag

help: ## 显示帮助信息
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## 安装依赖
	$(PYTHON_ENV)/bin/pip install rumps py2app

codesign: ## 修复签名（首次构建/重装依赖后执行）
	codesign -f -s - $(PYTHON)
	find $(PYTHON_ENV)/lib/python3.13/site-packages -name "*.so" | xargs codesign -f -s -

icon: ## 生成应用图标
	$(PYTHON_ENV)/bin/python make_icon.py

app: clean icon ## 构建 .app
	$(check_arch)
	$(PYTHON_ENV)/bin/python setup.py py2app
	@echo "✅ 构建完成: dist/$(NAME).app"

dmg: app ## 构建 DMG 安装包
	@echo "创建 DMG..."
	hdiutil create -size 200m -fs HFS+ -type UDIF -volname "$(NAME)" /tmp/timerecorder_template.dmg
	hdiutil attach -nobrowse -mountpoint /tmp/timerecorder_mount /tmp/timerecorder_template.dmg
	ditto "dist/$(NAME).app" "/tmp/timerecorder_mount/$(NAME).app"
	ln -sf /Applications "/tmp/timerecorder_mount/Applications"
	cp icon.icns "/tmp/timerecorder_mount/.VolumeIcon.icns"
	/usr/bin/SetFile -a C "/tmp/timerecorder_mount"
	hdiutil detach "/tmp/timerecorder_mount"
	rm -rf /tmp/timerecorder_mount
	hdiutil convert /tmp/timerecorder_template.dmg -format UDZO -ov -o "$(NAME).dmg"
	rm -f /tmp/timerecorder_template.dmg
	@echo "✅ DMG 已生成: $(NAME).dmg"
	@mkdir -p releases
	@mv "$(NAME).dmg" "releases/TimeRecorder-v$(VERSION).dmg"
	@echo "✅ 已移动到: releases/TimeRecorder-v$(VERSION).dmg"

release: tag dmg ## 发布新版本（打标签 + 构建 DMG）
	@echo "✅ Release v$(VERSION) 就绪！"
	@echo "   DMG: releases/TimeRecorder-v$(VERSION).dmg"
	@echo "   在 GitHub 上创建 Release："
	@echo "   1. git push --tags"
	@echo "   2. gh release create v$(VERSION) releases/TimeRecorder-v$(VERSION).dmg --title 'v$(VERSION)' --notes-file CHANGELOG.md"

tag: ## 打 Git 版本标签
	@if git rev-parse v$(VERSION) >/dev/null 2>&1; then \
		echo "⚠️  标签 v$(VERSION) 已存在"; \
	else \
		git tag -a v$(VERSION) -m "Release v$(VERSION)"; \
		echo "✅ 标签 v$(VERSION) 已创建"; \
	fi

clean: ## 清理构建产物（保留 releases/ 中的历史版本）
	rm -rf build dist *.egg-info __pycache__/
	rm -rf clock.iconset
	@echo '✅ 清理完成（releases/ 已保留）'
