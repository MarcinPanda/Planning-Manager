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

from PySide6.QtCore import (
    QEasingCurve, QEvent, QMimeData, QSettings, QSize, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import QBrush, QColor, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
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
    zones_snapshot,
)
from . import theme
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
<p><b>Move a whole block:</b> grab it by its <b>title</b> and drop it onto another block in the same column
(the blocks you can use lift up). The order is kept on this computer only; ⋯ → <i>Reset board layout</i> = back
to the default. New / renamed zones and halls: ⋯ → <i>Edit zones…</i> (for everyone).</p>
<p><b>Ctrl+Z</b> undoes the last change. Click a hall header to fold it.</p>
"""

MIME_TYPE = "application/x-planning-employee-ids"
ZONE_MIME_TYPE = "application/x-planning-board-zone"
OTHER_ZONE = "Other / unknown"
SIDE_DEPARTMENTS = ("Ziek", "Naar Huis")   # w panelu po prawej, nie na tablicy

STATUS_COLORS = {"sick": ROW_COLOR_SICK, "home": ROW_COLOR_HOME, "late": ROW_COLOR_LATE}
CHIP_COLOR = "#DCEBFF"
CARD_HEIGHT = 22

HALL_COLORS = {"North": "#1f6fb2", "South": "#c06a1b", "Both halls": "#4a5966"}



def login_tooltip(login):
    if not login:
        return "No login (use Import Logins)"
    return f"Login {login}  ·  picking N{login}P  ·  reach R{login}R"


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


def section_header(text, color, icon_name=None):
    """Kolorowy nagłówek z białą ikoną i tekstem (czytelny także bez rozróżniania kolorów)."""
    frame = QFrame()
    frame.setStyleSheet(f"QFrame {{ background-color: {color}; border-radius: 6px; }}"
                        "QLabel { color: #ffffff; font-weight: bold; background: transparent; }")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(8, 5, 8, 5)
    layout.setSpacing(6)
    if icon_name:
        icon_label = QLabel()
        icon_label.setPixmap(theme.white_icon(icon_name).pixmap(18, 18))
        layout.addWidget(icon_label)
    label = QLabel(text)
    layout.addWidget(label, 1)
    frame.label = label
    return frame


class LayoutStore:
    """Ułożenie klocków tablicy zapamiętane na tym komputerze: {kolumna: [nazwy klocków po kolei]}."""

    GROUP = "board_layout"

    def __init__(self):
        self.settings = QSettings("PlanningManager", "PlanningManager")

    def get(self, key):
        try:
            value = json.loads(self.settings.value(f"{self.GROUP}/{key}", "[]") or "[]")
            return [str(v) for v in value] if isinstance(value, list) else []
        except (TypeError, ValueError):
            return []

    def set(self, key, names):
        self.settings.setValue(f"{self.GROUP}/{key}", json.dumps(list(names)))

    def clear(self):
        self.settings.remove(self.GROUP)


class MemoryLayoutStore:
    """To samo w pamięci (testy)."""

    def __init__(self):
        self.data = {}

    def get(self, key):
        return list(self.data.get(key, []))

    def set(self, key, names):
        self.data[key] = list(names)

    def clear(self):
        self.data.clear()


def ordered(names, saved):
    """Kolejność zapamiętana przez użytkownika; nowe strefy (spoza zapamiętanej listy) na końcu."""
    return [n for n in saved if n in names] + [n for n in names if n not in saved]


def move_before(names, title, target):
    """Klocek `title` zajmuje miejsce klocka `target`, reszta się przesuwa."""
    names = list(names)
    if title not in names or target not in names or title == target:
        return names
    index = names.index(target)
    names.remove(title)
    names.insert(index, title)
    return names


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
    zone_moved = Signal(str, str, str)                  # kolumna, przenoszony klocek, klocek docelowy
    zone_drag = Signal(str, str, bool)                  # kolumna, klocek, True = start / False = koniec

    def __init__(self, title, department, position="", accepts_drops=True, fit=True, min_rows=1,
                 show_leave=False, parent=None):
        super().__init__(parent)
        self.title = title
        self.department = department
        self.position = position
        self.accepts_drops = accepts_drops
        self.column_key = ""      # kolumna tablicy (klocek da się przenieść za nagłówek); '' = poza tablicą
        self._press_pos = None
        self._lift_animation = None
        self.fit = fit            # True: wysokość dopasowana do liczby kart (bez przewijania)
        self.min_rows = min_rows
        self.show_leave = show_leave  # Ziek / Naar Huis: godzina wyjścia na karcie

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum if fit else QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("zoneTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(True)   # długie nazwy (Kantel/Consolidatie) w dwóch liniach zamiast ucięcia
        self.title_label.setMinimumWidth(10)
        self.title_label.installEventFilter(self)
        layout.addWidget(self.title_label)

        self.list = EmployeeList(accepts_drops)
        self.list.zone_position = position
        self.list.dropped.connect(
            lambda ids, source, add: self.move_requested.emit(ids, self.department, self.position, source, add)
        )
        self.list.action_requested.connect(lambda action, ids: self.action_requested.emit(action, ids, self.position))
        self.list.drag_state.connect(self.drag_state)
        self.list.hover.connect(self._set_hover)
        layout.addWidget(self.list)
        self._fit_height(0)

    def ids(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    # ------------------------------------------------ przenoszenie klocka za nagłówek
    def enable_block_drag(self, column_key):
        """Klocek tablicy: złapany za nagłówek przenosi się w obrębie kolumny (karty osób działają jak zwykle)."""
        self.column_key = column_key
        self.setAcceptDrops(True)       # karty osób odbiera lista; klocki – ramka (zdarzenie przechodzi wyżej)
        self.title_label.setCursor(Qt.OpenHandCursor)
        self.title_label.setToolTip("Drag the title to move this block")

    def eventFilter(self, obj, event):
        if obj is self.title_label and self.column_key:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._press_pos = event.position().toPoint()
                return True
            if event.type() == QEvent.MouseMove and self._press_pos is not None:
                if (event.position().toPoint() - self._press_pos).manhattanLength() >= \
                        QApplication.startDragDistance():
                    self._press_pos = None
                    self._start_zone_drag()
                return True
            if event.type() == QEvent.MouseButtonRelease:
                self._press_pos = None
        return super().eventFilter(obj, event)

    def set_lift(self, mode):
        """Podpowiedź przy przenoszeniu klocka: 'target' = tu można upuścić (pulsujące podświetlenie ramki),
        'source' = przenoszony klocek (przygaszony), None = zwykły wygląd."""
        if self._lift_animation is not None:
            self._lift_animation.stop()
            self._lift_animation = None
        self.setGraphicsEffect(None)
        self.setStyleSheet("")
        self.setProperty("dropTarget", mode == "target")
        self.style().unpolish(self)
        self.style().polish(self)
        if mode == "source":
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.35)
            self.setGraphicsEffect(effect)
        elif mode == "target":
            accent = QColor(theme.color("accent"))
            animation = QVariantAnimation(self)
            animation.setDuration(1400)
            animation.setStartValue(0.0)
            animation.setKeyValueAt(0.5, 1.0)
            animation.setEndValue(0.0)
            animation.setEasingCurve(QEasingCurve.InOutSine)
            animation.setLoopCount(-1)

            def breathe(value, c=accent):
                # ramka i delikatne tło w kolorze motywu – jaśniej / ciemniej, nic się nie przesuwa
                border = f"rgba({c.red()}, {c.green()}, {c.blue()}, {int(90 + 165 * value)})"
                fill = f"rgba({c.red()}, {c.green()}, {c.blue()}, {int(10 + 40 * value)})"
                self.setStyleSheet(f"DropZone {{ border: 2px solid {border}; border-radius: 8px; background-color: {fill}; }}"
                                   f"DropZone[hover=\"true\"] {{ border: 2px solid rgb({c.red()}, {c.green()},"
                                   f" {c.blue()}); }}")

            breathe(0.0)
            animation.valueChanged.connect(breathe)
            animation.start()
            self._lift_animation = animation

    def _start_zone_drag(self):
        mime = QMimeData()
        mime.setData(ZONE_MIME_TYPE, json.dumps({"column": self.column_key, "title": self.title}).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab().scaledToWidth(min(self.width(), 160), Qt.SmoothTransformation))
        self.drag_state.emit(True)    # bez przebudowy tablicy w trakcie przeciągania
        self.zone_drag.emit(self.column_key, self.title, True)
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self.zone_drag.emit(self.column_key, self.title, False)
            self.drag_state.emit(False)

    def _zone_payload(self, event):
        if not (self.column_key and event.mimeData().hasFormat(ZONE_MIME_TYPE)):
            return None
        try:
            payload = json.loads(bytes(event.mimeData().data(ZONE_MIME_TYPE)).decode("utf-8"))
        except ValueError:
            return None
        if payload.get("column") != self.column_key or payload.get("title") == self.title:
            return None
        return payload

    def dragEnterEvent(self, event):
        if self._zone_payload(event):
            self._set_hover(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._zone_payload(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_hover(False)

    def dropEvent(self, event):
        self._set_hover(False)
        payload = self._zone_payload(event)
        if not payload:
            event.ignore()
            return
        event.acceptProposedAction()
        self.zone_moved.emit(self.column_key, str(payload["title"]), self.title)

    def _set_hover(self, on):
        """Podświetlenie ramki, gdy nad strefą jest przeciągana karta (kolor z motywu)."""
        self.setProperty("hover", bool(on))
        self.style().unpolish(self)
        self.style().polish(self)

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

    def __init__(self, title, zones, grid_columns, icon_name=None, key="", parent=None):
        super().__init__(parent)
        self.title = title
        self.zones = zones
        self.key = key
        if key:
            for zone in zones:
                zone.enable_block_drag(key)
        self.icon_name = icon_name
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        header_row = QHBoxLayout()
        header_row.setSpacing(6)
        self.icon_label = QLabel()
        header_row.addWidget(self.icon_label)
        self.header = QLabel(title)
        self.header.setObjectName("columnHeader")
        header_row.addWidget(self.header, 1)
        layout.addLayout(header_row)
        self.refresh_theme()

        grid = QGridLayout()
        grid.setSpacing(4)
        for index, zone in enumerate(zones):
            grid.addWidget(zone, index // grid_columns, index % grid_columns, Qt.AlignTop)
        for col in range(grid_columns):
            grid.setColumnStretch(col, 1)
        layout.addLayout(grid)
        layout.addStretch()

    def refresh_theme(self):
        if self.icon_name:
            self.icon_label.setPixmap(theme.tinted_pixmap(self.icon_name, theme.color("muted"), 20))

    def update_count(self):
        people = {emp_id for zone in self.zones for emp_id in zone.ids()}
        self.header.setText(f"{self.title}  ({len(people)})")
        return people


class HallSection(QFrame):
    """Hala (North / South / wspólne): zwijany nagłówek i kolumny obok siebie."""

    def __init__(self, title, color, columns, stretches, icon_name=None, parent=None):
        super().__init__(parent)
        self.title = title
        self.columns = columns

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(6)

        self.header = QPushButton()
        self.header.setCheckable(True)
        self.header.setChecked(True)
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.setToolTip("Click to fold / unfold")
        if icon_name:
            self.header.setIcon(theme.white_icon(icon_name))
            self.header.setIconSize(QSize(20, 20))
        style = (f"background-color: {color}; color: #ffffff; font-weight: bold; font-size: 11pt;"
                 " text-align: left; padding: 7px 12px; border: none; border-radius: 7px;")
        self.header.setStyleSheet(f"QPushButton {{ {style} }} QPushButton:checked {{ {style} }}"
                                  f" QPushButton:hover {{ {style} border: 2px solid #ffffff; }}")
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

    def __init__(self, parent=None, layout_store=None):
        super().__init__(parent)
        self.layout_store = layout_store if layout_store is not None else LayoutStore()
        self.board_zones = []     # klocki tablicy (przebudowywane po zmianie stref / ułożenia)
        self.board_body = None
        self._zones_signature = None
        self.columns = []
        self.dragging = False
        self._signature = None
        self.zones = {}           # dział -> DropZone (działy bez stref, także Ziek / Naar Huis)
        self.position_zones = {}  # (dział, strefa) -> DropZone
        self.halls = {}
        self.all_zones = []       # wszystkie strefy z kartami – do jednego zaznaczenia na tablicy
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
            label.setObjectName("kpi")
            label.setAlignment(Qt.AlignCenter)
            self.kpi_labels[key] = label
            kpi_bar.addWidget(label)
        kpi_bar.addStretch()

        self.from_start_button = QPushButton("From start of shift")
        self.from_start_button.setCheckable(True)
        self.from_start_button.setCursor(Qt.PointingHandCursor)
        self.from_start_button.setIconSize(QSize(18, 18))
        self.from_start_button.setToolTip(
            "ON: a drop changes the department from the START of the shift (for changes reported late).\n"
            f"Turns off by itself {FROM_START_WINDOW_MIN} minutes after the shift starts."
        )
        self.from_start_button.setStyleSheet(
            "QPushButton:checked { background-color: #e67e22; color: #000000; font-weight: bold;"
            " border-color: #e67e22; }"
        )
        self.from_start_button.setMinimumWidth(self.from_start_button.fontMetrics().horizontalAdvance(
            self.from_start_button.text()) + 60)
        self.from_start_button.toggled.connect(self._set_from_start)

        kpi_bar.addWidget(self.from_start_button)

        self.help_button = QPushButton()
        self.help_button.setObjectName("helpButton")
        self.help_button.setFixedSize(32, 32)
        self.help_button.setIconSize(QSize(20, 20))
        self.help_button.setToolTip("How the board works")
        self.help_button.clicked.connect(self.show_help)
        kpi_bar.addWidget(self.help_button)
        outer.addLayout(kpi_bar)

        # wyraźny pasek, gdy tryb „od początku zmiany" jest włączony (nie tylko kolor)
        self.from_start_banner = QLabel()
        self.from_start_banner.setStyleSheet(
            "background-color: #e67e22; color: #000; font-weight: bold; font-size: 11pt; padding: 7px 12px;"
            " border-radius: 7px;"
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
        board.setObjectName("board")
        board_layout = QVBoxLayout(board)
        board_layout.setContentsMargins(0, 0, 6, 0)
        board_layout.addStretch()
        scroll.setWidget(board)
        self.board_layout = board_layout

        # ---- panel po prawej
        side = QWidget()
        side.setFixedWidth(205)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(6)
        main.addWidget(side)

        header = section_header("UNASSIGNED", "#8e44ad", "unassigned")
        header.setToolTip("Reach without a zone · Picking without a client. Drag a card onto a zone.")
        side_layout.addWidget(header)
        self.unassigned = DropZone("Unassigned", "", "", accepts_drops=False, fit=False)
        self.unassigned.title_label.setVisible(False)
        self._connect(self.unassigned)
        side_layout.addWidget(self.unassigned, 3)

        self.side_headers = {"Unassigned": header}
        for dept, color, icon_name in (("Ziek", "#c0392b", "sick"), ("Naar Huis", "#5d6d7e", "home")):
            header = section_header(dept.upper(), color, icon_name)
            self.side_headers[dept] = header
            side_layout.addWidget(header)
            zone = self._department_zone(dept, fit=False, show_leave=True)
            zone.title_label.setVisible(False)
            side_layout.addWidget(zone, 2)
            if dept == "Naar Huis":
                self.group_button = QPushButton("Send a group home…")
                self.group_button.setIconSize(QSize(18, 18))
                self.group_button.setToolTip(
                    "Tick many people and set one clock-out time (e.g. the whole shift ends early)")
                self.group_button.clicked.connect(self.group_home_requested)
                side_layout.addWidget(self.group_button)
        self.refresh_theme()

        # działy spoza listy (np. nietypowa nazwa z Excela) – tylko do wyciągania
        self.other_zone = DropZone(OTHER_ZONE, "", "", accepts_drops=False, fit=False)
        self._connect(self.other_zone)
        side_layout.addWidget(self.other_zone, 1)
        self.other_zone.setVisible(False)

        self._build_board()

    # ------------------------------------------------------------- tablica
    def _ordered_zones(self, key, names, make):
        zones = [make(name) for name in ordered(names, self.layout_store.get(key))]
        for zone in zones:
            self.board_zones.append(zone)
            zone.zone_moved.connect(self.move_zone)
            zone.zone_drag.connect(self._show_drop_targets)
        return zones

    def _build_board(self):
        """(Prze)budowa hal i klocków: po zmianie stref (Edit zones…) albo ułożenia (przeniesiony klocek)."""
        folded = {name: not hall.header.isChecked() for name, hall in self.halls.items()}
        for zone in self.board_zones:
            if zone in self.all_zones:
                self.all_zones.remove(zone)
            if zone.position:
                self.position_zones.pop((zone.department, zone.position), None)
            else:
                self.zones.pop(zone.department, None)
        self.board_zones = []
        if self.board_body is not None:
            self.board_body.setParent(None)
            self.board_body.deleteLater()

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        self.columns = []
        self.halls = {}
        for hall in HALLS:
            columns = []
            for dept, grid_columns, icon_name in (("Reachtruck", 4, "reach"), ("Orderpicker", 5, "picking")):
                key = f"{hall}:{dept}"
                names = [pos for pos in SUB_POSITIONS.get(dept, []) if hall_of(dept, pos) == hall]
                zones = self._ordered_zones(key, names, lambda pos, d=dept: self._position_zone(d, pos))
                columns.append(Column(SUB_POSITION_TITLES[dept].upper(), zones, grid_columns, icon_name, key))
            self.columns += columns
            self.halls[hall] = HallSection(hall, HALL_COLORS[hall], columns, (4, 5),
                                           "hall_north" if hall == "North" else "hall_south")
            body_layout.addWidget(self.halls[hall])

        inbound = [d for d in TEAM_LIST if d.startswith(INBOUND_PREFIX)]
        other = [d for d in TEAM_LIST
                 if d not in SUB_POSITIONS and d not in SIDE_DEPARTMENTS and d not in inbound]
        shared = [
            Column("INBOUND", self._ordered_zones("Both:Inbound", inbound, self._department_zone), 1, "inbound",
                   "Both:Inbound"),
            Column("OTHER", self._ordered_zones("Both:Other", other, self._department_zone), 6, "other",
                   "Both:Other"),
        ]
        self.columns += shared
        self.halls["Both halls"] = HallSection("Both halls", HALL_COLORS["Both halls"], shared, (1, 6), "other")
        body_layout.addWidget(self.halls["Both halls"])
        for name, hall in self.halls.items():
            if folded.get(name):
                hall.header.setChecked(False)

        self.board_layout.insertWidget(0, body)
        self.board_body = body
        self._zones_signature = zones_snapshot()
        for column in self.columns:
            column.refresh_theme()

    def zone_order(self, key):
        """Bieżąca kolejność klocków w kolumnie (do testów i zapisu)."""
        column = next((c for c in self.columns if c.key == key), None)
        return [zone.title for zone in column.zones] if column else []

    def move_zone(self, key, title, target):
        self.layout_store.set(key, move_before(self.zone_order(key), title, target))
        QTimer.singleShot(0, self._rebuild)   # nie usuwamy klocka w trakcie obsługi jego upuszczenia

    def reset_layout(self):
        self.layout_store.clear()
        self._rebuild()

    def update_zones(self):
        """Wywoływane po każdym odświeżeniu: strefy zmienione (także na innym komputerze) -> nowa tablica."""
        if zones_snapshot() != self._zones_signature and not self.dragging:
            self._rebuild()

    def _rebuild(self):
        self._build_board()
        self.set_employees(self.employees, force=True)

    def _show_drop_targets(self, key, title, started):
        """Przenoszony klocek przygasa, a klocki tej samej kolumny (tam można go upuścić) się unoszą."""
        for zone in self.board_zones:
            if not started or zone.column_key != key:
                zone.set_lift(None)
            else:
                zone.set_lift("source" if zone.title == title else "target")

    # ------------------------------------------------------------- budowa
    def _connect(self, zone):
        self.all_zones.append(zone)
        zone.list.itemSelectionChanged.connect(lambda z=zone: self._keep_one_selection(z))
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

    def _keep_one_selection(self, zone):
        """Zaznaczenie tylko w jednej strefie naraz na całej tablicy (Ctrl / Shift – kilka osób w tej strefie)."""
        if not zone.list.selectedItems():
            return
        for other in self.all_zones:
            if other is not zone and other.list.selectedItems():
                other.list.blockSignals(True)
                other.list.clearSelection()
                other.list.blockSignals(False)
                other.list.viewport().update()

    def refresh_theme(self):
        """Ikony w kolorach bieżącego motywu (po zmianie jasny / ciemny)."""
        self.from_start_button.setIcon(theme.icon("from_start", checked_key="black"))
        self.help_button.setIcon(theme.icon("help"))
        self.group_button.setIcon(theme.icon("bulk"))
        for column in self.columns:
            column.refresh_theme()

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
