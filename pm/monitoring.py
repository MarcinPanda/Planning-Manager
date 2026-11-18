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
import re
from datetime import datetime, timedelta

from PySide6.QtCore import (
    QEvent, QMimeData, QPointF, QSettings, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import QBrush, QColor, QDrag, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QInputDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .config import (
    EXTRA_INBOUND,
    HIDDEN_DEPARTMENTS,
    FROM_START_WINDOW_MIN,
    POSITION_RENAMES,
    PROTECTED_ZONES,
    HALLS,
    INBOUND_PREFIX,
    ROW_COLOR_HOME,
    ROW_COLOR_LATE,
    ROW_COLOR_SICK,
    SUB_POSITION_TITLES,
    SUB_POSITIONS,
    TEAM_LIST,
    hall_of,
    is_inbound,
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
to the default. <br><b>Add / remove blocks:</b> the gear next to a column title – every block gets a red <b>✕</b> (its people go
to Unassigned) and an empty <b>+</b> block appears at the end. <b>Rename / other hall:</b> right-click the block
title. These changes are for everyone.</p>
<p><b>Ctrl+Z</b> undoes the last change. Click a hall header to fold it.</p>
"""

MIME_TYPE = "application/x-planning-employee-ids"
ZONE_MIME_TYPE = "application/x-planning-board-zone"
OTHER_ZONE = "Other / unknown"
SIDE_DEPARTMENTS = ("Ziek", "Naar Huis")   # w panelu po prawej, nie na tablicy

STATUS_COLORS = {"sick": ROW_COLOR_SICK, "home": ROW_COLOR_HOME, "late": ROW_COLOR_LATE}
CHIP_COLOR = "#DCEBFF"
CARD_HEIGHT = 22
TITLE_SIDE = 14       # odstęp nazwy klocka od boków (miejsce na krzyżyk usuwania)

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


def board_signature():
    """Co decyduje o wyglądzie tablicy: strefy i lista działów (zmiana także z innego komputera)."""
    return zones_snapshot(), tuple(TEAM_LIST), frozenset(EXTRA_INBOUND), frozenset(HIDDEN_DEPARTMENTS)


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


ZONE_CODE = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")


def split_zone_code(title):
    """„Choco (12)" -> ("Choco", "12"): numer zony w systemie (Sturing wpisuje go pracownikowi)."""
    match = ZONE_CODE.match(title)
    return (match.group(1), match.group(2).strip()) if match else (title, "")


def person_pixmap(color, size=12):
    """Mała ikonka ludzika (głowa + ramiona) w kolorze motywu – przy liczbie osób w klocku."""
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(ratio, ratio)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QPointF(size / 2, size * 0.30), size * 0.22, size * 0.22)
    body = QPainterPath()
    body.moveTo(size * 0.12, size * 0.98)
    body.cubicTo(size * 0.12, size * 0.58, size * 0.88, size * 0.58, size * 0.88, size * 0.98)
    body.closeSubpath()
    painter.drawPath(body)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


class ZoneHeader(QWidget):
    """Nagłówek klocka: nazwa, obok ludzik z liczbą osób (zawsze, także 0), pod nazwą [numer zony]."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        name, code = split_zone_code(title)
        self.code = code
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(5)
        outer.addStretch(1)

        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.name_label = QLabel(name.replace("/", "/\u200b"))   # miejsce na złamanie linii po „/"
        self.name_label.setObjectName("zoneTitle")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setMinimumWidth(10)
        texts.addWidget(self.name_label)
        self.code_label = QLabel(f"[{code}]")
        self.code_label.setObjectName("zoneCode")
        self.code_label.setAlignment(Qt.AlignCenter)
        self.code_label.setVisible(bool(code))
        texts.addWidget(self.code_label)
        outer.addLayout(texts)

        people = QWidget()
        people_layout = QHBoxLayout(people)
        people_layout.setContentsMargins(0, 2, 0, 0)
        people_layout.setSpacing(2)
        self.icon_label = QLabel()
        self.count_label = QLabel("0")
        self.count_label.setObjectName("zoneCount")
        people_layout.addWidget(self.icon_label)
        people_layout.addWidget(self.count_label)
        people.setToolTip("Employees in this block")
        outer.addWidget(people, 0, Qt.AlignTop)
        outer.addStretch(1)
        self.refresh_theme()

        self._people = people

    def resizeEvent(self, event):
        """Nazwa łamie się tylko wtedy, gdy obok ludzika z liczbą naprawdę się nie mieści."""
        super().resizeEvent(event)
        text = self.name_label.text().replace("​", "")
        natural = self.name_label.fontMetrics().horizontalAdvance(text) + 4
        margins = self.contentsMargins()
        available = (self.width() - margins.left() - margins.right() - self._people.sizeHint().width()
                     - self.layout().spacing())
        self.name_label.setFixedWidth(max(10, min(natural, available)))

    @property
    def has_code(self):
        return bool(self.code)

    def reserve_code_line(self):
        """Pusty wiersz w miejscu numeru zony – wszystkie klocki kolumny mają wtedy tę samą wysokość."""
        if not self.code:
            self.code_label.setText(" ")
            self.code_label.setVisible(True)

    def set_count(self, count):
        self.count_label.setText(str(count))

    def refresh_theme(self):
        self.icon_label.setPixmap(person_pixmap(theme.color("muted")))


class CloseGlyphButton(QToolButton):
    """Krzyżyk do usuwania klocka, rysowany kreskami: spokojny w kolorze tekstu pomocniczego,
    na czerwono dopiero po najechaniu (jak przyciski zamykania w edytorach)."""

    SIZE = 18

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("removeBlockButton")
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setStyleSheet("QToolButton { background: transparent; border: none; }")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        hovered = self.underMouse()
        if hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(229, 83, 75, 60 if not self.isDown() else 95))
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 4, 4)
        color = QColor("#e5534b") if hovered else QColor(theme.color("muted"))
        pen = QPen(color, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        m = 5.5
        r = self.rect().adjusted(0, 0, -1, -1)
        painter.drawLine(QPointF(r.left() + m, r.top() + m), QPointF(r.right() - m + 1, r.bottom() - m + 1))
        painter.drawLine(QPointF(r.right() - m + 1, r.top() + m), QPointF(r.left() + m, r.bottom() - m + 1))

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class DropZone(QFrame):
    """Jedna strefa tablicy: dział albo strefa / klient wewnątrz działu, z kartami osób."""

    move_requested = Signal(list, str, str, str, bool)  # ids, dział, pozycja, pozycja źródłowa, dołóż
    action_requested = Signal(str, list, str)           # akcja, ids, pozycja tej strefy
    drag_state = Signal(bool)
    zone_moved = Signal(str, str, str)                  # kolumna, przenoszony klocek, klocek docelowy
    zone_drag = Signal(str, str, bool)                  # kolumna, klocek, True = start / False = koniec
    title_menu = Signal(object)                         # prawy klik na nazwie klocka (pozycja na ekranie)
    remove_clicked = Signal()                           # czerwony krzyżyk (tryb edycji kolumny)

    def __init__(self, title, department, position="", accepts_drops=True, fit=True, min_rows=1,
                 show_leave=False, parent=None):
        super().__init__(parent)
        self.title = title
        self.department = department
        self.position = position
        self.accepts_drops = accepts_drops
        self.column_key = ""      # kolumna tablicy (klocek da się przenieść za nagłówek); '' = poza tablicą
        self._press_pos = None
        self._frame_mode = None
        self._hover = False
        self.fit = fit            # True: wysokość dopasowana do liczby kart (bez przewijania)
        self.min_rows = min_rows
        self.show_leave = show_leave  # Ziek / Naar Huis: godzina wyjścia na karcie

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum if fit else QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)

        self.title_label = ZoneHeader(title)   # nazwa, ludzik z liczbą osób, [numer zony]
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

        # czerwony krzyżyk w prawym górnym rogu – widoczny tylko w trybie edycji kolumny
        self.remove_button = CloseGlyphButton(self)
        self.remove_button.setToolTip("Remove this block")
        self.remove_button.clicked.connect(self.remove_clicked)
        self.remove_button.hide()
        self.editing = False
        self.apply_frame()

    def set_editing(self, on, removable=True):
        """Tryb edycji kolumny: niebieska ramka i (gdy wolno usunąć) czerwony krzyżyk."""
        self.editing = on
        self.set_lift("target" if on else None)
        self.remove_button.setVisible(on and removable)
        if not removable:
            self.title_label.setToolTip("Used by the consolidation list / Reflex hours – cannot be removed")
        self._place_remove_button()

    def _place_remove_button(self):
        self.remove_button.move(self.width() - self.remove_button.width() - 3, 3)
        self.remove_button.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_remove_button()

    def ids(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    # ------------------------------------------------ przenoszenie klocka za nagłówek
    def enable_block_drag(self, column_key):
        """Klocek tablicy: złapany za nagłówek przenosi się w obrębie kolumny (karty osób działają jak zwykle)."""
        self.column_key = column_key
        self.setAcceptDrops(True)       # karty osób odbiera lista; klocki – ramka (zdarzenie przechodzi wyżej)
        # stałe miejsce na krzyżyk z trybu edycji – włączenie trybu niczego nie przesuwa
        self.title_label.setContentsMargins(TITLE_SIDE, 0, TITLE_SIDE, 0)
        self.title_label.setCursor(Qt.OpenHandCursor)
        self.title_label.setToolTip("Drag the title to move this block · right-click: rename")
        self.title_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self.title_label.customContextMenuRequested.connect(
            lambda pos: self.title_menu.emit(self.title_label.mapToGlobal(pos)))

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

    def apply_frame(self):
        """Ramka klocka: zawsze 2 px (zmienia się tylko kolor), więc podświetlenie niczego nie przesuwa."""
        lit = self._frame_mode == "target" or self._hover
        self.title_label.refresh_theme()
        color = theme.color("accent") if lit else theme.color("border")
        self.setStyleSheet(f"DropZone {{ background-color: {theme.color('surface')}; border: 2px solid {color};"
                           " border-radius: 8px; }"
                           "QLabel#zoneTitle { font-weight: 700; background: transparent; border: none; }"
                           f"QLabel#zoneCode {{ font-size: 8pt; color: {theme.color('muted')}; background: transparent;"
                           " border: none; }"
                           f"QLabel#zoneCount {{ color: {theme.color('muted')}; font-weight: 600; background: transparent;"
                           " border: none; }"
                           "QLabel { background: transparent; border: none; }"
                           "QListWidget { background: transparent; border: none; }")

    def set_lift(self, mode):
        """Podpowiedź przy przenoszeniu klocka: 'target' = tu można upuścić (niebieska ramka dookoła),
        'source' = przenoszony klocek (przygaszony), None = zwykły wygląd."""
        self.setGraphicsEffect(None)
        self.setProperty("dropTarget", mode == "target")
        self._frame_mode = mode
        self.apply_frame()
        if mode == "source":
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.35)
            self.setGraphicsEffect(effect)

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
        self._hover = bool(on)
        self.apply_frame()

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
        self.title_label.set_count(count)
        self._fit_height(count)


_EMPTY_ZONE_HEIGHT = {}


def empty_zone_height(with_code=False):
    """Wysokość pustego klocka z jednowierszową nazwą (i wierszem [numer zony]) – mierzona na prawdziwym klocku."""
    if with_code not in _EMPTY_ZONE_HEIGHT:
        probe = DropZone("Probe (1)" if with_code else "Probe", "", "")
        probe.enable_block_drag("probe")
        for widget in (probe, probe.title_label, probe.title_label.name_label, probe.title_label.code_label,
                       probe.list):
            widget.ensurePolished()
        _EMPTY_ZONE_HEIGHT[with_code] = probe.sizeHint().height()
        probe.deleteLater()
    return _EMPTY_ZONE_HEIGHT[with_code]


class AddBlockTile(QFrame):
    """Pusty klocek z plusem na końcu kolumny (tryb edycji): kliknięcie = nowy klocek."""

    clicked = Signal()

    def __init__(self, with_code=False, parent=None):
        super().__init__(parent)
        self.setObjectName("addBlockTile")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Add a new block here")
        self.setMinimumWidth(60)
        self.setFixedHeight(empty_zone_height(with_code))
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        self.plus = QLabel("+")
        self.plus.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.plus)
        self.refresh_theme()

    def refresh_theme(self):
        accent = QColor(theme.color("accent"))
        r, g, b = accent.red(), accent.green(), accent.blue()
        self.setStyleSheet(
            f"QFrame#addBlockTile {{ border: 2px solid rgb({r}, {g}, {b}); border-radius: 8px;"
            f" background-color: rgba({r}, {g}, {b}, 28); }}"
            f"QFrame#addBlockTile:hover {{ background-color: rgba({r}, {g}, {b}, 60); }}"
            f"QLabel {{ color: rgb({r}, {g}, {b}); font-size: 22pt; font-weight: 300; background: transparent;"
            " border: none; }")
        glow = QGraphicsDropShadowEffect(self)      # delikatna, nieruchoma poświata
        glow.setColor(QColor(r, g, b, 150))
        glow.setOffset(0, 0)
        glow.setBlurRadius(18)
        self.setGraphicsEffect(glow)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class Column(QFrame):
    """Kolumna tablicy (REACH / PICKING / INBOUND / OTHER): nagłówek + siatka stref."""

    add_requested = Signal(str)                # pusty klocek „+": klucz kolumny
    remove_requested = Signal(str, object)     # czerwony krzyżyk: klucz kolumny, klocek
    edit_toggled = Signal(str, bool)           # zębatka przy nagłówku

    def __init__(self, title, zones, grid_columns, icon_name=None, key="", parent=None):
        super().__init__(parent)
        self.title = title
        self.zones = zones
        self.key = key
        if key:
            for zone in zones:
                zone.enable_block_drag(key)
            if any(zone.title_label.has_code for zone in zones):
                for zone in zones:
                    zone.title_label.reserve_code_line()
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
        header_row.addWidget(self.header)
        self.edit_button = None
        self.add_tile = None
        if key:
            self.edit_button = QToolButton()
            self.edit_button.setObjectName("columnEditButton")
            self.edit_button.setCheckable(True)
            self.edit_button.setCursor(Qt.PointingHandCursor)
            self.edit_button.setIconSize(QSize(16, 16))
            self.edit_button.setFixedSize(24, 24)
            self.edit_button.setToolTip(f"Edit the blocks of {title}: add (+) or remove (✕)")
            self.edit_button.toggled.connect(self.set_editing)
            header_row.addSpacing(2)
            header_row.addWidget(self.edit_button)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        grid = QGridLayout()
        grid.setSpacing(6)
        for index, zone in enumerate(zones):
            grid.addWidget(zone, index // grid_columns, index % grid_columns, Qt.AlignTop)
            zone.remove_clicked.connect(lambda z=zone: self.remove_requested.emit(self.key, z))
        if key:
            # tej samej wysokości co pusty klocek tej kolumny (z wierszem [numer zony], gdy kolumna go ma)
            self.add_tile = AddBlockTile(any(zone.title_label.has_code for zone in zones))
            self.add_tile.clicked.connect(lambda: self.add_requested.emit(self.key))
            index = len(zones)
            grid.addWidget(self.add_tile, index // grid_columns, index % grid_columns, Qt.AlignTop)
            self.add_tile.hide()
        for col in range(grid_columns):
            grid.setColumnStretch(col, 1)
        layout.addLayout(grid)
        layout.addStretch()
        self.refresh_theme()

    @property
    def editing(self):
        return bool(self.edit_button and self.edit_button.isChecked())

    def set_editing(self, on):
        """Tryb edycji: klocki podświetlone z czerwonym krzyżykiem, na końcu pusty klocek „+"."""
        if self.edit_button is None:
            return
        if self.edit_button.isChecked() != on:
            self.edit_button.setChecked(on)      # wywoła tę metodę jeszcze raz
            return
        for zone in self.zones:
            zone.set_editing(on, removable=zone.title not in PROTECTED_ZONES)
        self.add_tile.setVisible(on)
        self.edit_toggled.emit(self.key, on)

    def refresh_theme(self):
        if self.icon_name:
            self.icon_label.setPixmap(theme.tinted_pixmap(self.icon_name, theme.color("muted"), 20))
        if self.edit_button is not None:
            self.edit_button.setIcon(theme.icon("settings"))
        if self.add_tile is not None:
            self.add_tile.refresh_theme()

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
    board_edit_requested = Signal(str, dict)     # dodanie / zmiana / usunięcie klocka (zapis w bazie)

    def __init__(self, parent=None, layout_store=None):
        super().__init__(parent)
        self.layout_store = layout_store if layout_store is not None else LayoutStore()
        self.board_zones = []     # klocki tablicy (przebudowywane po zmianie stref / ułożenia)
        self.board_body = None
        self._zones_signature = None
        self.columns = []
        self.editing_columns = set()   # kolumny w trybie edycji (zostają po przebudowie tablicy)
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
        side.setFixedWidth(195)   # 205 - 5%: więcej miejsca na tablicę
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
            zone.title_menu.connect(lambda pos, z=zone: self._block_menu(z, pos))
        return zones

    def _build_board(self):
        """(Prze)budowa hal i klocków: po zmianie stref (+ Add / prawy klik) albo ułożenia (przeniesiony klocek)."""
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

        inbound = [d for d in TEAM_LIST if is_inbound(d)]
        inbound = [d for d in inbound if d not in HIDDEN_DEPARTMENTS]
        other = [d for d in TEAM_LIST if d not in SUB_POSITIONS and d not in SIDE_DEPARTMENTS
                 and not is_inbound(d) and d not in HIDDEN_DEPARTMENTS]
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
        for column in self.columns:
            column.add_requested.connect(self._add_block)
            column.remove_requested.connect(self._remove_block)
            column.edit_toggled.connect(self._edit_toggled)
            if column.key in self.editing_columns:
                column.set_editing(True)
        self._zones_signature = board_signature()
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
        if board_signature() != self._zones_signature and not self.dragging:
            self._rebuild()

    def _rebuild(self):
        self._build_board()
        self.set_employees(self.employees, force=True)

    # ------------------------------------------- dodawanie / zmiana / usuwanie klocków
    def _add_block(self, key):
        hall, kind = key.split(":", 1)
        if kind in SUB_POSITIONS:
            title = f"{SUB_POSITION_TITLES[kind]} – {hall}"
            name, ok = QInputDialog.getText(self, "New block", f"New zone / client in {title}:")
            name = name.strip()
            if not ok or not name:
                return
            if name in POSITION_RENAMES:
                QMessageBox.warning(self, "New block", f"'{name}' is an old name the program replaces automatically "
                                                       f"('{POSITION_RENAMES[name]}'). Choose another name.")
                return
            self.board_edit_requested.emit("add_zone", {"department": kind, "name": name, "hall": hall})
            return
        from .config import hours_columns
        from .monitoring_dialogs import NewDepartmentDialog
        hidden = sorted((d for d in HIDDEN_DEPARTMENTS if is_inbound(d) == (kind == "Inbound")), key=str.lower)
        dialog = NewDepartmentDialog(kind.upper(), hours_columns(), hidden, self)
        if dialog.exec() != NewDepartmentDialog.Accepted:
            return
        name, column = dialog.values()
        if name:
            self.board_edit_requested.emit("add_department", {"name": name, "group": kind, "hours_column": column})

    def _edit_toggled(self, key, on):
        (self.editing_columns.add if on else self.editing_columns.discard)(key)

    def _block_menu(self, zone, global_pos):
        if not zone.position:
            return
        dept, name = zone.department, zone.position
        menu = QMenu(self)
        rename = menu.addAction("Rename…", lambda: self._rename_block(dept, name))
        other = "South" if hall_of(dept, name) == "North" else "North"
        menu.addAction(f"Move to {other} hall",
                       lambda: self.board_edit_requested.emit("zone_hall", {"department": dept, "name": name,
                                                                            "hall": other}))
        if name in PROTECTED_ZONES:
            rename.setEnabled(False)
        menu.exec(global_pos)

    def _rename_block(self, dept, name):
        new, ok = QInputDialog.getText(self, "Rename block", "New name:", text=name)
        new = new.strip()
        if ok and new and new != name:
            self.board_edit_requested.emit("rename_zone", {"department": dept, "old": name, "new": new})

    def remove_question(self, zone):
        count = len(zone.ids())
        people = f"{count} employee" + ("" if count == 1 else "s")
        text = f"Are you sure you want to remove the block '{zone.title}' containing {people}?"
        if count:
            text += "\n\nThey go to Unassigned."
        return text

    def _remove_block(self, key, zone):
        answer = QMessageBox.question(self, "Remove block", self.remove_question(zone))
        if answer != QMessageBox.Yes:
            return
        if zone.position:
            self.board_edit_requested.emit("remove_zone", {"department": zone.department, "name": zone.position})
        else:
            self.board_edit_requested.emit("hide_department", {"name": zone.department})

    def _show_drop_targets(self, key, title, started):
        """Przenoszony klocek przygasa, a klocki tej samej kolumny (tam można go upuścić) mają niebieską ramkę."""
        for zone in self.board_zones:
            if not started or zone.column_key != key:
                zone.set_lift("target" if zone.editing else None)
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
        for zone in self.all_zones + [self.other_zone] if hasattr(self, "other_zone") else self.all_zones:
            zone.apply_frame()

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
            elif dept in HIDDEN_DEPARTMENTS:
                unassigned.append(emp)     # klocek zdjęty z tablicy – godziny zostają w dziale
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
            "Inbound": sum(1 for e in working if is_inbound(e.active_department)),
            "Unassigned": sum(1 for e in unassigned if e.status not in ("sick", "home")),
            "Ziek": sum(1 for e in employees if e.status == "sick"),
            "Naar Huis": sum(1 for e in employees if e.status == "home"),
        }
        counts["Other"] = counts["On shift"] - counts["Reach"] - counts["Picking"] - counts["Inbound"]
        for key, label in self.kpi_labels.items():
            label.setText(f"{key}:  <b>{counts[key]}</b>")
