"""Widok Monitoring: tablica działów z pracownikami jako „kostkami" do przeciągania.

Widok niczego sam nie zapisuje. Po upuszczeniu kostki wysyła sygnał
move_requested(ids, dział, pozycja), a główne okno wykonuje zapis w bazie.
"""
import json

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .config import (
    MONITORING_GRID_COLUMNS,
    ROW_COLOR_HOME,
    ROW_COLOR_LATE,
    ROW_COLOR_SICK,
    SUB_POSITION_TITLES,
    SUB_POSITIONS,
    TEAM_LIST,
)

MIME_TYPE = "application/x-planning-employee-ids"
OTHER_ZONE = "Other / unknown"

STATUS_COLORS = {"sick": ROW_COLOR_SICK, "home": ROW_COLOR_HOME, "late": ROW_COLOR_LATE}
CHIP_COLOR = "#DCEBFF"

ZONE_STYLE = "DropZone { border: 1px solid #999; border-radius: 4px; }"
ZONE_STYLE_HOVER = "DropZone { border: 2px solid #00BCff; border-radius: 4px; }"


class EmployeeList(QListWidget):
    """Lista kostek w jednej strefie. Obsługuje przeciąganie i upuszczanie."""

    dropped = Signal(list)   # id pracowników upuszczonych na tę listę
    drag_state = Signal(bool)
    hover = Signal(bool)

    def __init__(self, accepts_drops=True, parent=None):
        super().__init__(parent)
        self.accepts_drops = accepts_drops
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(accepts_drops)
        self.setDragDropMode(QAbstractItemView.DragDrop if accepts_drops else QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setSpacing(1)

    def startDrag(self, supported_actions):
        ids = [
            item.data(Qt.UserRole)
            for item in self.selectedItems()
            if item.flags() & Qt.ItemIsDragEnabled
        ]
        if not ids:
            return

        mime = QMimeData()
        mime.setData(MIME_TYPE, json.dumps(ids).encode("utf-8"))

        drag = QDrag(self)
        drag.setMimeData(mime)

        self.drag_state.emit(True)
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self.drag_state.emit(False)

    def _accepts(self, event):
        return self.accepts_drops and event.mimeData().hasFormat(MIME_TYPE)

    def dragEnterEvent(self, event):
        if self._accepts(event):
            self.hover.emit(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._accepts(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.hover.emit(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.hover.emit(False)
        if not self._accepts(event):
            event.ignore()
            return

        try:
            ids = json.loads(bytes(event.mimeData().data(MIME_TYPE)).decode("utf-8"))
        except Exception:
            event.ignore()
            return

        event.acceptProposedAction()
        if event.source() is not self:
            self.dropped.emit([int(i) for i in ids])


class DropZone(QFrame):
    """Jedna strefa tablicy: dział albo pozycja (klient / strefa) wewnątrz działu."""

    move_requested = Signal(list, str, str)  # ids, dział, pozycja
    drag_state = Signal(bool)

    def __init__(self, title, department, position="", accepts_drops=True, parent=None):
        super().__init__(parent)
        self.title = title
        self.department = department
        self.position = position

        self.setObjectName("zone")
        self.setStyleSheet(ZONE_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.title_label)

        self.list = EmployeeList(accepts_drops)
        self.list.dropped.connect(lambda ids: self.move_requested.emit(ids, self.department, self.position))
        self.list.drag_state.connect(self.drag_state)
        self.list.hover.connect(lambda on: self.setStyleSheet(ZONE_STYLE_HOVER if on else ZONE_STYLE))
        layout.addWidget(self.list)

    def set_employees(self, employees):
        self.list.clear()

        for emp in sorted(employees, key=lambda e: (e.firstname.casefold(), e.lastname.casefold())):
            since = emp.active_since
            text = f"{emp.firstname} {emp.lastname}" + (f"  ·  {since}" if since else "")

            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, emp.employee_id)
            item.setBackground(QBrush(QColor(STATUS_COLORS.get(emp.status, CHIP_COLOR))))
            item.setForeground(QBrush(QColor("#000000")))
            item.setToolTip(
                f"{emp.lastname} {emp.firstname}\n"
                f"Work hours: {emp.work_hours}\n"
                f"Total: {emp.computed_hours} h\n"
                f"Here since: {since or 'start of work'}"
                + (f"\nInfo: {emp.info}" if emp.info else "")
            )

            if emp.status == "home":
                # kto poszedł do domu, tego już nie przenosimy
                item.setFlags(item.flags() & ~Qt.ItemIsDragEnabled & ~Qt.ItemIsSelectable)

            self.list.addItem(item)

        count = len(employees)
        self.title_label.setText(f"{self.title}  ({count})" if count else self.title)


class MonitoringView(QWidget):
    """Tablica: Piking i Reach Outbound z pozycjami, pod spodem wszystkie pozostałe działy."""

    move_requested = Signal(list, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.dragging = False
        self._signature = None
        self.zones = {}        # (dział, pozycja) -> DropZone
        self.other_zone = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        container = QWidget()
        layout = QVBoxLayout(container)
        scroll.setWidget(container)

        # Działy z pozycjami (klienci / strefy)
        for dept, positions in SUB_POSITIONS.items():
            box = QGroupBox(f"{SUB_POSITION_TITLES.get(dept, dept)}  –  {dept}")
            row = QHBoxLayout(box)
            row.setSpacing(4)

            self._add_zone(row, DropZone("No position", dept, ""))
            for position in positions:
                self._add_zone(row, DropZone(position, dept, position))

            box.setMinimumHeight(170)
            layout.addWidget(box)

        # Pozostałe działy – wszystkie naraz
        grid_box = QGroupBox("Departments")
        grid = QGridLayout(grid_box)
        grid.setSpacing(4)

        others = [dept for dept in TEAM_LIST if dept not in SUB_POSITIONS]
        for index, dept in enumerate(others):
            zone = DropZone(dept, dept, "")
            zone.setMinimumHeight(100)
            self._register(zone)
            grid.addWidget(zone, index // MONITORING_GRID_COLUMNS, index % MONITORING_GRID_COLUMNS)

        # Działy spoza listy (np. nietypowa nazwa z Excela) – tylko do wyciągania
        self.other_zone = DropZone(OTHER_ZONE, "", "", accepts_drops=False)
        self.other_zone.setMinimumHeight(100)
        self.other_zone.drag_state.connect(self._set_dragging)
        grid.addWidget(
            self.other_zone,
            len(others) // MONITORING_GRID_COLUMNS,
            len(others) % MONITORING_GRID_COLUMNS,
        )

        layout.addWidget(grid_box)
        layout.addStretch()

    def _add_zone(self, row_layout, zone):
        self._register(zone)
        row_layout.addWidget(zone)

    def _register(self, zone):
        self.zones[(zone.department, zone.position)] = zone
        zone.move_requested.connect(self.move_requested)
        zone.drag_state.connect(self._set_dragging)

    def _set_dragging(self, state):
        self.dragging = state

    def zone_key_for(self, emp):
        """Do której strefy należy pracownik (None = strefa „Other")."""
        dept = emp.active_department
        if (dept, emp.position) in self.zones:
            return (dept, emp.position)
        if (dept, "") in self.zones:
            return (dept, "")
        return None

    def set_employees(self, employees, force=False):
        """Przebudowuje tablicę, ale tylko gdy coś się zmieniło (żeby nie migała co 10 s)."""
        signature = sorted(
            (e.employee_id, e.lastname, e.firstname, e.active_department, e.position,
             e.active_since, e.status, e.work_hours, e.computed_hours, e.info)
            for e in employees
        )
        if not force and signature == self._signature:
            return
        if self.dragging:
            return  # nie przebudowujemy w trakcie przeciągania; zrobi to następne odświeżenie
        self._signature = signature

        groups = {key: [] for key in self.zones}
        other = []
        for emp in employees:
            key = self.zone_key_for(emp)
            if key is None:
                other.append(emp)
            else:
                groups[key].append(emp)

        for key, zone in self.zones.items():
            zone.set_employees(groups[key])
        self.other_zone.set_employees(other)
        self.other_zone.setVisible(bool(other))
