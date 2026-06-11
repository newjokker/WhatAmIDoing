#!/usr/bin/env python3
"""Convert a PNG image into a macOS .icns app icon.

Usage:
    python3 png_to_icns.py input.png
    python3 png_to_icns.py input.png -o icon.icns
    python3 png_to_icns.py input.png -o icon.icns --keep-iconset

Requires macOS command-line tools because it uses `sips` for resizing.
It tries `iconutil` first, then falls back to writing a PNG-backed ICNS file.
"""

import argparse
import os
import shutil
import struct
import subprocess as sp
import sys
import tempfile
from pathlib import Path


# macOS iconset standard file set. The @2x entries intentionally duplicate
# some pixel sizes because Finder uses the filename scale metadata.
ICONSET_ENTRIES = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]

# ICNS chunks are keyed by pixel size, not filename scale, so the direct writer
# stores one representative for each unique modern PNG-backed icon size.
ICNS_CHUNK_ENTRIES = [
    ("icon_16x16.png", b"icp4"),
    ("icon_32x32.png", b"icp5"),
    ("icon_32x32@2x.png", b"icp6"),
    ("icon_128x128.png", b"ic07"),
    ("icon_256x256.png", b"ic08"),
    ("icon_512x512.png", b"ic09"),
    ("icon_512x512@2x.png", b"ic10"),
]


def run(cmd):
    sp.run(cmd, check=True, stdout=sp.DEVNULL, stderr=sp.PIPE)


def assert_png(path):
    if not path.exists():
        raise FileNotFoundError(f"找不到输入文件: {path}")
    if path.suffix.lower() != ".png":
        raise ValueError("输入文件必须是 .png")
    with path.open("rb") as f:
        if f.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ValueError("输入文件不是有效 PNG")


def make_iconset(input_png, iconset_dir):
    iconset_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["COPYFILE_DISABLE"] = "1"

    for size, filename in ICONSET_ENTRIES:
        output = iconset_dir / filename
        sp.run(
            ["sips", "-z", str(size), str(size), str(input_png), "--out", str(output)],
            check=True,
            env=env,
            stdout=sp.DEVNULL,
            stderr=sp.PIPE,
        )
    validate_iconset(iconset_dir)


def validate_iconset(iconset_dir):
    missing = [filename for _size, filename in ICONSET_ENTRIES if not (iconset_dir / filename).exists()]
    if missing:
        raise RuntimeError(f"iconset 缺少文件: {', '.join(missing)}")


def write_icns_from_iconset(iconset_dir, output_icns):
    """Write a PNG-backed ICNS file directly from the iconset entries."""
    chunks = []
    for filename, code in ICNS_CHUNK_ENTRIES:
        data = (iconset_dir / filename).read_bytes()
        chunks.append(code + struct.pack(">I", len(data) + 8) + data)

    body = b"".join(chunks)
    output_icns.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)


def convert_png_to_icns(input_png, output_icns, keep_iconset=False):
    assert_png(input_png)
    output_icns.parent.mkdir(parents=True, exist_ok=True)

    if keep_iconset:
        iconset_dir = output_icns.with_suffix(".iconset")
        if iconset_dir.exists():
            shutil.rmtree(iconset_dir)
        cleanup_dir = None
    else:
        cleanup_dir = tempfile.TemporaryDirectory(prefix="png_to_icns_")
        iconset_dir = Path(cleanup_dir.name) / "AppIcon.iconset"

    try:
        make_iconset(input_png, iconset_dir)
        env = dict(os.environ)
        env["COPYFILE_DISABLE"] = "1"
        try:
            sp.run(
                ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(output_icns)],
                check=True,
                env=env,
                stdout=sp.DEVNULL,
                stderr=sp.PIPE,
            )
        except (FileNotFoundError, sp.CalledProcessError):
            write_icns_from_iconset(iconset_dir, output_icns)
    finally:
        if cleanup_dir is not None:
            cleanup_dir.cleanup()

    return output_icns


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Convert a PNG image into a macOS .icns app icon.")
    parser.add_argument("png", type=Path, help="输入 PNG 图片路径，建议至少 1024x1024")
    parser.add_argument("-o", "--output", type=Path, help="输出 .icns 路径，默认与输入同名")
    parser.add_argument("--keep-iconset", action="store_true", help="保留生成的 .iconset 文件夹")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    input_png = args.png.resolve()
    output_icns = (args.output or input_png.with_suffix(".icns")).resolve()

    try:
        path = convert_png_to_icns(input_png, output_icns, args.keep_iconset)
    except Exception as exc:
        print(f"❌ 生成失败: {exc}", file=sys.stderr)
        return 1

    print(f"✅ App 图标已生成: {path}")
    return 0


if __name__ == "__main__":
    
    # 使用方法
    # python3 png_to_icns.py your-image.png -o icon.icns --keep-iconset
    
    raise SystemExit(main())
