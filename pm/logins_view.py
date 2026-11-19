"""Widok Loginy: numery 001–299 (kody N…P picking i R…R reach), kto ma który, stan loginu.

Widok niczego sam nie zapisuje – wysyła sygnały, a główne okno zapisuje w bazie.
"""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .db import login_status
from .logic import name_key

COLUMNS = ["Login", "Picking", "Reach", "Person", "Status", "Today", "Note", "Changed", ""]
COL = {name: i for i, name in enumerate(COLUMNS)}
STATUS_TEXT = {"free": "Free", "assigned": "Assigned", "damaged": "Damaged", "blocked": "Blocked"}
STATUS_ICON = {"free": "login_free", "assigned": "login_assigned", "damaged": "login_damaged",
               "blocked": "login_blocked"}
FILTERS = ["all", "free", "assigned", "damaged", "blocked"]
STATUS_COLOR = {"free": "muted", "assigned": "text", "damaged": "warning", "blocked": "danger"}


def status_icon(status):
    """Ikona stanu w kolorze stanu (wolny szary, uszkodzony pomarańczowy, zablokowany czerwony)."""
    return QIcon(theme.tinted_pixmap(STATUS_ICON[status], theme.color(STATUS_COLOR[status])))

HELP_TEXT = """
<h3>Logins – who has which login</h3>
<p>One row per login number 001–299. <b>Picking</b> = N…P code, <b>Reach</b> = R…R code.<br>
<b>Assign…</b> on a free login gives it to a person. A person has one login: giving them another one frees
the old one.<br>
<b>Release</b> frees the login (the person left or got another one).<br>
<b>⋯</b> → <i>Damaged</i> / <i>Blocked</i> (with a reason) – such a login is not given to anyone until it is
set back to <i>OK</i>. Double-click <b>Note</b> to write a remark.<br>
<b>Today</b> ✓ = the person is on the shift shown now.</p>
<p>On <b>Monitoring</b>: right-click a person without a login → <i>Add login…</i>.<br>
<b>Import Inlognamen…</b> loads the old login file once: you see what will happen before anything is saved.
Logins already given are never overwritten.</p>
<p>All changes are in the history (⋯ → History).</p>
"""


def login_codes(number):
    return f"N{number}P", f"R{number}R"


def similar_logins(rows, firstname, lastname):
    """Przypisane loginy, których nazwisko w spisie wygląda na tę samą osobę (inna pisownia),
    np. plan „Ahmad Khalaf" – spis „AHMAD-NICOLAE KHALAF". Najlepsze dopasowania pierwsze."""
    words = set(name_key(firstname, lastname).split())
    last_words = {w for w in name_key(lastname).split() if len(w) >= 3}
    result = []
    for row in rows:
        if not row["name_key"]:
            continue
        other = set(row["name_key"].split())
        if last_words & other:
            result.append((len(words & other), row))
    result.sort(key=lambda item: (-item[0], item[1]["number"]))
    return [row for _, row in result[:5]]


class LoginForPersonDialog(QDialog):
    """Monitoring → „Add login…": ta sama osoba w spisie (inna pisownia) albo nowy, wolny numer."""

    def __init__(self, person, free_numbers, similar, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add login")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>Login for {person}</b>"))
        self.group = QButtonGroup(self)
        self.choices = []

        if similar:
            hint = QLabel("Already in the login list under another spelling?")
            hint.setObjectName("hint")
            layout.addWidget(hint)
            for row in similar:
                radio = QRadioButton(f"Same person:  {row['number']}  –  {row['name']}")
                self.group.addButton(radio)
                layout.addWidget(radio)
                self.choices.append((radio, row["number"], True))

        new_row = QHBoxLayout()
        self.new_radio = QRadioButton("New login:")
        self.group.addButton(self.new_radio)
        new_row.addWidget(self.new_radio)
        self.number_combo = QComboBox()
        for number in free_numbers:
            n_code, r_code = login_codes(number)
            self.number_combo.addItem(f"{number}   ({n_code} / {r_code})", number)
        new_row.addWidget(self.number_combo, 1)
        layout.addLayout(new_row)
        self.choices.append((self.new_radio, None, False))
        self.new_radio.setChecked(True)
        if not free_numbers:
            self.new_radio.setEnabled(False)
            self.number_combo.setEnabled(False)
            if similar:
                self.choices[0][0].setChecked(True)
        self.new_radio.toggled.connect(self.number_combo.setEnabled)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Ok).setEnabled(bool(free_numbers or similar))
        layout.addWidget(buttons)

    def value(self):
        """(numer, ta_sama_osoba)"""
        for radio, number, same in self.choices:
            if radio.isChecked():
                return (number or self.number_combo.currentData()), same
        return None, False


