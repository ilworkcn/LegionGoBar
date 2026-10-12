"""无边框窗口的拖动区域；调试窗口使用系统标题栏。"""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from importlib.resources import files
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton

class TitleBar(QWidget):
    def __init__(self, window, i18n):
        super().__init__(window)
        self.main_window = window
        self.drag_offset = None
        self.setFixedHeight(36)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        title = QLabel("LegionGoBar", self)
        title.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(title, 1)
        for name, tip, action in (("minimize", "Minimize", window.showMinimized), ("close", "Close", window.close)):
            button = QPushButton(self)
            button.setObjectName("window_" + name)
            button.setProperty("role", "window-close" if name == "close" else "window-control")
            button.setIcon(QIcon(str(files("legiongobar").joinpath(f"assets/ui/{name}.svg"))))
            button.setIconSize(QSize(16, 16))
            button.setFixedSize(36, 32)
            i18n.bind(button, tip, "setAccessibleName")
            i18n.bind(button, tip, "setToolTip")
            button.clicked.connect(action)
            row.addWidget(button)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self.main_window.windowHandle()
            if not handle or not handle.startSystemMove():
                self.drag_offset = event.globalPosition().toPoint() - self.main_window.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.main_window.move(event.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, event):
        self.drag_offset = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.main_window.showNormal() if self.main_window.isMaximized() else self.main_window.showMaximized()
