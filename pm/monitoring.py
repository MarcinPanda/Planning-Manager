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
from datetime import datetime, timedelta

from PySide6.QtCore import QMimeData, QSize, Qt, QTimer, Signal
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
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .config import (
    FROM_START_WINDOW_MIN,
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
from .db import shift_start_minutes

HELP_TEXT = """
<h3>Monitoring – who is where right now</h3>
<p><b>Move someone:</b> drag their card onto another zone or department. The change counts
<b>from now</b>.<br>
<b>Several people:</b> Ctrl / Shift + click, then drag them together.<br>
<b>Second zone / client at the same time:</b> hold <b>Ctrl</b> while dropping, or right-click →
<i>Zones / clients…</i> and tick all of them. A card with <b>(+2)</b> works in 2 more zones.<br>
<b>Remove from a zone:</b> right-click → <i>Remove from …</i>.</p>
<p><b>Naar Huis / Ziek:</b> drop the card there (or right-click). Enter the <b>clock-out time</b>, or
choose <i>whole day</i> if the person did not come. Hours count until that time.<br>
Wrong time? Right-click the card → <i>Change time…</i>. Mistake? → <i>Back to work</i>.<br>
<b>Whole shift ends early:</b> <i>Send a group home…</i> under Naar Huis.</p>
<p><b>⏮ From start of shift:</b> for changes the helpdesk hears about late (e.g. someone was on
another department since the start). While it is ON (orange bar), a drop changes the department
from the start of the shift. It switches off by itself 30 minutes after the shift starts.</p>
<p><b>Ctrl+Z</b> undoes the last change. Click a hall header to fold it.</p>
"""

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


def card_text(emp, show_department=False, show_leave=False):
    """„095 – Bruno Carvalho Azevedo" (+ ile jeszcze stref, godzina wyjścia przy Ziek / Naar Huis).
    Za długi tekst lista skraca „…" na końcu; pełne dane są w podpowiedzi."""
    name = f"{emp.firstname} {emp.lastname}".strip()
    text = f"{emp.login} – {name}" if emp.login else name
    if show_leave:
        text += f"   ·  {emp.active_since or 'all day'}"
    if show_department:
        text += f"   ·  {SUB_POSITION_TITLES.get(emp.active_department, emp.active_department)}"
    elif emp.active_department in SUB_POSITIONS and len(emp.positions) > 1:
        text = f"[+{len(emp.positions) - 1}] {text}"   # pracuje też w innych strefach (na początku – nie znika w „…")
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
    action_requested = Signal(str, list)  # akcja z menu pod prawym klikiem, id pracowników
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
        if item is None:
            return
        if not item.isSelected():
            self.clearSelection()
            item.setSelected(True)
        items = self.selectedItems() or [item]
        ids = [i.data(Qt.UserRole) for i in items]
        statuses = {i.data(Qt.UserRole + 1) for i in items}
        has_zones = {i.data(Qt.UserRole + 2) for i in items}

        menu = QMenu(self)
        if statuses <= {"home", "sick"}:
            menu.addAction("Change time…", lambda: self.action_requested.emit("time", ids))
            menu.addAction("Back to work", lambda: self.action_requested.emit("back", ids))
        else:
            if len(ids) == 1 and True in has_zones:
                menu.addAction("Zones / clients…", lambda: self.action_requested.emit("zones", ids))
            if self.zone_position:
                menu.addAction(f"Remove from {self.zone_position}", lambda: self.action_requested.emit("remove", ids))
            menu.addSeparator()
            menu.addAction("Naar Huis (going home)…", lambda: self.action_requested.emit("home", ids))
            menu.addAction("Ziek (sick)…", lambda: self.action_requested.emit("sick", ids))
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
    action_requested = Signal(str, list, str)           # akcja, ids, pozycja tej strefy
    drag_state = Signal(bool)

    def __init__(self, title, department, position="", accepts_drops=True, fit=True, min_rows=1,
                 show_leave=False, parent=None):
        super().__init__(parent)
        self.title = title
        self.department = department
        self.position = position
        self.fit = fit            # True: wysokość dopasowana do liczby kart (bez przewijania)
        self.min_rows = min_rows
        self.show_leave = show_leave  # Ziek / Naar Huis: godzina wyjścia na karcie

        self.setStyleSheet(ZONE_STYLE)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum if fit else QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("zoneTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(True)   # długie nazwy (Kantel/Consolidatie) w dwóch liniach zamiast ucięcia
        self.title_label.setMinimumWidth(10)
        layout.addWidget(self.title_label)

        self.list = EmployeeList(accepts_drops)
        self.list.zone_position = position
        self.list.dropped.connect(
            lambda ids, source, add: self.move_requested.emit(ids, self.department, self.position, source, add)
        )
        self.list.action_requested.connect(lambda action, ids: self.action_requested.emit(action, ids, self.position))
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

        if self.show_leave:
            key = lambda e: (e.active_since or "", e.firstname.casefold(), e.lastname.casefold())  # noqa: E731
        else:
            key = lambda e: (e.firstname.casefold(), e.lastname.casefold())  # noqa: E731
        for emp in sorted(employees, key=key):
            item = QListWidgetItem(card_text(emp, show_department, self.show_leave))
            item.setSizeHint(QSize(10, CARD_HEIGHT))
            item.setData(Qt.UserRole, emp.employee_id)
            item.setData(Qt.UserRole + 1, emp.status)
            item.setData(Qt.UserRole + 2, emp.active_department in SUB_POSITIONS)
            item.setBackground(QBrush(QColor(STATUS_COLORS.get(emp.status, CHIP_COLOR))))
            item.setForeground(QBrush(QColor("#000000")))
            item.setToolTip(employee_tooltip(emp))

            if emp.status in ("home", "sick"):
                # z Ziek / Naar Huis nie przeciągamy – prawy klik: Change time / Back to work
                item.setFlags(item.flags() & ~Qt.ItemIsDragEnabled)

            self.list.addItem(item)

        count = len(employees)
        title = self.title.replace("/", "/​")   # miejsce na złamanie linii po „/"
        self.title_label.setText(f"{title}  ({count})" if count else title)
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
    leave_requested = Signal(list, str)          # ids, 'home' / 'sick' (upuszczenie albo menu)
    action_requested = Signal(str, list)         # 'time' / 'back' / 'zones', ids
    group_home_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.dragging = False
        self._signature = None
        self.zones = {}           # dział -> DropZone (działy bez stref, także Ziek / Naar Huis)
        self.position_zones = {}  # (dział, strefa) -> DropZone
        self.halls = {}
        self.employees = []
        self.from_start_deadline = None   # datetime: kiedy tryb „od początku zmiany" sam się wyłączy

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # ---- pasek liczników + tryb „od początku zmiany" + pomoc
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

        self.from_start_button = QPushButton("⏮  From start of shift")
        self.from_start_button.setCheckable(True)
        self.from_start_button.setCursor(Qt.PointingHandCursor)
        self.from_start_button.setToolTip(
            "ON: a drop changes the department from the START of the shift (for changes reported late).\n"
            f"Turns off by itself {FROM_START_WINDOW_MIN} minutes after the shift starts."
        )
        self.from_start_button.setStyleSheet(
            "QPushButton { padding: 5px 12px; border-radius: 4px; }"
            "QPushButton:checked { background-color: #e67e22; color: #000; font-weight: bold; }"
        )
        self.from_start_button.setMinimumWidth(self.from_start_button.fontMetrics().horizontalAdvance(
            self.from_start_button.text()) + 40)
        self.from_start_button.toggled.connect(self._set_from_start)
        kpi_bar.addWidget(self.from_start_button)

        help_button = QPushButton("?")
        help_button.setFixedSize(30, 30)
        help_button.setToolTip("How the board works")
        help_button.setStyleSheet("QPushButton { border-radius: 15px; font-weight: bold; font-size: 15px; }")
        help_button.clicked.connect(self.show_help)
        kpi_bar.addWidget(help_button)
        outer.addLayout(kpi_bar)

        # wyraźny pasek, gdy tryb „od początku zmiany" jest włączony (nie tylko kolor)
        self.from_start_banner = QLabel()
        self.from_start_banner.setStyleSheet(
            "background-color: #e67e22; color: #000; font-weight: bold; font-size: 14px; padding: 6px 10px;"
            " border-radius: 3px;"
        )
        self.from_start_banner.setVisible(False)
        outer.addWidget(self.from_start_banner)
        self.from_start_timer = QTimer(self)
        self.from_start_timer.timeout.connect(self._check_from_start)
        self.from_start_timer.start(20_000)

        main = QHBoxLayout()
        main.setSpacing(6)
        outer.addLayout(main, 1)

        # ---- tablica (przewijana tylko w pionie – szerokość zawsze mieści się w oknie)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
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
        side.setFixedWidth(205)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(6)
        main.addWidget(side)

        header = section_header("UNASSIGNED", "#8e44ad")
        header.setToolTip("Reach without a zone · Picking without a client. Drag a card onto a zone.")
        side_layout.addWidget(header)
        self.unassigned = DropZone("Unassigned", "", "", accepts_drops=False, fit=False)
        self._connect(self.unassigned)
        side_layout.addWidget(self.unassigned, 3)

        for dept, color in (("Ziek", "#c0392b"), ("Naar Huis", "#5d6d7e")):
            side_layout.addWidget(section_header(dept.upper(), color))
            zone = self._department_zone(dept, fit=False, show_leave=True)
            zone.title_label.setVisible(False)
            side_layout.addWidget(zone, 2)
            if dept == "Naar Huis":
                group = QPushButton("Send a group home…")
                group.setToolTip("Tick many people and set one clock-out time (e.g. the whole shift ends early)")
                group.clicked.connect(self.group_home_requested)
                side_layout.addWidget(group)

        # działy spoza listy (np. nietypowa nazwa z Excela) – tylko do wyciągania
        self.other_zone = DropZone(OTHER_ZONE, "", "", accepts_drops=False, fit=False)
        self._connect(self.other_zone)
        side_layout.addWidget(self.other_zone, 1)
        self.other_zone.setVisible(False)

    # ------------------------------------------------------------- budowa
    def _connect(self, zone):
        if zone.department in SIDE_DEPARTMENTS:
            kind = "home" if zone.department == "Naar Huis" else "sick"
            zone.move_requested.connect(lambda ids, *_: self.leave_requested.emit(ids, kind))
        else:
            zone.move_requested.connect(self.move_requested)
        zone.action_requested.connect(self._on_action)
        zone.drag_state.connect(self._set_dragging)
        return zone

    def _position_zone(self, dept, position):
        zone = self._connect(DropZone(position, dept, position))
        zone.setMinimumWidth(60)
        self.position_zones[(dept, position)] = zone
        return zone

    def _department_zone(self, dept, fit=True, show_leave=False):
        zone = self._connect(DropZone(dept, dept, "", fit=fit, show_leave=show_leave))
        zone.setMinimumWidth(60)
        self.zones[dept] = zone
        return zone

    def _on_action(self, action, ids, position):
        if action == "remove":
            for emp_id in ids:
                self.toggle_position_requested.emit(emp_id, position)
        elif action in ("home", "sick"):
            self.leave_requested.emit(ids, action)
        else:
            self.action_requested.emit(action, ids)

    def _set_dragging(self, state):
        self.dragging = state

    # ------------------------------------------------- tryb „od początku zmiany"
    @property
    def from_start(self):
        return self.from_start_button.isChecked()

    def _set_from_start(self, on):
        if on:
            now = datetime.now()
            start = shift_start_minutes(self.employees)
            deadline = None
            if start is not None:
                deadline = now.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)
                if deadline - now > timedelta(hours=12):      # start zmiany był wczoraj
                    deadline -= timedelta(days=1)
                deadline += timedelta(minutes=FROM_START_WINDOW_MIN)
            if deadline is None or deadline <= now:
                deadline = now + timedelta(minutes=10)         # włączony później: działa jeszcze 10 min
            self.from_start_deadline = deadline
            self.from_start_banner.setText(
                "⏮  FROM START OF SHIFT is ON – a drop changes the department from the start of the shift.  "
                f"Turns off automatically at {deadline:%H:%M}."
            )
        else:
            self.from_start_deadline = None
        self.from_start_banner.setVisible(on)

    def _check_from_start(self):
        if self.from_start and self.from_start_deadline and datetime.now() >= self.from_start_deadline:
            self.from_start_button.setChecked(False)

    def show_help(self):
        QMessageBox.information(self, "Monitoring – how it works", HELP_TEXT)

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
        self.employees = list(employees)

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
