from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QPushButton
from .theme import FONT_FAMILY


class Tile(QPushButton):
    def __init__(self, glyph):
        super().__init__()
        self.glyph = glyph
        self.label = ""
        self.state = "--"
        self.setMinimumHeight(108)

    def set_display(self, label, state):
        self.label, self.state = label, state
        self.setAccessibleName(f"{label}: {state}")
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("white" if self.hasFocus() else "#50555C"), 2))
        painter.setBrush(QColor("#484E58" if self.underMouse() else "#30343A"))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)
        painter.setPen(QColor("white" if self.isEnabled() else "#8E9298"))
        font = QFont("Segoe MDL2 Assets")
        font.setPixelSize(24)
        painter.setFont(font)
        painter.drawText(QRect(0, 12, self.width(), 32), Qt.AlignCenter, self.glyph)
        font = QFont(FONT_FAMILY)
        font.setPixelSize(14)
        painter.setFont(font)
        painter.drawText(QRect(2, 46, self.width() - 4, 24), Qt.AlignCenter, self.label)
        painter.setPen(QColor("#58C8ED" if self.isEnabled() else "#8E9298"))
        painter.drawText(QRect(2, 73, self.width() - 4, 22), Qt.AlignCenter, self.state)
