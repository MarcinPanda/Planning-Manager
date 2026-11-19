"""Widok Consolidatie: lista RIT-ów do konsolidacji z przypisanymi reacherami.

Widok niczego sam nie zapisuje – wysyła sygnały, a główne okno zapisuje w bazie.
Przypisanie reachera do RIT-u (bez „V") daje mu na Monitoringu strefę Kantel/Consolidatie.
"""
from datetime import date

from PySide6.QtCore import QSize, QTime, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .config import CONSOLIDATION_DEPARTMENT, CONSOLIDATION_WORK_DEPARTMENT
from .db import consolidation_zones, employee_token
from .excel_io import parse_reachers

COLUMNS = ["Time", "RIT", "Area", "Amount", "Kantel", "Consol.", "Reacher", "V", "Done", "Lane", "Comment",
           "Who was busy"]
COL = {name: i for i, name in enumerate(COLUMNS)}
EDITABLE_TEXT = {"Time": "time", "Area": "area", "Amount": "amount", "Kantel": "kantel", "Lane": "lane",
                 "Comment": "comment"}

HELP_TEXT = """
<h3>Consolidatie – the RIT list</h3>
<p><b>Reacher</b> – click the cell and tick who drives this RIT. From that moment the reacher is on
<b>Kantel/Consolidatie</b> on Monitoring.<br>
<b>V</b> – tick when the reacher has driven the RIT in. When all their RITs have V, the reacher
goes back to their previous zone.<br>
<b>Done</b> – tick (X) when the consolidation is finished. Done RITs are hidden
(untick <i>Hide done</i> to see them).<br>
<b>Who was busy</b> – click and pick who did the consolidation (people on Consolidatie/Kantelen).<br>
<b>Lane, Comment, Time, pallets</b> – double-click to edit.<br>
Right-click a row: assign / remove reacher, delete RIT.</p>
<p><b>Import Consolidatie</b> loads new RITs from the Excel file; it never overwrites what was
entered here. The Excel file itself is not changed.</p>
"""

COLOR_DRIVEN = "#c8f0d4"     # V – zwiezione
COLOR_DONE = "#d9d9d9"       # V + Done – wszystko zrobione
COLOR_ASSIGNED = "#ffe9a8"   # reacher przypisany, jeszcze wozi


def token_label(token, employees_by_token, login_names):
    emp = employees_by_token.get(token)
    if emp is not None:
        name = f"{emp.firstname} {emp.lastname}"
        return f"{name} [{emp.login}]" if emp.login else name
    if token.startswith("id:"):
        return "(removed employee)"
    name = login_names.get(token)
    return f"{name} [{token}]" if name else f"[{token}]"


class ReacherDialog(QDialog):
    """Wybór reacherów do RIT-u: lista osób z działu Reach + pole na inne loginy."""

    def __init__(self, rit_label, employees, current_tokens, login_names, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Reacher – {rit_label}")
        self.resize(420, 520)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Tick the reacher(s) for this RIT.\n"
                                "They get the Kantel/Consolidatie zone on Monitoring until V is set."))

        self.list = QListWidget()
        layout.addWidget(self.list)

        by_token = {employee_token(e): e for e in employees}
        # RIT zapisany przed nadaniem loginu ma „id:17" – pokazujemy go jako tę osobę (z loginem)
        id_to_token = {f"id:{e.employee_id}": employee_token(e) for e in employees}
        current_tokens = list(dict.fromkeys(id_to_token.get(t, t) for t in current_tokens))
        reach = [e for e in employees
                 if e.active_department == CONSOLIDATION_DEPARTMENT and e.status not in ("sick", "home")]
        reach.sort(key=lambda e: (e.lastname.lower(), e.firstname.lower()))

        shown = set()
        for emp in reach:
            token = employee_token(emp)
            zones = ", ".join(emp.positions) or "no zone"
            label = f"{token_label(token, by_token, login_names)}   ·   {zones}"
            self._add(label, token, token in current_tokens)
            shown.add(token)

        for token in current_tokens:
            if token not in shown:
                emp = by_token.get(token)
                where = (f"now on {emp.active_department}" if emp is not None
                         else "not on today's plan (login only)")
                self._add(token_label(token, by_token, login_names) + f"   ·   {where}", token, True)
                shown.add(token)

        form = QFormLayout()
        self.extra_edit = QLineEdit()
        self.extra_edit.setPlaceholderText("e.g. R052R / 052 (several: separate with /)")
        form.addRow("Other login(s):", self.extra_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add(self, label, token, checked):
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, token)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.list.addItem(item)

    def tokens(self):
        result = [
            self.list.item(i).data(Qt.UserRole)
            for i in range(self.list.count())
            if self.list.item(i).checkState() == Qt.Checked
        ]
        for login in parse_reachers(self.extra_edit.text()):
            if login not in result:
                result.append(login)
        return result


