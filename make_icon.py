"""生成时间记录器应用图标 (icns)，无需 PIL"""
import struct
import zlib
import os
import subprocess as sp
import math


def _create_png_raw(width, height):
    """Create an activity timeline icon PNG as bytes."""
    def clamp(v, lo=0.0, hi=1.0):
        return max(lo, min(hi, v))

    def smoothstep(edge0, edge1, x):
        if edge0 == edge1:
            return 1.0 if x >= edge1 else 0.0
        t = clamp((x - edge0) / (edge1 - edge0))
        return t * t * (3 - 2 * t)

    def rounded_rect_alpha(x, y, cx, cy, w, h, r, aa):
        qx = abs(x - cx) - w / 2 + r
        qy = abs(y - cy) - h / 2 + r
        outside_x = max(qx, 0)
        outside_y = max(qy, 0)
        outside = math.sqrt(outside_x * outside_x + outside_y * outside_y)
        inside = min(max(qx, qy), 0)
        dist = outside + inside - r
        return 1 - smoothstep(-aa, aa, dist)

    def circle_alpha(x, y, cx, cy, radius, aa):
        dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2) - radius
        return 1 - smoothstep(-aa, aa, dist)

    def ring_alpha(x, y, cx, cy, radius, thickness, aa):
        dist = abs(math.sqrt((x - cx) ** 2 + (y - cy) ** 2) - radius) - thickness / 2
        return 1 - smoothstep(-aa, aa, dist)

    def line_alpha(x, y, x1, y1, x2, y2, thickness, aa):
        vx, vy = x2 - x1, y2 - y1
        wx, wy = x - x1, y - y1
        length2 = vx * vx + vy * vy
        t = 0 if length2 == 0 else clamp((wx * vx + wy * vy) / length2)
        px, py = x1 + t * vx, y1 + t * vy
        dist = math.sqrt((x - px) ** 2 + (y - py) ** 2) - thickness / 2
        return 1 - smoothstep(-aa, aa, dist)

    def over(dst, src, alpha):
        alpha = clamp(alpha)
        if alpha <= 0:
            return dst
        sr, sg, sb, sa = src
        dr, dg, db, da = dst
        a = alpha * (sa / 255)
        out_a = a + da * (1 - a)
        if out_a <= 0:
            return (0, 0, 0, 0)
        out_r = (sr * a + dr * da * (1 - a)) / out_a
        out_g = (sg * a + dg * da * (1 - a)) / out_a
        out_b = (sb * a + db * da * (1 - a)) / out_a
        return (out_r, out_g, out_b, out_a)

    pixels = []
    aa = max(1.0, width / 180)
    scale = min(width, height)

    for y in range(height):
        row = bytearray()
        for x in range(width):
            nx = x / width
            ny = y / height
            color = (0, 0, 0, 0)

            bg_a = rounded_rect_alpha(x, y, width / 2, height / 2, scale * 0.88, scale * 0.88, scale * 0.20, aa)
            bg_top = (18, 83, 124, 255)
            bg_bottom = (15, 132, 205, 255)
            bg_mix = ny
            bg = (
                bg_top[0] * (1 - bg_mix) + bg_bottom[0] * bg_mix,
                bg_top[1] * (1 - bg_mix) + bg_bottom[1] * bg_mix,
                bg_top[2] * (1 - bg_mix) + bg_bottom[2] * bg_mix,
                255,
            )
            color = over(color, bg, bg_a)

            glow_a = circle_alpha(x, y, width * 0.28, height * 0.20, scale * 0.33, aa * 3) * 0.22
            color = over(color, (113, 214, 255, 255), glow_a * bg_a)

            card_shadow = rounded_rect_alpha(x, y, width * 0.52, height * 0.55 + scale * 0.018, scale * 0.56, scale * 0.60, scale * 0.065, aa)
            color = over(color, (4, 36, 62, 255), card_shadow * 0.28)

            card_a = rounded_rect_alpha(x, y, width * 0.50, height * 0.54, scale * 0.56, scale * 0.60, scale * 0.065, aa)
            color = over(color, (249, 252, 248, 255), card_a)

            header_a = rounded_rect_alpha(x, y, width * 0.50, height * 0.29, scale * 0.46, scale * 0.105, scale * 0.032, aa)
            color = over(color, (225, 241, 236, 255), header_a * card_a)

            spine_a = line_alpha(x, y, width * 0.34, height * 0.39, width * 0.34, height * 0.75, scale * 0.018, aa)
            color = over(color, (110, 132, 145, 255), spine_a * card_a)

            items = [
                (0.42, (255, 184, 77, 255), 0.44),
                (0.55, (61, 194, 154, 255), 0.53),
                (0.68, (255, 118, 102, 255), 0.47),
            ]
            for item_y, dot_color, line_w in items:
                dot_outer = circle_alpha(x, y, width * 0.34, height * item_y, scale * 0.047, aa)
                dot_inner = circle_alpha(x, y, width * 0.34, height * item_y, scale * 0.028, aa)
                color = over(color, (255, 255, 255, 255), dot_outer * card_a)
                color = over(color, dot_color, dot_inner * card_a)

                task_a = rounded_rect_alpha(
                    x, y, width * (0.51 + line_w * 0.02), height * item_y,
                    scale * line_w, scale * 0.050, scale * 0.025, aa,
                )
                color = over(color, (206, 218, 222, 255), task_a * card_a)

                fill_a = rounded_rect_alpha(
                    x, y, width * (0.43 + line_w * 0.015), height * item_y,
                    scale * (line_w * 0.55), scale * 0.050, scale * 0.025, aa,
                )
                color = over(color, dot_color, fill_a * 0.95 * card_a)

            clock_cx, clock_cy = width * 0.70, height * 0.31
            clock_shadow = circle_alpha(x, y, clock_cx + scale * 0.014, clock_cy + scale * 0.016, scale * 0.135, aa)
            color = over(color, (4, 36, 62, 255), clock_shadow * 0.20)
            clock_face = circle_alpha(x, y, clock_cx, clock_cy, scale * 0.135, aa)
            color = over(color, (255, 255, 255, 255), clock_face)
            clock_ring = ring_alpha(x, y, clock_cx, clock_cy, scale * 0.117, scale * 0.018, aa)
            color = over(color, (25, 91, 132, 255), clock_ring)
            hour = line_alpha(x, y, clock_cx, clock_cy, clock_cx, clock_cy - scale * 0.060, scale * 0.016, aa)
            minute = line_alpha(x, y, clock_cx, clock_cy, clock_cx + scale * 0.055, clock_cy + scale * 0.032, scale * 0.016, aa)
            color = over(color, (25, 91, 132, 255), hour * clock_face)
            color = over(color, (25, 91, 132, 255), minute * clock_face)
            color = over(color, (255, 118, 102, 255), circle_alpha(x, y, clock_cx, clock_cy, scale * 0.018, aa))

            shine = line_alpha(x, y, width * 0.25, height * 0.19, width * 0.70, height * 0.10, scale * 0.014, aa)
            color = over(color, (255, 255, 255, 255), shine * 0.16 * bg_a)

            r, g, b, a = color
            row.extend([int(clamp(r, 0, 255)), int(clamp(g, 0, 255)), int(clamp(b, 0, 255)), int(clamp(a, 0, 255))])
        pixels.append(b'\x00' + bytes(row))

    raw = b''.join(pixels)

    def chunk(c_type, data):
        c = c_type + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', ihdr)
        + chunk(b'IDAT', zlib.compress(raw))
        + chunk(b'IEND', b'')
    )


