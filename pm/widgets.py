"""Pomocnicze widżety, wątki robocze i delegaty."""
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QItemDelegate,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    Property,
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QPainter, QColor

from .db import load_employees_from_db


class ToggleButton(QCheckBox):
    def __init__(
        self,
        width=70,
        height=25,
        bgColor="#777",
        circleColor="#DDD",
        activeColor="#00BCff",
        animationCurve=QEasingCurve.Linear,
        parent=None
    ):
        super().__init__(parent)

        self.setFixedSize(width, height)
        self.setCursor(Qt.PointingHandCursor)

        self._bg_color = bgColor
        self._circle_color = circleColor
        self._active_color = activeColor
        self._circle_diameter = height - 6
        self._circle_position = 3

        self.animation = QPropertyAnimation(self, b"circle_position", self)
        self.animation.setDuration(200)
        self.animation.setEasingCurve(animationCurve)
        self.stateChanged.connect(self.start_transition)

    @Property(int)
    def circle_position(self):
        return self._circle_position

    @circle_position.setter
    def circle_position(self, pos):
        self._circle_position = pos
        self.update()

    def start_transition(self, state):
        self.animation.stop()
        self.animation.setEndValue(self.width() - self._circle_diameter - 3 if state == 2 else 3)
        self.animation.start()

    def hitButton(self, pos):
        return self.contentsRect().contains(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()

        painter.setBrush(QColor(self._active_color if self.isChecked() else self._bg_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, rect.height() // 2, rect.height() // 2)

        painter.setBrush(QColor(self._circle_color))
        painter.drawEllipse(self._circle_position, 3, self._circle_diameter, self._circle_diameter)

        painter.end()


class DatabaseLoadWorker(QObject):
    finished = Signal(list)
    error = Signal(str)

    @Slot()
    def run(self):
        try:
            data = load_employees_from_db()
            self.finished.emit(data)
        except Exception as exc:
            self.error.emit(str(exc))


class DatabaseTaskWorker(QObject):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = task

    @Slot()
    def run(self):
        try:
            result = self.task()
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class InfoItemDelegate(QItemDelegate):
    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)

        parent_widget = parent.window()
        if hasattr(parent_widget, "is_editing_info"):
            parent_widget.is_editing_info = True

        return editor

    def setModelData(self, editor, model, index):
        super().setModelData(editor, model, index)

        parent_widget = editor.window()
        if hasattr(parent_widget, "is_editing_info"):
            parent_widget.is_editing_info = False

    def destroyEditor(self, editor, index):
        # Anulowanie edycji (Esc) nie wywołuje setModelData – zdejmij flagę tutaj,
        # inaczej auto-odświeżanie zostałoby wstrzymane na stałe.
        parent_widget = editor.window()
        if hasattr(parent_widget, "is_editing_info"):
            parent_widget.is_editing_info = False
        super().destroyEditor(editor, index)
