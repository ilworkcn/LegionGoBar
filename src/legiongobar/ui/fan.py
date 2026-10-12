from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from ..native.legion_hid import FAN_FLOORS as FLOORS


class FanCurve(QWidget):
    edited = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = FLOORS.copy()
        self.selected = 0
        self.dragging = False
        self.setMinimumHeight(150)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_data(self, value):
        values = [int(v) for v in value.split(",")]
        if len(values) == 10:
            self.values = values
            self.update()

    def points(self):
        return [QPointF(8 + index * (self.width() - 16) / 9, 8 + (100 - value) * (self.height() - 16) / 100) for index, value in enumerate(self.values)]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#50555C"), 1))
        for row in range(5):
            y = 8 + row * (self.height() - 16) / 4
            painter.drawLine(QPointF(8, y), QPointF(self.width() - 8, y))
        painter.setPen(QPen(QColor("#58C8ED"), 2))
        painter.drawPolyline(QPolygonF(self.points()))
        for index, point in enumerate(self.points()):
            painter.setBrush(QColor("white" if index == self.selected and self.hasFocus() else "#58C8ED"))
            painter.drawEllipse(point, 4, 4)

    def move_point(self, position):
        value = round(100 - (position.y() - 8) * 100 / max(1, self.height() - 16))
        self.values[self.selected] = min(100, max(FLOORS[self.selected], value))
        self.update()

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton:
            self.selected = min(range(10), key=lambda i: abs(self.points()[i].x() - event.position().x()))
            self.dragging = True
            self.move_point(event.position())

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move_point(event.position())

    def mouseReleaseEvent(self, event):
        if self.dragging:
            self.dragging = False
            self.edited.emit(",".join(map(str, self.values)))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_Right):
            self.selected = min(9, max(0, self.selected + (1 if event.key() == Qt.Key_Right else -1)))
        elif event.key() in (Qt.Key_Up, Qt.Key_Down):
            delta = 1 if event.key() == Qt.Key_Up else -1
            self.values[self.selected] = min(100, max(FLOORS[self.selected], self.values[self.selected] + delta))
            self.edited.emit(",".join(map(str, self.values)))
        else:
            super().keyPressEvent(event)
        self.update()
