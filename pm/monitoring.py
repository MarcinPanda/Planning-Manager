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
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
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
POSITION_ON_COLOR = "#2ecc71"  # zielona komórka = osoba pracuje w tej strefie


def login_tooltip(login):
    if not login:
        return "No login (use Import Logins)"
    return f"Login {login}  ·  picking N{login}P / Z{login}P  ·  reach R{login}R"


def employee_tooltip(emp):
    since = emp.active_since
    return (
        f"{emp.lastname} {emp.firstname}\n"
        f"Login: {emp.login or '-'}\n"
        + (f"Zones: {', '.join(emp.positions)}\n" if emp.positions else "")
        + f"Work hours: {emp.work_hours}\n"
        f"Total: {emp.computed_hours} h\n"
        f"Here since: {since or 'start of work'}"
        + (f"\nInfo: {emp.info}" if emp.info else "")
    )

ZONE_STYLE = "DropZone { border: 1px solid #999; border-radius: 4px; }"
ZONE_STYLE_HOVER = "DropZone { border: 2px solid #00BCff; border-radius: 4px; }"


class EmployeeList(QListWidget):
    """Lista kostek w jednej strefie. Obsługuje przeciąganie i upuszczanie."""

    dropped = Signal(list, str, bool)   # id pracowników, pozycja źródłowa, czy z Ctrl (dołóż)
    drag_state = Signal(bool)
    hover = Signal(bool)

    def __init__(self, accepts_drops=True, parent=None):
        super().__init__(parent)
        self.accepts_drops = accepts_drops
        self.zone_position = ""
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
        mime.setData(MIME_TYPE, json.dumps({"ids": ids, "from": self.zone_position}).encode("utf-8"))

        drag = QDrag(self)
        drag.setMimeData(mime)

        self.drag_state.emit(True)
        try:
            drag.exec(Qt.MoveAction | Qt.CopyAction, Qt.MoveAction)
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
            payload = json.loads(bytes(event.mimeData().data(MIME_TYPE)).decode("utf-8"))
            ids = [int(i) for i in payload["ids"]]
            from_position = str(payload.get("from", ""))
        except Exception:
            event.ignore()
            return

        add = bool(event.modifiers() & Qt.ControlModifier)  # Ctrl = dołóż strefę zamiast przenosić
        event.acceptProposedAction()
        if event.source() is not self:
            self.dropped.emit(ids, from_position, add)


class DropZone(QFrame):
    """Jedna strefa tablicy: dział albo pozycja (klient / strefa) wewnątrz działu."""

    move_requested = Signal(list, str, str, str, bool)  # ids, dział, pozycja, pozycja źródłowa, dołóż
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
        self.list.zone_position = position
        self.list.dropped.connect(
            lambda ids, source, add: self.move_requested.emit(ids, self.department, self.position, source, add)
        )
        self.list.drag_state.connect(self.drag_state)
        self.list.hover.connect(lambda on: self.setStyleSheet(ZONE_STYLE_HOVER if on else ZONE_STYLE))
        layout.addWidget(self.list)

    def set_employees(self, employees, show_department=False):
        self.list.clear()

        for emp in sorted(employees, key=lambda e: (e.firstname.casefold(), e.lastname.casefold())):
            since = emp.active_since
            text = (
                f"{emp.firstname} {emp.lastname}"
                + (f"  [{emp.login}]" if emp.login else "")
                + (f"  –  {emp.active_department}" if show_department else "")
                + (f"  ·  {since}" if since else "")
            )

            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, emp.employee_id)
            item.setBackground(QBrush(QColor(STATUS_COLORS.get(emp.status, CHIP_COLOR))))
            item.setForeground(QBrush(QColor("#000000")))
            item.setToolTip(employee_tooltip(emp))

            if emp.status == "home":
                # kto poszedł do domu, tego już nie przenosimy
                item.setFlags(item.flags() & ~Qt.ItemIsDragEnabled & ~Qt.ItemIsSelectable)

            self.list.addItem(item)

        count = len(employees)
        self.title_label.setText(f"{self.title}  ({count})" if count else self.title)