class PersonForLoginDialog(QDialog):
    """Zakładka Loginy → „Assign…": komu dać numer (lista osób bez loginu z pokazywanej zmiany albo wpisane)."""

    def __init__(self, number, people, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Assign login {number}")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        n_code, r_code = login_codes(number)
        layout.addWidget(QLabel(f"<b>Login {number}</b>  ({n_code} / {r_code})  for:"))
        self.name_combo = QComboBox()
        self.name_combo.setEditable(True)
        self.name_combo.setInsertPolicy(QComboBox.NoInsert)
        self.name_combo.addItems(people)
        self.name_combo.setCurrentIndex(-1)
        self.name_combo.lineEdit().setPlaceholderText("First name Last name")
        layout.addWidget(self.name_combo)
        hint = QLabel("The list shows people on this shift without a login. You can also type a name.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self):
        return " ".join(self.name_combo.currentText().split())


class LoginImportDialog(QDialog):
    """Podgląd importu pliku loginów: co zostanie zapisane, co pominięte i dlaczego."""

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import logins – preview")
        self.resize(640, 560)
        layout = QVBoxLayout(self)
        new = sum(1 for r in rows if r["action"] == "new")
        same = sum(1 for r in rows if r["action"] == "same")
        skip = sum(1 for r in rows if r["action"] == "skip")
        layout.addWidget(QLabel(f"<b>{new}</b> new  ·  {same} already the same  ·  {skip} skipped"))

        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(["Login", "Name in the file", "What happens"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        order = {"new": 0, "skip": 1, "same": 2}
        for r, row in enumerate(sorted(rows, key=lambda x: (order[x["action"]], x["number"]))):
            what = {"new": "New", "same": "Already the same"}.get(row["action"], f"Skipped – {row['detail']}")
            for c, text in enumerate((row["number"], row["name"], what)):
                table.setItem(r, c, QTableWidgetItem(text))
        table.setColumnWidth(0, 60)
        table.setColumnWidth(1, 240)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)

        hint = QLabel("Logins already given to someone are never overwritten.")
        hint.setObjectName("hint")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.ok_button = buttons.addButton(f"Import {new} new", QDialogButtonBox.AcceptRole)
        self.ok_button.setEnabled(new > 0)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class LoginsView(QWidget):
    assign_requested = Signal(str, str, bool)        # numer, „Imię Nazwisko", ta sama osoba
    release_requested = Signal(str)                  # numer
    state_requested = Signal(str, str, object)       # numer, ok / damaged / blocked, powód (None = bez zmian)
    note_requested = Signal(str, str)                # numer, uwagi
    import_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.employees = []
        self._signature = None
        self._filling = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        bar = QHBoxLayout()
        self.filter_group = QButtonGroup(self)
        self.filter_buttons = {}
        for key in FILTERS:
            button = QPushButton()
            button.setCheckable(True)
            button.setMinimumHeight(32)
            self.filter_group.addButton(button)
            self.filter_buttons[key] = button
            bar.addWidget(button)
        self.filter_buttons["all"].setChecked(True)
        for button in self.filter_buttons.values():
            button.toggled.connect(lambda on: on and self._rebuild())
        bar.addSpacing(12)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search login or name")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(200)
        self.search.textChanged.connect(lambda _: self._rebuild())
        bar.addWidget(self.search)
        bar.addStretch()

        self.import_button = QPushButton("Import Inlognamen…")
        self.import_button.setMinimumHeight(32)
        self.import_button.setToolTip("Load the old login file (preview before saving)")
        self.import_button.clicked.connect(self.import_requested)
        bar.addWidget(self.import_button)
        self.help_button = QPushButton()
        self.help_button.setObjectName("helpButton")
        self.help_button.setFixedSize(32, 32)
        self.help_button.setIconSize(QSize(20, 20))
        self.help_button.setToolTip("How logins work")
        self.help_button.clicked.connect(lambda: QMessageBox.information(self, "Logins – how it works", HELP_TEXT))
        bar.addWidget(self.help_button)
        layout.addLayout(bar)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setIconSize(QSize(20, 20))
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        for name, width in (("Login", 60), ("Picking", 75), ("Reach", 75), ("Person", 240), ("Status", 120),
                            ("Today", 60), ("Note", 260), ("Changed", 170), ("", 170)):
            self.table.setColumnWidth(COL[name], width)
        header.setStretchLastSection(True)
        layout.addWidget(self.table)
        self.refresh_theme()

    # ------------------------------------------------------------------ dane
    def refresh_theme(self):
        self.help_button.setIcon(theme.icon("help"))
        self._signature = None
        if self.rows:
            self._rebuild()

    def set_data(self, rows, employees):
        self.rows = rows
        self.employees = employees
        signature = (tuple(tuple(r.values()) for r in rows), tuple(sorted(e.login for e in employees if e.login)))
        if signature == self._signature:
            return
        self._signature = signature
        self._rebuild()

    def counts(self):
        result = {key: 0 for key in FILTERS}
        for row in self.rows:
            result[login_status(row)] += 1
            result["all"] += 1
        return result

    def free_numbers(self):
        return [r["number"] for r in self.rows if login_status(r) == "free"]

    def people_without_login(self):
        return sorted({f"{e.firstname} {e.lastname}".strip() for e in self.employees if not e.login},
                      key=str.casefold)

    def shown_numbers(self):
        return [self.table.item(r, COL["Login"]).text() for r in range(self.table.rowCount())]

    def _rebuild(self):
        counts = self.counts()
        for key, button in self.filter_buttons.items():
            button.setText(f"{'All' if key == 'all' else STATUS_TEXT[key]}  {counts[key]}")
            if key != "all":
                button.setIcon(status_icon(key))

        wanted = next(k for k, b in self.filter_buttons.items() if b.isChecked())
        text = self.search.text().strip().casefold()
        today = {e.login for e in self.employees if e.login}
        shown = [r for r in self.rows
                 if (wanted == "all" or login_status(r) == wanted)
                 and (not text or text in r["number"] or text in r["name"].casefold()
                      or text in r["note"].casefold())]

        self._filling = True
        scroll = self.table.verticalScrollBar().value()
        self.table.setRowCount(0)          # bez tego przyciski usuniętych wierszy zostają na ekranie
        self.table.setRowCount(len(shown))
        for r, row in enumerate(shown):
            status = login_status(row)
            n_code, r_code = login_codes(row["number"])
            changed = f"{row['changed']}  {row['changed_by']}".strip()
            values = {"Login": row["number"], "Picking": n_code, "Reach": r_code, "Person": row["name"],
                      "Status": STATUS_TEXT[status], "Today": "✓" if row["number"] in today and row["name"] else "",
                      "Note": row["note"], "Changed": changed}
            for name, value in values.items():
                item = QTableWidgetItem(value)
                if name != "Note":
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if name == "Status":
                    item.setIcon(status_icon(status))
                    if status in ("damaged", "blocked"):
                        item.setForeground(QColor(theme.color(STATUS_COLOR[status])))
                if name in ("Login", "Today"):
                    item.setTextAlignment(Qt.AlignCenter)
                if name in ("Picking", "Reach", "Changed") or (status == "free" and name == "Status"):
                    item.setForeground(QColor(theme.color("muted")))
                self.table.setItem(r, COL[name], item)
            self.table.setCellWidget(r, COL[""], self._row_actions(row, status))
        self.table.verticalScrollBar().setValue(scroll)
        self._filling = False

    def _row_actions(self, row, status):
        """Widoczne przyciski w wierszu: główna akcja + ⋯ (stan loginu, uwagi)."""
        cell = QWidget()
        cell.setObjectName("rowActions")
        layout = QHBoxLayout(cell)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)
        number = row["number"]
        if status == "free":
            main = QPushButton("Assign…")
            main.clicked.connect(lambda: self._assign(number))
        elif status == "assigned":
            main = QPushButton("Release")
            main.clicked.connect(lambda: self._release(number))
        else:
            main = QPushButton("Set OK")
            main.clicked.connect(lambda: self.state_requested.emit(number, "ok", None))
        main.setObjectName("rowButton")
        main.setFixedWidth(84)
        layout.addWidget(main)
        more = QToolButton()
        more.setText("⋯")
        font = QFont(more.font())
        font.setPointSize(13)
        font.setBold(True)
        more.setFont(font)
        more.setFixedWidth(36)
        more.setObjectName("rowButton")
        more.setToolTip("Damaged / blocked / note")
        more.setPopupMode(QToolButton.InstantPopup)
        more.setMenu(self._menu(row, status, more))
        layout.addWidget(more)
        layout.addStretch()
        return cell

    def _menu(self, row, status, parent=None):
        number = row["number"]
        menu = QMenu(parent or self)
        if status == "free":
            menu.addAction("Assign…", lambda: self._assign(number))
        if row["name"]:
            menu.addAction("Release", lambda: self._release(number))
        menu.addSeparator()
        if row["state"] != "damaged":
            menu.addAction(status_icon("damaged"), "Damaged…", lambda: self._set_state(number, "damaged"))
        if row["state"] != "blocked":
            menu.addAction(status_icon("blocked"), "Blocked…", lambda: self._set_state(number, "blocked"))
        if row["state"] != "ok":
            menu.addAction("Set OK", lambda: self.state_requested.emit(number, "ok", None))
        menu.addSeparator()
        menu.addAction("Note…", lambda: self._edit_note(row))
        return menu

    # ---------------------------------------------------------------- akcje
    def _row(self, number):
        return next((r for r in self.rows if r["number"] == number), None)

    def _assign(self, number):
        dialog = PersonForLoginDialog(number, self.people_without_login(), self)
        if dialog.exec() == QDialog.Accepted and dialog.value():
            self.assign_requested.emit(number, dialog.value(), False)

    def _release(self, number):
        row = self._row(number)
        if row and QMessageBox.question(
                self, "Release login", f"Release login {number} ({row['name']})?\n\n"
                                       "The login becomes free and can be given to someone else.") == QMessageBox.Yes:
            self.release_requested.emit(number)

    def _set_state(self, number, state):
        reason, ok = QInputDialog.getText(self, f"Login {number} – {STATUS_TEXT[state].lower()}",
                                          "Reason (shown in Note):", text=(self._row(number) or {}).get("note", ""))
        if ok:
            self.state_requested.emit(number, state, reason)

    def _edit_note(self, row):
        note, ok = QInputDialog.getText(self, f"Login {row['number']} – note", "Note:", text=row["note"])
        if ok:
            self.note_requested.emit(row["number"], note)

    def _on_item_changed(self, item):
        if self._filling or item.column() != COL["Note"]:
            return
        number = self.table.item(item.row(), COL["Login"]).text()
        row = self._row(number)
        if row is not None and item.text().strip() != row["note"]:
            self.note_requested.emit(number, item.text())

    def _on_double_click(self, r, c):
        if c == COL["Note"]:
            return
        row = self._row(self.table.item(r, COL["Login"]).text())
        if row and login_status(row) == "free":
            self._assign(row["number"])

    def _context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        row = self._row(self.table.item(index.row(), COL["Login"]).text())
        if row:
            self._menu(row, login_status(row)).exec(self.table.viewport().mapToGlobal(pos))
