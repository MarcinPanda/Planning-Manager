"""Podgląd przed zapisem godzin do pliku Uren_Lijst: co, gdzie i ile – z możliwością poprawek."""
from copy import copy

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import config
from .hours_export import build_changes

SETTINGS_GROUP = "hours_columns"
HEADERS = ["Write", "Person", "In the file as", "Department (plan)", "Column in the file", "Hours", "Note to add",
           "Status"]


def remembered_columns():
    settings = QSettings("PlanningManager", "PlanningManager")
    settings.beginGroup(SETTINGS_GROUP)
    try:
        return {key: settings.value(key) for key in settings.childKeys()}
    finally:
        settings.endGroup()


def remember_columns(choices):
    settings = QSettings("PlanningManager", "PlanningManager")
    settings.beginGroup(SETTINGS_GROUP)
    for department, column in choices.items():
        settings.setValue(department, column)
    settings.endGroup()


HELP = (
    "<b>What happens:</b> the original file is only read. The hours are written to a copy "
    "<i>…_copy.xlsx</i> next to it – only the cells of the people below that are ticked, in the sheet of this "
    "day. Afterwards the copy is compared with the original; anything else changed = the copy is removed.<br>"
    "Check the hours and columns. <b>Split line</b> = divide a person's hours over two columns "
    "(e.g. 2 h Consolidatie + 6 h Kantelen)."
)


class HoursDialog(QDialog):
    def __init__(self, lines, sheet, title, warning="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hours to Excel – preview")
        self.resize(1250, 720)
        self.sheet = sheet
        self.lines = [copy(line) for line in lines]
        self.columns = list(sheet.columns)

        layout = QVBoxLayout(self)
        heading = QLabel(f"<b>{title}</b>")
        layout.addWidget(heading)
        if warning:
            warn = QLabel(f"⚠ {warning}")
            warn.setWordWrap(True)
            warn.setStyleSheet("color: #d9822b; font-weight: bold;")
            layout.addWidget(warn)
        info = QLabel(HELP)
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        for col, width in enumerate([60, 190, 190, 150, 190, 80, 170]):
            self.table.setColumnWidth(col, width)
        layout.addWidget(self.table, 1)

        self.summary = QLabel()
        layout.addWidget(self.summary)

        buttons = QHBoxLayout()
        split = QPushButton("Split line")
        split.clicked.connect(self.split_line)
        buttons.addWidget(split)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.write_button = QPushButton("Write copy")
        self.write_button.setDefault(True)
        self.write_button.clicked.connect(self.try_accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.write_button)
        layout.addLayout(buttons)

        self.rebuild()

    # -------------------------------------------------------------- tabela
    def rebuild(self):
        self.table.setRowCount(len(self.lines))
        for i, line in enumerate(self.lines):
            self._fill_row(i, line)
        self.update_summary()

    def _text(self, row, col, text):
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, col, item)

    def _fill_row(self, i, line):
        holder = QWidget()
        box = QCheckBox()
        box.setChecked(line.include)
        box.setEnabled(line.row is not None)
        box.toggled.connect(lambda checked, ln=line: self._set(ln, "include", checked))
        h = QHBoxLayout(holder)
        h.setContentsMargins(0, 0, 0, 0)
        h.setAlignment(Qt.AlignCenter)
        h.addWidget(box)
        self.table.setCellWidget(i, 0, holder)

        self._text(i, 1, line.person)
        self._text(i, 2, line.excel_name or "—")
        self._text(i, 3, line.department)

        combo = QComboBox()
        combo.addItem("")
        combo.addItems(self.columns)
        combo.setCurrentText(line.column)
        combo.currentTextChanged.connect(lambda text, ln=line: self._set(ln, "column", text))
        self.table.setCellWidget(i, 4, combo)

        spin = QDoubleSpinBox()
        spin.setRange(0, config.HOURS_MAX_PER_PERSON)
        spin.setSingleStep(0.25)
        spin.setDecimals(2)
        spin.setValue(line.hours)
        spin.valueChanged.connect(lambda value, ln=line: self._set(ln, "hours", round(value * 4) / 4))
        self.table.setCellWidget(i, 5, spin)

        note = QLineEdit(line.note)
        note.textChanged.connect(lambda text, ln=line: self._set(ln, "note", text.strip()))
        self.table.setCellWidget(i, 6, note)

        self._text(i, 7, line.status)
        if line.row is None or line.status.startswith("already"):
            item = self.table.item(i, 7)
            item.setForeground(Qt.darkYellow if line.row is not None else Qt.red)

    def _set(self, line, attr, value):
        setattr(line, attr, value)
        self.update_summary()

    def split_line(self):
        index = self.table.currentRow()
        if index < 0:
            QMessageBox.information(self, "Split line", "Select a line first.")
            return
        original = self.lines[index]
        if original.row is None:
            return
        extra = copy(original)
        extra.hours, extra.column, extra.note, extra.status = 0.0, "", "", "split"
        self.lines.insert(index + 1, extra)
        self.rebuild()
        self.table.selectRow(index + 1)

    def update_summary(self):
        chosen = [ln for ln in self.lines if ln.include]
        people = len({ln.row for ln in chosen})
        hours = sum(ln.hours for ln in chosen)
        missing = sum(1 for ln in self.lines if ln.row is None)
        filled = len({ln.row for ln in self.lines if ln.status.startswith("already")})
        text = f"To write: {people} people, {hours:g} h."
        if missing:
            text += f"  Not in the file: {missing} (add them in sheet 'Namen' first)."
        if filled:
            text += f"  Already filled in the file: {filled} (not ticked)."
        self.summary.setText(text)

    # -------------------------------------------------------------- wynik
    def column_choices(self):
        """Wybory kolumn dla działów – zapamiętywane na kolejne razy."""
        choices = {}
        for line in self.lines:
            if line.include and line.column and line.hours and line.status != "split":
                if config.HOURS_COLUMN_MAP.get(line.department) != line.column:
                    choices[line.department] = line.column
        return choices

    def try_accept(self):
        _, _, errors = build_changes(self.lines, self.sheet)
        if errors:
            QMessageBox.warning(self, "Hours to Excel", "Please fix first:\n\n" + "\n".join(errors[:15]))
            return
        if not any(ln.include for ln in self.lines):
            QMessageBox.information(self, "Hours to Excel", "Nothing is ticked.")
            return
        overwrite = [ln.person for ln in self.lines if ln.include and ln.status.startswith("already")]
        if overwrite:
            answer = QMessageBox.question(
                self, "Hours to Excel",
                "These people already have hours in the file; the chosen cells will be replaced:\n\n"
                + "\n".join(sorted(set(overwrite))[:15]) + "\n\nContinue?")
            if answer != QMessageBox.Yes:
                return
        self.accept()