class PositionTable(QTableWidget):
    """Tabela działu ze strefami (jak zakładka Tools w Excelu).

    Wiersz = pracownik, kolumny = strefy / klienci. Kliknięcie komórki włącza lub
    wyłącza daną strefę – można zaznaczyć kilka naraz (godziny się nie zmieniają).
    Nazwisko można przeciągnąć do innego działu; osobę z innego działu można tu
    upuścić (na nazwisko = bez strefy, na kolumnę strefy = od razu w tej strefie).
    """

    FIXED_COLS = 2  # Name, Login
    MIN_ROWS = 3

    move_requested = Signal(list, str, str, str, bool)
    toggle_position_requested = Signal(int, str)
    drag_state = Signal(bool)

    def __init__(self, department, positions, parent=None):
        super().__init__(parent)
        self.department = department
        self.positions = positions
        self.employees = []

        self.setColumnCount(self.FIXED_COLS + len(positions))
        self.setHorizontalHeaderLabels(["Name", "Login", *positions])
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        self.setColumnWidth(0, 220)
        self.setColumnWidth(1, 60)
        for col in range(self.FIXED_COLS, self.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.Stretch)
            self.horizontalHeaderItem(col).setToolTip("Click a cell to switch this zone on / off")

        self.cellClicked.connect(self._on_cell_clicked)
        self.setRowCount(self.MIN_ROWS)
        self._fit_height()

    # ---------------------------------------------------------------- dane
    def set_employees(self, employees):
        self.employees = sorted(employees, key=lambda e: (e.firstname.casefold(), e.lastname.casefold()))
        self.clearContents()
        self.setRowCount(max(self.MIN_ROWS, len(self.employees)))

        for row, emp in enumerate(self.employees):
            status_color = STATUS_COLORS.get(emp.status)
            since = emp.active_since

            name = QTableWidgetItem(f"{emp.firstname} {emp.lastname}" + (f"  ·  {since}" if since else ""))
            name.setData(Qt.UserRole, emp.employee_id)
            name.setToolTip(employee_tooltip(emp))
            name.setBackground(QBrush(QColor(status_color or CHIP_COLOR)))
            name.setForeground(QBrush(QColor("#000000")))
            self.setItem(row, 0, name)

            login = QTableWidgetItem(emp.login)
            login.setTextAlignment(Qt.AlignCenter)
            login.setToolTip(login_tooltip(emp.login))
            self.setItem(row, 1, login)

            active = set(emp.positions)
            for i, position in enumerate(self.positions):
                cell = QTableWidgetItem("✓" if position in active else "")
                cell.setTextAlignment(Qt.AlignCenter)
                if position in active:
                    cell.setBackground(QBrush(QColor(POSITION_ON_COLOR)))
                    cell.setForeground(QBrush(QColor("#000000")))
                cell.setToolTip(f"{position}: click to switch on / off")
                self.setItem(row, self.FIXED_COLS + i, cell)

        self._fit_height()

    def _fit_height(self):
        height = self.horizontalHeader().sizeHint().height() + 2 * self.frameWidth()
        height += sum(self.rowHeight(r) for r in range(self.rowCount()))
        height += self.horizontalScrollBar().sizeHint().height()  # miejsce na pasek przy wąskim oknie
        self.setFixedHeight(height)

    def employee_at(self, row):
        return self.employees[row] if 0 <= row < len(self.employees) else None

    def _on_cell_clicked(self, row, col):
        emp = self.employee_at(row)
        if emp is None or col < self.FIXED_COLS or emp.status == "home":
            return
        self.toggle_position_requested.emit(emp.employee_id, self.positions[col - self.FIXED_COLS])

    # ------------------------------------------------------- przeciąganie
    def startDrag(self, supported_actions):
        rows = sorted({index.row() for index in self.selectedIndexes()})
        ids = [
            emp.employee_id
            for emp in (self.employee_at(r) for r in rows)
            if emp is not None and emp.status != "home"
        ]
        if not ids:
            return

        mime = QMimeData()
        mime.setData(MIME_TYPE, json.dumps({"ids": ids, "from": ""}).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)

        self.drag_state.emit(True)
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self.drag_state.emit(False)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(MIME_TYPE) or event.source() is self:
            event.ignore()
            return
        try:
            payload = json.loads(bytes(event.mimeData().data(MIME_TYPE)).decode("utf-8"))
            ids = [int(i) for i in payload["ids"]]
        except Exception:
            event.ignore()
            return

        col = self.columnAt(event.position().toPoint().x())
        event.acceptProposedAction()
        self.handle_drop(ids, col)

    def handle_drop(self, ids, col):
        position = self.positions[col - self.FIXED_COLS] if col >= self.FIXED_COLS else ""
        self.move_requested.emit(ids, self.department, position, "", False)


