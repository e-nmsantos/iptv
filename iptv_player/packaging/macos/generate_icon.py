"""Generate an .app icon for IPTV Player (macOS .icns).

Run ON macOS AFTER installing Pillow:
    pip install Pillow
    python packaging/macos/generate_icon.py

This creates iconset/ and converts it to icon.icns using iconutil (built-in on macOS).
"""

import struct
import zlib
import os
import subprocess
import tempfile
import shutil

ICON_SIZES = [
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

HERE = os.path.dirname(os.path.abspath(__file__))
ICONSET_DIR = os.path.join(HERE, "IPTV.iconset")
OUTPUT_ICNS = os.path.join(HERE, "icon.icns")


def _write_png(path: str, width: int, height: int, pixels: bytes):
    """Write a minimal PNG to *path*."""
    # Raw image data (RGBA, no filter)
    raw = b""
    for y in range(height):
        raw += b"\x00"  # filter byte = None
        raw += pixels[y * width * 4 : (y + 1) * width * 4]

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    idat = zlib.compress(raw)

    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", ihdr)
    png += _chunk(b"IDAT", idat)
    png += _chunk(b"IEND", b"")

    with open(path, "wb") as f:
        f.write(png)


def _generate_icon_pixels(size: int):
    """Generate RGBA pixel data for the IPTV Player icon.

    Design: rounded rectangle with purple gradient background and a white
    play-triangle.
    """
    pixels = bytearray(size * size * 4)
    cx = cy = size / 2
    radius = size * 0.22
    inner = size * 0.28  # play-triangle inset

    for y in range(size):
        for x in range(size):
            i = (y * size + x) * 4
            # Distance from centre
            dx, dy = abs(x - cx), abs(y - cy)
            # Rounded rectangle test
            rx, ry = max(0, dx - cx + radius), max(0, dy - cy + radius)
            inside = (rx * rx + ry * ry) <= (radius * radius)

            if inside:
                # Purple gradient
                t = (x + y) / (size * 2)
                r = int(98 + t * 40)
                g = int(0 + t * 30)
                b = int(238 - t * 30)
                pixels[i] = r
                pixels[i + 1] = g
                pixels[i + 2] = b
                pixels[i + 3] = 255

                # Play triangle (white)
                # Map to normalized coords: (-1..1)
                nx = (x - cx) / cx
                ny = (y - cy) / cy
                # Triangle pointing right
                if nx >= -0.6 and ny >= -0.55 and ny <= 0.55:
                    # Edge: right edge of triangle
                    edge_x = 0.6
                    left_edge = -0.3 + (0.9 / 1.1) * abs(ny)  # slant
                    if left_edge <= nx <= edge_x:
                        pixels[i] = 255
                        pixels[i + 1] = 255
                        pixels[i + 2] = 255
            else:
                # Transparent outside
                pixels[i + 3] = 0
    return bytes(pixels)


def main():
    try:
        from PIL import Image  # noqa: F401
        have_pil = True
    except ImportError:
        have_pil = False

    print(f"Generating iconset in: {ICONSET_DIR}")
    os.makedirs(ICONSET_DIR, exist_ok=True)

    for size, filename in ICON_SIZES:
        pixels = _generate_icon_pixels(size)
        path = os.path.join(ICONSET_DIR, filename)

        if have_pil:
            from PIL import Image
            img = Image.frombytes("RGBA", (size, size), pixels)
            img.save(path)
            print(f"  {filename:20s}  {size}x{size}  (Pillow)")
        else:
            _write_png(path, size, pixels)
            print(f"  {filename:20s}  {size}x{size}  (raw PNG)")

    # Convert to .icns using iconutil (macOS only)
    if sys.platform == "darwin":
        if os.path.exists(OUTPUT_ICNS):
            os.remove(OUTPUT_ICNS)
        subprocess.run(
            ["iconutil", "--convert", "icns", ICONSET_DIR, "--output", OUTPUT_ICNS],
            check=True,
        )
        print(f"\n.icns created at: {OUTPUT_ICNS}")
        # Cleanup iconset
        shutil.rmtree(ICONSET_DIR)
        print("Temp iconset removed.")
    else:
        print(f"\nNot on macOS — skipping iconutil conversion.")
        print(f"On macOS, run: iconutil --convert icns {ICONSET_DIR} --output {OUTPUT_ICNS}")
        print(f"Or just keep the iconset folder at: {ICONSET_DIR}")


if __name__ == "__main__":
    import sys
    main()
