"""Render the app logo (src/ui/assets/app_icon.svg) into platform assets.

Outputs (committed, so builds don't need this script):
  packaging/windows/app.ico                         multi-size Windows icon
  android-tv/app/src/main/res/mipmap-*/ic_launcher.png
  android-tv/app/src/main/res/drawable-xhdpi/tv_banner.png   320×180 TV banner

Usage:  python packaging/generate_brand_assets.py
"""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform.startswith("win"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "src" / "ui" / "assets" / "app_icon.svg"
ANDROID_RES = ROOT / "android-tv" / "app" / "src" / "main" / "res"


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(str(SVG)).render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def write_ico(path: Path, sizes=(16, 24, 32, 48, 64, 128, 256)) -> None:
    """ICO container with PNG-compressed entries (supported since Windows Vista)."""
    images = [png_bytes(render(size)) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for size, blob in zip(sizes, images):
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(images))


def write_tv_banner(path: Path, width: int = 320, height: int = 180) -> None:
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0.0, QColor("#1e1e21"))
    gradient.setColorAt(1.0, QColor("#0e0e10"))
    painter.fillRect(image.rect(), gradient)
    logo = 112
    QSvgRenderer(str(SVG)).render(painter, QRectF(18, (height - logo) / 2, logo, logo))
    painter.setPen(QColor("#f5f5f7"))
    font = QFont("Segoe UI", 22)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRectF(140, 52, width - 150, 40), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "IPTV")
    painter.setPen(QColor("#e8455a"))
    painter.drawText(QRectF(140, 88, width - 150, 40), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Player")
    painter.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path), "PNG")


def main() -> None:
    QApplication.instance() or QApplication([])
    write_ico(ROOT / "packaging" / "windows" / "app.ico")
    for folder, size in {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}.items():
        target = ANDROID_RES / f"mipmap-{folder}" / "ic_launcher.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        render(size).save(str(target), "PNG")
    write_tv_banner(ANDROID_RES / "drawable-xhdpi" / "tv_banner.png")
    print("Brand assets written.")


if __name__ == "__main__":
    main()
