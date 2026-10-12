from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QPushButton
from .theme import text_font


class Tile(QPushButton):
    def __init__(self, glyph):
        super().__init__()
        self.glyph = glyph
        self.label = ""
        self.state = "--"
        self.visual_state = "off"
        self.setMinimumHeight(108)

    def set_display(self, label, state):
        self.label, self.state = label, state
        self.setAccessibleName(f"{label}: {state}")
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        painter.setPen(QPen(QColor("white" if self.hasFocus() or self.property("edit_selected") else "#50555C"), 2 if self.hasFocus() or self.property("edit_selected") else 1))
        color = QColor({"on": "#1A2E1F", "active": "#1A2530", "trigger": "#252030"}.get(self.visual_state, "#1A1C1E") if self.isEnabled() else "#0D0E0F")
        painter.setBrush(color.darker(110) if self.isDown() else color)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)
        painter.setPen(QColor("white" if self.isEnabled() else "#8E9298"))
        font = QFont("Segoe MDL2 Assets")
        font.setPixelSize(24)
        painter.setFont(font)
        painter.drawText(QRect(0, 12, self.width(), 32), Qt.AlignCenter, self.glyph)
        font = text_font(14)
        painter.setFont(font)
        painter.drawText(QRect(6, 44, self.width() - 12, 34), Qt.AlignCenter | Qt.TextWordWrap, self.label)
        painter.setPen(QColor(("#A0A0A0" if self.visual_state == "off" else "#58C8ED") if self.isEnabled() else "#606060"))
        painter.drawText(QRect(2, 73, self.width() - 4, 22), Qt.AlignCenter, self.state)
