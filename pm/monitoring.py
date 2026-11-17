"""Widok Monitoring: tablica magazynu – kto gdzie teraz jest („oczy steeringu").

Układ:
- pasek liczników u góry,
- hala North i hala South (zwijane): kolumny REACH i PICKING, w nich strefy / klienci z kartami osób,
- część wspólna dla obu hal: INBOUND i OTHER (pozostałe działy),
- panel po prawej: Unassigned (Reach bez strefy, Picking bez klienta), Ziek, Naar Huis.

Karta = pracownik („login – Nazwisko I."). Przeciągnięcie karty = przeniesienie (od teraz),
z Ctrl = dołożenie drugiej strefy. Widok niczego sam nie zapisuje – wysyła sygnały,
a główne okno zapisuje w bazie (Ctrl+Z cofa).
"""
import json

from PySide6.QtCore import QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .config import (
    HALLS,
    INBOUND_PREFIX,
    ROW_COLOR_HOME,
    ROW_COLOR_LATE,
    ROW_COLOR_SICK,
    SUB_POSITION_TITLES,
    SUB_POSITIONS,
    TEAM_LIST,
    hall_of,
)

MIME_TYPE = "application/x-planning-employee-ids"
OTHER_ZONE = "Other / unknown"
SIDE_DEPARTMENTS = ("Ziek", "Naar Huis")   # w panelu po prawej, nie na tablicy

STATUS_COLORS = {"sick": ROW_COLOR_SICK, "home": ROW_COLOR_HOME, "late": ROW_COLOR_LATE}
CHIP_COLOR = "#DCEBFF"
CARD_HEIGHT = 22

HALL_COLORS = {"North": "#1f6fb2", "South": "#c06a1b", "Both halls": "#4a5966"}

ZONE_STYLE = ("DropZone { border: 1px solid #555; border-radius: 4px; }"
              "DropZone QLabel#zoneTitle { font-weight: bold; }")
ZONE_STYLE_HOVER = ("DropZone { border: 2px solid #00BCff; border-radius: 4px; }"
                    "DropZone QLabel#zoneTitle { font-weight: bold; }")


def login_tooltip(login):
    if not login:
        return "No login (use Import Logins)"
    return f"Login {login}  ·  picking N{login}P / Z{login}P  ·  reach R{login}R"


def employee_tooltip(emp):
    since = emp.active_since
    return (
        f"{emp.firstname} {emp.lastname}\n"
        f"Login: {emp.login or '-'}\n"
        f"Department: {emp.active_department}\n"
        + (f"Zones: {', '.join(emp.positions)}\n" if emp.positions else "")
        + f"Work hours: {emp.work_hours}\n"
        f"Total: {emp.computed_hours} h\n"
        f"Here since: {since or 'start of work'}"
        + (f"\nInfo: {emp.info}" if emp.info else "")
    )


def card_text(emp, show_department=False):
    """„003 – Kowalski J." (bez loginu: samo nazwisko)."""
    name = emp.lastname + (f" {emp.firstname[:1]}." if emp.firstname else "")
    text = f"{emp.login} – {name}" if emp.login else name
    if show_department:
        text += f"   ·  {SUB_POSITION_TITLES.get(emp.active_department, emp.active_department)}"
    return text


def section_header(text, color):
    label = QLabel(text)
    label.setStyleSheet(
        f"background-color: {color}; color: #fff; font-weight: bold; padding: 4px 8px; border-radius: 3px;"
    )
    return label


