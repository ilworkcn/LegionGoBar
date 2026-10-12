"""按原型绘制滑块，统一鼠标拖动、刻度吸附和键盘操作。"""
from PySide6.QtCore import Qt, QRectF, QPointF, QSize
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSlider


class Slider(QSlider):
    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.snap_interval = 1
        self.setMinimumHeight(36)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def sizeHint(self):
        return QSize(160, 36)

    def snapped(self, value):
        step = max(1, self.snap_interval)
        value = self.minimum() + int((value-self.minimum())/step + 0.5)*step
        return max(self.minimum(), min(self.maximum(), value))

    def position_value(self, x):
        fraction = max(0, min(1, (x-12)/max(1, self.width()-24)))
        if self.invertedAppearance() != (self.layoutDirection() == Qt.RightToLeft):
            fraction = 1-fraction
        return self.snapped(self.minimum()+fraction*(self.maximum()-self.minimum()))

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        self.setFocus(Qt.MouseFocusReason)
        self.setSliderDown(True)
        self.setSliderPosition(self.position_value(event.position().x()))
        event.accept()

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self.setSliderPosition(self.position_value(event.position().x()))
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isSliderDown():
            self.setSliderPosition(self.position_value(event.position().x()))
            self.setSliderDown(False)
            self.update()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        left, right, y = 12., self.width()-12., self.height()/2-2
        span = max(1, self.maximum()-self.minimum())
        reverse = self.invertedAppearance() != (self.layoutDirection() == Qt.RightToLeft)
        def x_for(value):
            ratio = (value-self.minimum())/span
            return left + (1-ratio if reverse else ratio)*(right-left)
        x = x_for(self.sliderPosition())
        accent = QColor('#58C8ED' if self.isEnabled() else '#606060')
        painter.setPen(QPen(QColor('#626970' if self.isEnabled() else '#41464C'), 4, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(left, y), QPointF(right, y))
        painter.setPen(QPen(accent, 4, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(right if reverse else left, y), QPointF(x, y))
        if self.tickPosition() != QSlider.NoTicks:
            interval = max(1, self.tickInterval())
            # 过密的刻度按整数倍间隔绘制，避免高范围控件挤成色块。
            interval *= max(1, int(span/max(1, (right-left)/4)/interval)+1)
            painter.setPen(QPen(QColor('#80868D'), 1))
            for value in range(self.minimum(), self.maximum()+1, interval):
                tx = x_for(value)
                if self.tickPosition() in (QSlider.TicksBelow, QSlider.TicksBothSides):
                    painter.drawLine(QPointF(tx, y+11), QPointF(tx, y+14))
                if self.tickPosition() in (QSlider.TicksAbove, QSlider.TicksBothSides):
                    painter.drawLine(QPointF(tx, y-11), QPointF(tx, y-14))
        painter.setPen(QPen(QColor('#555B63'), 1))
        painter.setBrush(QColor('#30343A'))
        painter.drawEllipse(QPointF(x, y), 10, 10)
        painter.setPen(Qt.NoPen)
        painter.setBrush(accent)
        radius = 5 if self.isSliderDown() else 7 if self.underMouse() else 6
        painter.drawEllipse(QPointF(x, y), radius, radius)
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor('white'), 2))
            painter.drawRoundedRect(QRectF(1, 1, self.width()-2, self.height()-2), 4, 4)
