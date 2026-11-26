"""Custom PySide6 widgets for Art Director (VU meter, Emoji status badge, styling)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


DARK_STYLESHEET = """
QMainWindow, QDialog {
    background-color: #14171d;
    color: #e6eaf2;
    font-family: "Segoe UI", "Inter", "San Francisco", sans-serif;
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #2a3140;
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px 10px 10px 10px;
    background-color: #1b2029;
    font-weight: 600;
    color: #c8d2e6;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QPushButton {
    background-color: #262d3b;
    color: #e6eaf2;
    border: 1px solid #384357;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #323c4f;
    border-color: #4f6080;
}
QPushButton:pressed {
    background-color: #1f2530;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit, QTableWidget {
    background-color: #101318;
    color: #eef2fa;
    border: 1px solid #2e3748;
    border-radius: 5px;
    padding: 5px 8px;
}
QHeaderView::section {
    background-color: #1f2633;
    color: #c9d4ea;
    border: 1px solid #2e3748;
    padding: 5px;
    font-weight: 600;
}
QTabWidget::pane {
    border: 1px solid #2a3140;
    border-radius: 6px;
    background-color: #181c24;
}
QTabBar::tab {
    background-color: #1d222c;
    color: #9ba8c2;
    padding: 8px 14px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #293244;
    color: #ffffff;
    font-weight: 600;
}
"""


class AudioLevelMeter(QWidget):
    """Real-time horizontal dBFS VU meter with noise-gate threshold line."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(24)
        self.setMaximumHeight(28)
        self._rms_db = -90.0
        self._peak_db = -90.0
        self._gate_db = -42.0
        self._gate_open = False

    def set_levels(
        self, rms_db: float, peak_db: float, gate_db: float, gate_open: bool
    ) -> None:
        self._rms_db = rms_db
        self._peak_db = peak_db
        self._gate_db = gate_db
        self._gate_open = gate_open
        self.update()

    def _db_to_ratio(self, db: float) -> float:
        clamped = max(-60.0, min(0.0, db))
        return (clamped + 60.0) / 60.0

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()

        # Background track
        painter.setBrush(QColor("#0d1015"))
        painter.setPen(QColor("#2c3445"))
        painter.drawRoundedRect(0, 0, w - 1, h - 1, 5, 5)

        rms_w = int(self._db_to_ratio(self._rms_db) * (w - 4))
        peak_x = int(self._db_to_ratio(self._peak_db) * (w - 4)) + 2
        gate_x = int(self._db_to_ratio(self._gate_db) * (w - 4)) + 2

        if rms_w > 0:
            bar_color = QColor("#2ecc71") if self._gate_open else QColor("#3b82f6")
            if self._peak_db > -6.0:
                bar_color = QColor("#e74c3c")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bar_color)
            painter.drawRoundedRect(2, 3, rms_w, h - 6, 3, 3)

        # Peak hold line
        painter.setPen(QColor("#f1c40f"))
        painter.drawLine(peak_x, 2, peak_x, h - 3)

        # Noise gate threshold marker
        painter.setPen(QColor("#ff6b6b"))
        painter.drawLine(gate_x, 1, gate_x, h - 2)


class EmojiStatusBadge(QFrame):
    """Prominent visual status badge showing 👍 for Wake Mode and 👋 for Sleep Mode."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 16, 8)
        layout.setSpacing(12)

        self.emoji_label = QLabel("👍")
        emoji_font = QFont()
        emoji_font.setPointSize(24)
        self.emoji_label.setFont(emoji_font)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        self.mode_label = QLabel("WAKE MODE")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        self.mode_label.setFont(title_font)

        self.sub_label = QLabel("Ascolto comandi attivo")
        self.sub_label.setStyleSheet("color: #b7c3da; font-size: 11px;")

        text_col.addWidget(self.mode_label)
        text_col.addWidget(self.sub_label)
        layout.addWidget(self.emoji_label)
        layout.addLayout(text_col)
        self.set_mode("wake", "👍", "WAKE MODE (Attivo)")

    def set_mode(self, mode: str, emoji: str, label: str) -> None:
        self.emoji_label.setText(emoji)
        self.mode_label.setText(label)
        if mode == "wake":
            self.sub_label.setText("Pronto a ricevere prefissi e comandi vocali")
            self.setStyleSheet(
                "QFrame { background-color: #132a1f; border: 2px solid #2ecc71; border-radius: 10px; }"
                "QLabel { border: none; background: transparent; color: #e8fff1; }"
            )
        elif mode == "sleep":
            self.sub_label.setText("Comandi sospesi — pronuncia Wake o usa Hotkey")
            self.setStyleSheet(
                "QFrame { background-color: #2b2314; border: 2px solid #f39c12; border-radius: 10px; }"
                "QLabel { border: none; background: transparent; color: #fff5df; }"
            )
        else:
            self.sub_label.setText("Interruzione globale e reset di sicurezza")
            self.setStyleSheet(
                "QFrame { background-color: #361316; border: 2px solid #e74c3c; border-radius: 10px; }"
                "QLabel { border: none; background: transparent; color: #ffe8e8; }"
            )
