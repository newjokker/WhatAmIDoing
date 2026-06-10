"""生成时间记录器应用图标 (icns)，无需 PIL"""
import struct
import zlib
import os
import subprocess as sp
import math


def _create_png_raw(width, height):
    """Create a simple clock icon PNG as bytes."""
    pixels = []
    cx, cy = width / 2, height / 2
    radius = min(width, height) * 0.42
    inner_radius = radius * 0.88
    for y in range(height):
        row = bytearray()
        for x in range(width):
            dx = (x - cx) / radius
            dy = (y - cy) / radius
            dist = math.sqrt(dx * dx + dy * dy)

            # Clock face (circle)
            in_face = dist < 1.0

            # Inner face (lighter)
            in_inner = dist < inner_radius / radius

            # Hour hand
            hx, hy = dx * 0.55 - 0.02, dy * 0.55 - 0.02
            angle_h = math.atan2(hy - 0.12, hx)
            dist_h = math.sqrt((hx) ** 2 + (hy - 0.12) ** 2)
            in_hour_hand = dist_h < 0.08 and abs(angle_h - (-math.pi / 2)) < 0.35 and in_face

            # Minute hand
            mx, my = dx * 0.75 - 0.02, dy * 0.75 - 0.02
            angle_m = math.atan2(my + 0.05, mx - 0.05)
            dist_m = math.sqrt((mx - 0.05) ** 2 + (my + 0.05) ** 2)
            in_minute_hand = dist_m < 0.06 and abs(angle_m - (-math.pi / 2 + 0.3)) < 0.3 and in_face

            # Center dot
            in_center = dist < 0.08

            # Tick marks (12, 3, 6, 9)
            tick_dist = abs(dist - 0.92) < 0.04
            tick_angle = math.atan2(dy, dx)
            is_tick = False
            if tick_dist:
                for tick_angle_target in [0, math.pi / 2, math.pi, 3 * math.pi / 2]:
                    if abs(tick_angle - tick_angle_target) < 0.15:
                        is_tick = True
                        break

            if in_center:
                r, g, b, a = 60, 60, 60, 255
            elif in_hour_hand or in_minute_hand:
                r, g, b, a = 50, 50, 50, 255
            elif is_tick:
                r, g, b, a = 80, 80, 80, 255
            elif in_inner:
                r, g, b, a = 255, 255, 255, 255
            elif in_face:
                r, g, b, a = 220, 220, 230, 255
            else:
                r, g, b, a = 0, 0, 0, 0

            row.extend([r, g, b, a])
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


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
iconset = os.path.join(SCRIPT_DIR, 'clock.iconset')
os.makedirs(iconset, exist_ok=True)

sizes = [16, 32, 64, 128, 256, 512]
for s in sizes:
    data = _create_png_raw(s, s)
    path = os.path.join(iconset, f'icon_{s}x{s}.png')
    with open(path, 'wb') as f:
        f.write(data)
    if s <= 128:
        path2 = os.path.join(iconset, f'icon_{s}x{s}@2x.png')
        with open(path2, 'wb') as f:
            f.write(_create_png_raw(s * 2, s * 2))

# Convert to .icns using iconutil
icns_path = os.path.join(SCRIPT_DIR, 'icon.icns')
sp.run(['iconutil', '-c', 'icns', iconset, '-o', icns_path], check=True)
print(f'✅ 图标已生成: {icns_path}')