class MonitoringView(QWidget):
    """Tablica: działy ze strefami jako tabele (jak w Excelu), pod spodem wszystkie pozostałe działy."""

    move_requested = Signal(list, str, str, str, bool)
    toggle_position_requested = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.dragging = False
        self._signature = None
        self.zones = {}        # dział -> DropZone (działy bez stref)
        self.tables = {}       # dział -> PositionTable (działy ze strefami)
        self.boxes = {}        # dział -> QGroupBox z tabelą
        self.other_zone = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        container = QWidget()
        layout = QVBoxLayout(container)
        scroll.setWidget(container)

        hint = QLabel(
            "Drag a name to another department = move (from now)  ·  "
            "Click a zone cell = switch that zone on / off (several at once allowed)  ·  "
            "Ctrl / Shift + click = select several names"
        )
        hint.setStyleSheet("color: #888;")
        layout.addWidget(hint)

        # Działy ze strefami / klientami – tabele
        for dept, positions in SUB_POSITIONS.items():
            box = QGroupBox(self._box_title(dept, 0))
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(4, 4, 4, 4)

            table = PositionTable(dept, positions)
            table.move_requested.connect(self.move_requested)
            table.toggle_position_requested.connect(self.toggle_position_requested)
            table.drag_state.connect(self._set_dragging)
            self.tables[dept] = table
            self.boxes[dept] = box

            box_layout.addWidget(table)
            layout.addWidget(box)

        # Pozostałe działy – wszystkie naraz
        grid_box = QGroupBox("Departments")
        grid = QGridLayout(grid_box)
        grid.setSpacing(4)

        others = [dept for dept in TEAM_LIST if dept not in SUB_POSITIONS]
        for index, dept in enumerate(others):
            zone = DropZone(dept, dept, "")
            zone.setMinimumHeight(100)
            self.zones[dept] = zone
            zone.move_requested.connect(self.move_requested)
            zone.drag_state.connect(self._set_dragging)
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

    @staticmethod
    def _box_title(dept, count):
        title = f"{SUB_POSITION_TITLES.get(dept, dept)}  –  {dept}"
        return f"{title}  ({count})" if count else title

    def _set_dragging(self, state):
        self.dragging = state

    def place_of(self, emp):
        """('table', dział) / ('zone', dział) / ('other', '') – gdzie pokazać pracownika."""
        dept = emp.active_department
        if dept in self.tables:
            return ("table", dept)
        if dept in self.zones:
            return ("zone", dept)
        return ("other", "")

    def set_employees(self, employees, force=False):
        """Przebudowuje tablicę, ale tylko gdy coś się zmieniło (żeby nie migała co 10 s)."""
        signature = sorted(
            (e.employee_id, e.lastname, e.firstname, e.login, e.active_department, e.position,
             e.active_since, e.status, e.work_hours, e.computed_hours, e.info)
            for e in employees
        )
        if not force and signature == self._signature:
            return
        if self.dragging:
            return  # nie przebudowujemy w trakcie przeciągania; zrobi to następne odświeżenie
        self._signature = signature

        in_tables = {dept: [] for dept in self.tables}
        in_zones = {dept: [] for dept in self.zones}
        other = []

        for emp in employees:
            kind, dept = self.place_of(emp)
            if kind == "table":
                in_tables[dept].append(emp)
            elif kind == "zone":
                in_zones[dept].append(emp)
            else:
                other.append(emp)

        for dept, table in self.tables.items():
            table.set_employees(in_tables[dept])
            self.boxes[dept].setTitle(self._box_title(dept, len(in_tables[dept])))
        for dept, zone in self.zones.items():
            zone.set_employees(in_zones[dept])
        self.other_zone.set_employees(other, show_department=True)
        self.other_zone.setVisible(bool(other))
