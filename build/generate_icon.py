"""Generate multi-resolution Art Director application icons (.ico and .png)."""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication


def render_icon_png(size: int) -> bytes:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = max(1.0, size * 0.04)
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)

    grad = QLinearGradient(QPointF(0, 0), QPointF(size, size))
    grad.setColorAt(0.0, QColor("#1b263b"))
    grad.setColorAt(0.55, QColor("#111827"))
    grad.setColorAt(1.0, QColor("#0b1320"))

    p.setBrush(grad)
    p.setPen(QPen(QColor("#2ecc71"), max(1.5, size * 0.05)))
    radius = size * 0.22
    p.drawRoundedRect(rect, radius, radius)

    # Subtle voice-wave arc above AD monogram
    wave_pen = QPen(QColor("#38bdf8"), max(1.2, size * 0.045))
    wave_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(wave_pen)
    cx = size * 0.5
    cy = size * 0.25
    bars = [(-0.22, 0.07), (-0.11, 0.13), (0.0, 0.17), (0.11, 0.13), (0.22, 0.07)]
    for dx, half_h in bars:
        x = cx + dx * size
        hh = half_h * size * 0.5
        p.drawLine(QPointF(x, cy - hh), QPointF(x, cy + hh))

    # Crisp "AD" monogram
    p.setPen(QColor("#ffffff"))
    font = QFont("Segoe UI", max(6, int(size * 0.36)), QFont.Weight.Bold)
    p.setFont(font)
    text_rect = QRectF(0, size * 0.24, size, size * 0.72)
    p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "AD")
    p.end()

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buf, "PNG")
    return bytes(buf.data())


def build_ico_from_pngs(sizes: list[int]) -> bytes:
    pngs = [(s, render_icon_png(s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries = bytearray()
    payload = bytearray()
    for s, data in pngs:
        dim = 0 if s >= 256 else s
        entries.extend(
            struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        )
        payload.extend(data)
        offset += len(data)
    return header + bytes(entries) + bytes(payload)


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    assets_dir = Path(__file__).resolve().parents[1] / "art_director" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    png_256 = render_icon_png(256)
    (assets_dir / "art_director.png").write_bytes(png_256)

    ico_bytes = build_ico_from_pngs([16, 24, 32, 48, 64, 128, 256])
    (assets_dir / "art_director.ico").write_bytes(ico_bytes)
    print(f"Generated icons in {assets_dir}")
    app.quit()


if __name__ == "__main__":
    main()
