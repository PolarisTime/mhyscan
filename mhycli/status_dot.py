"""状态灯组件 — 圆点 + 可选呼吸脉动

状态: idle(灰) / ok(绿) / busy(蓝) / warn(琥珀) / error(红)
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel

COLORS = {
    "idle": "#6A7080",
    "ok": "#34D399",
    "busy": "#7CB3FF",
    "warn": "#FBBF24",
    "error": "#F87171",
}


class StatusDot(QLabel):
    def __init__(self, status: str = "idle", parent=None, pulse: bool = False):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._color = QColor(COLORS.get(status, COLORS["idle"]))
        self._pulse = pulse
        self._opacity = 1.0
        self._timer = None
        if pulse:
            self._timer = QTimer(self)
            self._timer.setInterval(500)
            self._timer.timeout.connect(self._toggle)
            self._timer.start()

    def set_status(self, status: str, pulse: bool = False):
        self._color = QColor(COLORS.get(status, COLORS["idle"]))
        self._pulse = pulse
        if pulse and self._timer and not self._timer.isActive():
            self._timer.start()
        elif not pulse and self._timer:
            self._timer.stop()
        self._opacity = 1.0
        self.update()

    def _toggle(self):
        self._opacity = 0.35 if self._opacity > 0.5 else 1.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        p.setOpacity(0.22)
        p.drawEllipse(self.rect())
        p.setOpacity(self._opacity)
        p.drawEllipse(QRectF(2, 2, 6, 6))