class EmployeeList(QListWidget):
    """Lista kart w jednej strefie. Obsługuje przeciąganie i upuszczanie."""

    dropped = Signal(list, str, bool)   # id pracowników, pozycja źródłowa, czy z Ctrl (dołóż)
    remove_requested = Signal(list)     # id pracowników do zdjęcia z tej strefy
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
        self.setSpacing(0)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

    def selected_ids(self):
        return [item.data(Qt.UserRole) for item in self.selectedItems() if item.flags() & Qt.ItemIsDragEnabled]

    def _context_menu(self, pos):
        item = self.itemAt(pos)
        if item is None or not self.zone_position:
            return
        if not item.isSelected():
            self.clearSelection()
            item.setSelected(True)
        ids = self.selected_ids()
        if not ids:
            return
        menu = QMenu(self)
        menu.addAction(f"Remove from {self.zone_position}", lambda: self.remove_requested.emit(ids))
        menu.exec(self.viewport().mapToGlobal(pos))

    def startDrag(self, supported_actions):
        ids = self.selected_ids()
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
    """Jedna strefa tablicy: dział albo strefa / klient wewnątrz działu, z kartami osób."""

    move_requested = Signal(list, str, str, str, bool)  # ids, dział, pozycja, pozycja źródłowa, dołóż
    remove_requested = Signal(list, str)                # ids, pozycja
    drag_state = Signal(bool)

    def __init__(self, title, department, position="", accepts_drops=True, fit=True, min_rows=1, parent=None):
        super().__init__(parent)
        self.title = title
        self.department = department
        self.position = position
        self.fit = fit            # True: wysokość dopasowana do liczby kart (bez przewijania)
        self.min_rows = min_rows

        self.setStyleSheet(ZONE_STYLE)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum if fit else QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("zoneTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)

        self.list = EmployeeList(accepts_drops)
        self.list.zone_position = position
        self.list.dropped.connect(
            lambda ids, source, add: self.move_requested.emit(ids, self.department, self.position, source, add)
        )
        self.list.remove_requested.connect(lambda ids: self.remove_requested.emit(ids, self.position))
        self.list.drag_state.connect(self.drag_state)
        self.list.hover.connect(lambda on: self.setStyleSheet(ZONE_STYLE_HOVER if on else ZONE_STYLE))
        layout.addWidget(self.list)
        self._fit_height(0)

    def ids(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def _fit_height(self, count):
        if self.fit:
            self.list.setFixedHeight(max(self.min_rows, count) * CARD_HEIGHT + 4)

    def set_employees(self, employees, show_department=False):
        self.list.clear()

        for emp in sorted(employees, key=lambda e: (e.lastname.casefold(), e.firstname.casefold())):
            item = QListWidgetItem(card_text(emp, show_department))
            item.setSizeHint(QSize(10, CARD_HEIGHT))
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
        self._fit_height(count)


class Column(QFrame):
    """Kolumna tablicy (REACH / PICKING / INBOUND / OTHER): nagłówek + siatka stref."""

    def __init__(self, title, zones, grid_columns, parent=None):
        super().__init__(parent)
        self.title = title
        self.zones = zones
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(3)

        self.header = QLabel(title)
        self.header.setStyleSheet("font-weight: bold; font-size: 13px; padding: 2px;")
        layout.addWidget(self.header)

        grid = QGridLayout()
        grid.setSpacing(4)
        for index, zone in enumerate(zones):
            grid.addWidget(zone, index // grid_columns, index % grid_columns, Qt.AlignTop)
        for col in range(grid_columns):
            grid.setColumnStretch(col, 1)
        layout.addLayout(grid)
        layout.addStretch()

    def update_count(self):
        people = {emp_id for zone in self.zones for emp_id in zone.ids()}
        self.header.setText(f"{self.title}  ({len(people)})")
        return people


class HallSection(QFrame):
    """Hala (North / South / wspólne): zwijany nagłówek i kolumny obok siebie."""

    def __init__(self, title, color, columns, stretches, parent=None):
        super().__init__(parent)
        self.title = title
        self.columns = columns

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(3)

        self.header = QPushButton()
        self.header.setCheckable(True)
        self.header.setChecked(True)
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setStyleSheet(
            f"QPushButton {{ background-color: {color}; color: #fff; font-weight: bold; font-size: 14px;"
            " text-align: left; padding: 6px 10px; border: none; border-radius: 3px; }"
        )
        self.header.toggled.connect(self._toggle)
        layout.addWidget(self.header)

        self.body = QWidget()
        body_layout = QHBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)
        for column, stretch in zip(columns, stretches):
            body_layout.addWidget(column, stretch)
        layout.addWidget(self.body)
        self.update_count()

    def _toggle(self, open_):
        self.body.setVisible(open_)
        self.update_count()

    def update_count(self):
        people = set()
        for column in self.columns:
            people |= column.update_count()
        arrow = "▼" if self.header.isChecked() else "►"
        self.header.setText(f"{arrow}  {self.title.upper()}   ·   {len(people)} people")


class MonitoringView(QWidget):
    """Tablica magazynu: hale North / South, część wspólna i panel po prawej."""

    move_requested = Signal(list, str, str, str, bool)
    toggle_position_requested = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.dragging = False
        self._signature = None
        self.zones = {}           # dział -> DropZone (działy bez stref, także Ziek / Naar Huis)
        self.position_zones = {}  # (dział, strefa) -> DropZone
        self.halls = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # ---- pasek liczników
        self.kpi_labels = {}
        kpi_bar = QHBoxLayout()
        kpi_bar.setSpacing(6)
        for key in ("On shift", "Reach", "Picking", "Inbound", "Other", "Unassigned", "Ziek", "Naar Huis"):
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(
                "background-color: #2c3b4b; color: #e8eef4; border-radius: 4px; padding: 4px 10px;"
            )
            self.kpi_labels[key] = label
            kpi_bar.addWidget(label)
        kpi_bar.addStretch()
        hint = QLabel("Drag = move (from now)  ·  Ctrl + drag = add a 2nd zone  ·  "
                      "Right-click = remove from zone  ·  Ctrl+Z = undo")
        hint.setStyleSheet("color: #888;")
        kpi_bar.addWidget(hint)
        outer.addLayout(kpi_bar)

        main = QHBoxLayout()
        main.setSpacing(6)
        outer.addLayout(main, 1)

        # ---- tablica (przewijana)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        main.addWidget(scroll, 1)
        board = QWidget()
        board_layout = QVBoxLayout(board)
        board_layout.setContentsMargins(0, 0, 4, 0)
        scroll.setWidget(board)

        for hall in HALLS:
            columns = []
            for dept, grid_columns in (("Reachtruck", 4), ("Orderpicker", 5)):
                zones = [self._position_zone(dept, pos) for pos in SUB_POSITIONS[dept] if hall_of(dept, pos) == hall]
                columns.append(Column(SUB_POSITION_TITLES[dept].upper(), zones, grid_columns))
            self.halls[hall] = HallSection(hall, HALL_COLORS[hall], columns, (4, 5))
            board_layout.addWidget(self.halls[hall])

        inbound = [d for d in TEAM_LIST if d.startswith(INBOUND_PREFIX)]
        other = [d for d in TEAM_LIST
                 if d not in SUB_POSITIONS and d not in SIDE_DEPARTMENTS and d not in inbound]
        shared = [
            Column("INBOUND", [self._department_zone(d) for d in inbound], 1),
            Column("OTHER", [self._department_zone(d) for d in other], 6),
        ]
        self.halls["Both halls"] = HallSection("Both halls", HALL_COLORS["Both halls"], shared, (1, 6))
        board_layout.addWidget(self.halls["Both halls"])
        board_layout.addStretch()

        # ---- panel po prawej
        side = QWidget()
        side.setFixedWidth(250)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(6)
        main.addWidget(side)

        side_layout.addWidget(section_header("UNASSIGNED", "#8e44ad"))
        note = QLabel("Reach without zone · Picking without client.\nDrag a card onto a zone.")
        note.setStyleSheet("color: #888;")
        side_layout.addWidget(note)
        self.unassigned = DropZone("Unassigned", "", "", accepts_drops=False, fit=False)
        self.unassigned.drag_state.connect(self._set_dragging)
        side_layout.addWidget(self.unassigned, 3)

        for dept in SIDE_DEPARTMENTS:
            zone = self._department_zone(dept, fit=False)
            side_layout.addWidget(zone, 1)

        # działy spoza listy (np. nietypowa nazwa z Excela) – tylko do wyciągania
        self.other_zone = DropZone(OTHER_ZONE, "", "", accepts_drops=False, fit=False)
        self.other_zone.drag_state.connect(self._set_dragging)
        side_layout.addWidget(self.other_zone, 1)
        self.other_zone.setVisible(False)

    # ------------------------------------------------------------- budowa
    def _connect(self, zone):
        zone.move_requested.connect(self.move_requested)
        zone.remove_requested.connect(self._remove_from_zone)
        zone.drag_state.connect(self._set_dragging)
        return zone

    def _position_zone(self, dept, position):
        zone = self._connect(DropZone(position, dept, position))
        zone.setMinimumWidth(120)
        self.position_zones[(dept, position)] = zone
        return zone

    def _department_zone(self, dept, fit=True):
        zone = self._connect(DropZone(dept, dept, "", fit=fit))
        zone.setMinimumWidth(120)
        self.zones[dept] = zone
        return zone

    def _remove_from_zone(self, ids, position):
        for emp_id in ids:
            self.toggle_position_requested.emit(emp_id, position)

    def _set_dragging(self, state):
        self.dragging = state

    # --------------------------------------------------------------- dane
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

        in_positions = {key: [] for key in self.position_zones}
        in_zones = {dept: [] for dept in self.zones}
        unassigned, other = [], []

        for emp in employees:
            dept = emp.active_department
            if dept in SUB_POSITIONS:
                placed = False
                for position in emp.positions:
                    if (dept, position) in in_positions:
                        in_positions[(dept, position)].append(emp)
                        placed = True
                if not placed:
                    unassigned.append(emp)
            elif dept in in_zones:
                in_zones[dept].append(emp)
            else:
                other.append(emp)

        for key, zone in self.position_zones.items():
            zone.set_employees(in_positions[key])
        for dept, zone in self.zones.items():
            zone.set_employees(in_zones[dept])
        self.unassigned.set_employees(unassigned, show_department=True)
        self.other_zone.set_employees(other, show_department=True)
        self.other_zone.setVisible(bool(other))

        for hall in self.halls.values():
            hall.update_count()
        self._update_kpis(employees, unassigned)

    def _update_kpis(self, employees, unassigned):
        working = [e for e in employees if e.status not in ("sick", "home")]
        counts = {
            "On shift": len(working),
            "Reach": sum(1 for e in working if e.active_department == "Reachtruck"),
            "Picking": sum(1 for e in working if e.active_department == "Orderpicker"),
            "Inbound": sum(1 for e in working if e.active_department.startswith(INBOUND_PREFIX)),
            "Unassigned": sum(1 for e in unassigned if e.status not in ("sick", "home")),
            "Ziek": sum(1 for e in employees if e.status == "sick"),
            "Naar Huis": sum(1 for e in employees if e.status == "home"),
        }
        counts["Other"] = counts["On shift"] - counts["Reach"] - counts["Picking"] - counts["Inbound"]
        for key, label in self.kpi_labels.items():
            label.setText(f"{key}:  <b>{counts[key]}</b>")
