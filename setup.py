"""
setup.py - py2app 打包配置
用法: python3 setup.py py2app
"""

from setuptools import setup

APP = ["time_recorder.py"]
DATA_FILES = []
VERSION = "1.4.15"
OPTIONS = {
    "argv_emulation": False,
    "iconfile": "icon.icns",
    "plist": {
        "CFBundleName": "干啥来着",
        "CFBundleDisplayName": "⏰ 干啥来着",
        "CFBundleIdentifier": "com.timerecorder.app",
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "CFBundleExecutable": "time_recorder",
        "CFBundleDevelopmentRegion": "zh_CN",
        "NSHumanReadableCopyright": "Copyright © 2026. All rights reserved.",
        "LSUIElement": True,  # 无 Dock 图标，仅菜单栏
    },
    "packages": ["rumps"],
    "frameworks": ["/opt/miniconda3/lib/libffi.8.dylib"],
    "includes": ["ctypes", "AppKit", "Foundation", "objc"],
    "dylib_excludes": [],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