def _write_icns_from_iconset(iconset, icns_path):
    """Write a modern ICNS file directly from PNG iconset entries."""
    entries = [
        (b'icp4', 'icon_16x16.png'),
        (b'icp5', 'icon_32x32.png'),
        (b'icp6', 'icon_32x32@2x.png'),
        (b'ic07', 'icon_128x128.png'),
        (b'ic08', 'icon_256x256.png'),
        (b'ic09', 'icon_512x512.png'),
        (b'ic10', 'icon_512x512@2x.png'),
    ]
    chunks = []
    for code, filename in entries:
        path = os.path.join(iconset, filename)
        with open(path, 'rb') as f:
            data = f.read()
        chunks.append(code + struct.pack('>I', len(data) + 8) + data)

    body = b''.join(chunks)
    with open(icns_path, 'wb') as f:
        f.write(b'icns' + struct.pack('>I', len(body) + 8) + body)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
iconset = os.path.join(SCRIPT_DIR, 'clock.iconset')
os.makedirs(iconset, exist_ok=True)

master_png = os.path.join(iconset, 'master.png')
with open(master_png, 'wb') as f:
    f.write(_create_png_raw(512, 512))

env = dict(os.environ)
env['COPYFILE_DISABLE'] = '1'

icon_sizes = [16, 32, 128, 256, 512]
for s in icon_sizes:
    path = os.path.join(iconset, f'icon_{s}x{s}.png')
    sp.run(['sips', '-z', str(s), str(s), master_png, '--out', path], check=True, env=env, stdout=sp.DEVNULL)

    path2 = os.path.join(iconset, f'icon_{s}x{s}@2x.png')
    sp.run(['sips', '-z', str(s * 2), str(s * 2), master_png, '--out', path2], check=True, env=env, stdout=sp.DEVNULL)

os.remove(master_png)

# Convert to .icns. Prefer iconutil when available; fall back to a direct writer
# because some command-line environments reject otherwise valid iconsets.
icns_path = os.path.join(SCRIPT_DIR, 'icon.icns')
for name in os.listdir(iconset):
    if name.startswith('._'):
        os.remove(os.path.join(iconset, name))

try:
    sp.run(['iconutil', '-c', 'icns', iconset, '-o', icns_path], check=True, env=env)
except sp.CalledProcessError:
    _write_icns_from_iconset(iconset, icns_path)

print(f'✅ 图标已生成: {icns_path}')