def split_names(text):
    return [n.strip() for n in (text or "").replace(";", ",").replace("/", ",").split(",") if n.strip()]


class BusyPopup(QDialog):
    """Rozwijana lista pod komórką „Who was busy": osoby z działu Consolidatie/Kantelen do zaznaczenia."""

    def __init__(self, employees, current_text, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setMinimumWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        title = QLabel(f"On {CONSOLIDATION_WORK_DEPARTMENT} now:")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        current = split_names(current_text)
        people = sorted(
            (e for e in employees
             if e.active_department == CONSOLIDATION_WORK_DEPARTMENT and e.status not in ("sick", "home")),
            key=lambda e: (e.firstname.lower(), e.lastname.lower()),
        )
        names = [f"{e.firstname} {e.lastname}".strip() for e in people]
        self.list = QListWidget()
        for name in names + [n for n in current if n not in names]:  # wpisani wcześniej, których dziś nie ma
            item = QListWidgetItem(name)
            # bez ItemIsUserCheckable: przełączamy sami w itemClicked (klik w kwadracik albo w nazwisko)
            item.setFlags(Qt.ItemIsEnabled)
            item.setCheckState(Qt.Checked if name in current else Qt.Unchecked)
            self.list.addItem(item)
        if not names:
            hint = QLabel(f"Nobody is on {CONSOLIDATION_WORK_DEPARTMENT} right now.")
            hint.setStyleSheet("color: #888;")
            layout.addWidget(hint)
        self.list.setMaximumHeight(max(60, min(320, self.list.count() * 32 + 12)))
        self.list.itemClicked.connect(self.toggle)
        layout.addWidget(self.list)

        self.other_edit = QLineEdit()
        self.other_edit.setPlaceholderText("Someone else (type a name)")
        self.other_edit.returnPressed.connect(self.accept)
        layout.addWidget(self.other_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        clear = buttons.addButton("Clear", QDialogButtonBox.ResetRole)
        clear.clicked.connect(self._clear)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def toggle(item):
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

    def _clear(self):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.Unchecked)
        self.other_edit.clear()
        self.accept()

    def text(self):
        names = [self.list.item(i).text() for i in range(self.list.count())
                 if self.list.item(i).checkState() == Qt.Checked]
        for name in split_names(self.other_edit.text()):
            if name not in names:
                names.append(name)
        return ", ".join(names)


class AddRitDialog(QDialog):
    def __init__(self, datum, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Add RIT – {datum}")

        form = QFormLayout(self)
        self.rit_edit = QLineEdit()
        self.area_combo = QComboBox()
        self.area_combo.addItems(["noord", "zuid"])
        self.area_combo.setEditable(True)
        self.time_edit = QTimeEdit(QTime.currentTime())
        self.time_edit.setDisplayFormat("HH:mm")
        self.amount_spin = QSpinBox()
        self.amount_spin.setRange(0, 999)
        self.kantel_spin = QSpinBox()
        self.kantel_spin.setRange(0, 999)
        self.comment_edit = QLineEdit()

        form.addRow("RIT:", self.rit_edit)
        form.addRow("Area:", self.area_combo)
        form.addRow("Time:", self.time_edit)
        form.addRow("Amount (pallets):", self.amount_spin)
        form.addRow("Kantel (pallets):", self.kantel_spin)
        form.addRow("Comment:", self.comment_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _accept(self):
        if not self.rit_edit.text().strip():
            QMessageBox.warning(self, "Warning", "Enter the RIT number.")
            return
        if self.kantel_spin.value() > self.amount_spin.value():
            QMessageBox.warning(self, "Warning", "Kantel cannot be more than Amount.")
            return
        self.accept()

    def values(self):
        return {
            "rit": self.rit_edit.text().strip(),
            "area": self.area_combo.currentText().strip(),
            "time": self.time_edit.time().toString("HH:mm"),
            "amount": self.amount_spin.value(),
            "kantel": self.kantel_spin.value(),
            "comment": self.comment_edit.text().strip(),
        }


class ConsolidationView(QWidget):
    update_requested = Signal(int, object)     # id RIT-u, {pole: wartość}
    add_requested = Signal(str, object)        # data, wartości z AddRitDialog
    delete_requested = Signal(list)            # id RIT-ów
    import_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.rows = []
        self.shown_rows = []
        self.employees = []
        self.login_names = {}
        self._signature = None
        self._filling = False
        self.dialog_open = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Date:"))
        self.date_combo = QComboBox()
        self.date_combo.setMinimumWidth(130)
        self.date_combo.currentIndexChanged.connect(lambda _: self._rebuild())
        bar.addWidget(self.date_combo)

        # Jak filtr w oryginalnym pliku: RIT z „X" w Done (konsolidacja zrobiona) znika z listy roboczej
        self.hide_finished = QCheckBox("Hide done (X)")
        self.hide_finished.setChecked(True)
        self.hide_finished.toggled.connect(lambda _: self._rebuild())
        bar.addWidget(self.hide_finished)
        bar.addSpacing(15)

        self.import_button = QPushButton("Import Consolidatie")
        self.import_button.setMinimumHeight(32)
        self.import_button.setToolTip("Load RITs from the Consolidatie Excel file (last days + upcoming)")
        self.import_button.clicked.connect(self.import_requested)
        bar.addWidget(self.import_button)

        self.add_button = QPushButton("Add RIT")
        self.add_button.setMinimumHeight(32)
        self.add_button.clicked.connect(self._add_rit)
        bar.addWidget(self.add_button)

        bar.addSpacing(15)
        self.summary_label = QLabel("")
        bar.addWidget(self.summary_label)
        bar.addStretch()
        self.help_button = QPushButton()
        self.help_button.setObjectName("helpButton")
        self.help_button.setFixedSize(32, 32)
        self.help_button.setIconSize(QSize(20, 20))
        self.help_button.setToolTip("How the consolidation list works")
        self.help_button.clicked.connect(
            lambda: QMessageBox.information(self, "Consolidatie – how it works", HELP_TEXT))
        bar.addWidget(self.help_button)
        layout.addLayout(bar)
        self.refresh_theme()

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.itemChanged.connect(self._on_item_changed)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        for name, width in (("Time", 60), ("RIT", 80), ("Area", 60), ("Amount", 65), ("Kantel", 60),
                            ("Consol.", 60), ("Reacher", 330), ("V", 40), ("Done", 50), ("Lane", 70),
                            ("Comment", 220)):
            self.table.setColumnWidth(COL[name], width)
        header.setStretchLastSection(True)
        layout.addWidget(self.table)

    def refresh_theme(self):
        self.help_button.setIcon(theme.icon("help"))
        self.import_button.setIcon(theme.icon("import"))
        self.add_button.setIcon(theme.icon("consolidation"))

    # ------------------------------------------------------------------ dane
    @property
    def busy(self):
        """Nie przebudowujemy tabeli, gdy ktoś coś w niej edytuje albo ma otwarte okno."""
        return self.dialog_open or self.table.state() == QAbstractItemView.EditingState

    def current_date(self):
        return self.date_combo.currentData() or date.today().isoformat()

    def set_data(self, rows, employees, login_names, force=False):
        signature = (
            [tuple((k, tuple(v) if isinstance(v, list) else v) for k, v in r.items()) for r in rows],
            sorted((e.employee_id, e.login, e.lastname, e.firstname, e.active_department, e.position, e.status)
                   for e in employees),
            tuple(sorted(login_names.items())),
        )
        if not force and signature == self._signature:
            return
        if self.busy:
            return
        self._signature = signature
        self.rows = rows
        self.employees = employees
        self.login_names = login_names
        self._fill_dates()
        self._rebuild()

    def _fill_dates(self):
        today = date.today().isoformat()
        dates = sorted({r["datum"] for r in self.rows} | {today})
        current = self.date_combo.currentData() or today
        self.date_combo.blockSignals(True)
        self.date_combo.clear()
        for d in dates:
            self.date_combo.addItem(f"{d}  (today)" if d == today else d, d)
        self.date_combo.setCurrentIndex(max(0, dates.index(current) if current in dates else dates.index(today)))
        self.date_combo.blockSignals(False)

    def _rebuild(self):
        datum = self.current_date()
        rows = [r for r in self.rows if r["datum"] == datum]
        total_amount = sum(r["amount"] for r in rows)
        total_kantel = sum(r["kantel"] for r in rows)
        open_count = sum(1 for r in rows if not r["v"])
        done_count = sum(1 for r in rows if r["done"])
        unassigned = sum(1 for r in rows if not r["v"] and not r["reachers"])
        self.summary_label.setText(
            f"RITs: {len(rows)}  ·  to drive (no V): {open_count}  ·  without reacher: {unassigned}  ·  "
            f"done: {done_count}  ·  pallets: {total_amount} (Kantel {total_kantel}, "
            f"Consolidatie {total_amount - total_kantel})"
        )
        if self.hide_finished.isChecked():
            rows = [r for r in rows if not r["done"]]
        self.shown_rows = rows

        by_token = {employee_token(e): e for e in self.employees}
        for emp in self.employees:
            if emp.login:
                by_token.setdefault(f"id:{emp.employee_id}", emp)

        self._filling = True
        self.table.setRowCount(len(rows))
        for row_index, r in enumerate(rows):
            reacher_text = ", ".join(token_label(t, by_token, self.login_names) for t in r["reachers"])
            values = {
                "Time": r["time"], "RIT": r["rit"] + (f" ({r['seq']})" if r["seq"] > 1 else ""),
                "Area": r["area"], "Amount": str(r["amount"]), "Kantel": str(r["kantel"]),
                "Consol.": str(r["amount"] - r["kantel"]),
                "Reacher": reacher_text or (r["reacher_text"] and f"? {r['reacher_text']}") or "+ assign",
                "V": "", "Done": "", "Lane": r["lane"], "Comment": r["comment"], "Who was busy": r["busy"],
            }

            if r["v"] and r["done"]:
                color = COLOR_DONE
            elif r["v"]:
                color = COLOR_DRIVEN
            elif r["reachers"]:
                color = COLOR_ASSIGNED
            else:
                color = None

            for name, text in values.items():
                item = QTableWidgetItem(text)
                flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
                if name in EDITABLE_TEXT:
                    flags |= Qt.ItemIsEditable
                if name in ("V", "Done"):
                    flags |= Qt.ItemIsUserCheckable
                    item.setCheckState(Qt.Checked if r["v" if name == "V" else "done"] else Qt.Unchecked)
                item.setFlags(flags)
                if name in ("Amount", "Kantel", "Consol.", "Time"):
                    item.setTextAlignment(Qt.AlignCenter)
                if name == "Who was busy":
                    item.setToolTip(f"Click to pick who did it (people on {CONSOLIDATION_WORK_DEPARTMENT})")
                    if not r["busy"]:
                        item.setText("+ pick")
                        item.setForeground(QBrush(QColor("#888")))
                if name == "Reacher":
                    zones = ", ".join(consolidation_zones(r["amount"], r["kantel"]))
                    item.setToolTip(f"Click to assign reacher(s). Zone on Monitoring: {zones}")
                    if not r["reachers"]:
                        item.setForeground(QBrush(QColor("#888")))
                if color:
                    item.setBackground(QBrush(QColor(color)))
                    placeholder = (name == "Reacher" and not r["reachers"]) or (name == "Who was busy" and not r["busy"])
                    if not placeholder:
                        item.setForeground(QBrush(QColor("#000")))
                self.table.setItem(row_index, COL[name], item)
        self._filling = False

    # ------------------------------------------------------------- akcje
    def row_data(self, row):
        return self.shown_rows[row] if 0 <= row < len(self.shown_rows) else None

    def _on_cell_clicked(self, row, col):
        if col == COL["Reacher"]:
            self.edit_reachers(row)
        elif col == COL["Who was busy"]:
            self.edit_busy(row)

    def edit_busy(self, row):
        r = self.row_data(row)
        if r is None:
            return
        popup = BusyPopup(self.employees, r["busy"], self)
        rect = self.table.visualRect(self.table.model().index(row, COL["Who was busy"]))
        popup.move(self.table.viewport().mapToGlobal(rect.bottomLeft()))
        self.dialog_open = True
        try:
            accepted = popup.exec() == QDialog.Accepted
        finally:
            self.dialog_open = False
        if accepted:
            text = popup.text()
            if text != r["busy"]:
                self.update_requested.emit(r["id"], {"busy": text})

    def edit_reachers(self, row):
        r = self.row_data(row)
        if r is None:
            return
        dialog = ReacherDialog(f"RIT {r['rit']} ({r['time']})", self.employees, r["reachers"], self.login_names, self)
        self.dialog_open = True
        try:
            accepted = dialog.exec() == QDialog.Accepted
        finally:
            self.dialog_open = False
        if accepted:
            tokens = dialog.tokens()
            if tokens != r["reachers"]:
                self.update_requested.emit(r["id"], {"reachers": tokens})

    def _on_item_changed(self, item):
        if self._filling:
            return
        r = self.row_data(item.row())
        if r is None:
            return
        name = COLUMNS[item.column()]
        if name in ("V", "Done"):
            key = "v" if name == "V" else "done"
            checked = item.checkState() == Qt.Checked
            if checked != r[key]:
                self.update_requested.emit(r["id"], {key: checked})
        elif name in EDITABLE_TEXT:
            key = EDITABLE_TEXT[name]
            text = item.text().strip()
            if key in ("amount", "kantel"):
                if not text.isdigit():
                    QMessageBox.warning(self, "Warning", "Enter a whole number.")
                    self._rebuild()
                    return
                text = int(text)
            if text != r[key]:
                self.update_requested.emit(r["id"], {key: text})

    def _add_rit(self):
        dialog = AddRitDialog(self.current_date(), self)
        self.dialog_open = True
        try:
            accepted = dialog.exec() == QDialog.Accepted
        finally:
            self.dialog_open = False
        if accepted:
            self.add_requested.emit(self.current_date(), dialog.values())

    def selected_ids(self):
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return [self.shown_rows[r]["id"] for r in rows if r < len(self.shown_rows)]

    def _context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        if row not in {i.row() for i in self.table.selectionModel().selectedRows()}:
            self.table.selectRow(row)
        menu = QMenu(self)
        menu.addAction("Assign reacher...", lambda: self.edit_reachers(row))
        menu.addAction("Remove reacher(s)", lambda: self._clear_reachers(row))
        menu.addSeparator()
        menu.addAction("Delete RIT", self._delete_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _clear_reachers(self, row):
        r = self.row_data(row)
        if r is not None and r["reachers"]:
            self.update_requested.emit(r["id"], {"reachers": []})

    def _delete_selected(self):
        ids = self.selected_ids()
        if not ids:
            return
        reply = QMessageBox.question(self, "Confirm", f"Delete {len(ids)} RIT(s) from the list?")
        if reply == QMessageBox.Yes:
            self.delete_requested.emit(ids)
