"""
setup.py - py2app 打包配置
用法: python3 setup.py py2app
"""

from setuptools import setup

APP = ["time_recorder.py"]
DATA_FILES = []
OPTIONS = {
    "argv_emulation": False,
    "iconfile": "icon.icns",
    "plist": {
        "CFBundleName": "时间记录器",
        "CFBundleDisplayName": "⏰ 时间记录器",
        "CFBundleIdentifier": "com.timerecorder.app",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
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
