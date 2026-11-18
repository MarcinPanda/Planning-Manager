"""Okienka tablicy Monitoring: Naar Huis / Ziek, zmiana godziny, wysyłanie grupy do domu, wybór stref."""
from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QTimeEdit,
    QVBoxLayout,
)

from .config import HALLS, SUB_POSITIONS, SUB_POSITION_TITLES, hall_of

KIND_TITLES = {"home": "Naar Huis (going home)", "sick": "Ziek (sick)"}


def _time_edit(value=None):
    edit = QTimeEdit(value or QTime.currentTime())
    edit.setDisplayFormat("HH:mm")
    edit.setMinimumHeight(30)
    edit.setMinimumWidth(110)
    edit.setStyleSheet("font-size: 15px;")
    return edit


def _hint(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #888;")
    return label


class LeaveDialog(QDialog):
    """Naar Huis / Ziek dla jednej lub kilku osób: od godziny (odbicie) albo cały dzień."""

    def __init__(self, kind, names, all_day_default=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(KIND_TITLES[kind])
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)

        who = ", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else "")
        title = QLabel(f"<b>{KIND_TITLES[kind]}</b><br>{who}")
        title.setWordWrap(True)
        layout.addWidget(title)

        self.at_time = QRadioButton("From this time (clock-out time):")
        self.all_day = QRadioButton(
            "Whole day – did not come to work (0 h)" if kind == "home" else "Sick from the start – did not come (0 h)"
        )
        group = QButtonGroup(self)
        group.addButton(self.at_time)
        group.addButton(self.all_day)

        row = QHBoxLayout()
        row.addWidget(self.at_time)
        self.time_edit = _time_edit()
        row.addWidget(self.time_edit)
        row.addStretch()
        layout.addLayout(row)
        layout.addWidget(self.all_day)
        layout.addWidget(_hint("Hours are counted until this time. If the real clock-out time is different, "
                               "change it later: right-click the card → Change time."))

        (self.all_day if all_day_default else self.at_time).setChecked(True)
        self.at_time.toggled.connect(self.time_edit.setEnabled)
        self.time_edit.setEnabled(self.at_time.isChecked())

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        """(godzina 'HH:MM', cały_dzień)"""
        return self.time_edit.time().toString("HH:mm"), self.all_day.isChecked()


class TimeDialog(QDialog):
    def __init__(self, title, text, value=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.time_edit = _time_edit(value)
        layout.addWidget(self.time_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self):
        return self.time_edit.time().toString("HH:mm")


def department_group(emp):
    dept = emp.active_department
    if dept in SUB_POSITION_TITLES:
        return SUB_POSITION_TITLES[dept]
    return "Inbound" if dept.startswith("Inbound") else "Other"


class GroupHomeDialog(QDialog):
    """Wysłanie wielu osób naraz do domu z jedną godziną (np. cała zmiana kończy wcześniej)."""

    def __init__(self, employees, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Send a group home")
        self.resize(460, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Send a group home</b> – tick the people, set one clock-out time."))

        bar = QHBoxLayout()
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "Reach", "Picking", "Inbound", "Other"])
        self.filter_combo.currentTextChanged.connect(self._apply_filter)
        bar.addWidget(QLabel("Show:"))
        bar.addWidget(self.filter_combo)
        bar.addStretch()
        for text, state in (("Tick shown", Qt.Checked), ("Untick all", Qt.Unchecked)):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, s=state: self._set_all(s))
            bar.addWidget(button)
        layout.addLayout(bar)

        self.list = QListWidget()
        working = [e for e in employees if e.status not in ("home", "sick")]
        for emp in sorted(working, key=lambda e: (department_group(e), e.lastname.casefold())):
            item = QListWidgetItem(
                f"{emp.login + ' – ' if emp.login else ''}{emp.firstname} {emp.lastname}   ·  "
                f"{emp.active_department}   ·  {emp.work_hours}"
            )
            item.setData(Qt.UserRole, emp.employee_id)
            item.setData(Qt.UserRole + 1, department_group(emp))
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list.addItem(item)
        self.list.itemClicked.connect(
            lambda item: item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
        )
        self.list.itemChanged.connect(lambda _: self._update_count())
        layout.addWidget(self.list)

        row = QHBoxLayout()
        row.addWidget(QLabel("Clock-out time:"))
        self.time_edit = _time_edit()
        row.addWidget(self.time_edit)
        row.addStretch()
        self.count_label = QLabel()
        row.addWidget(self.count_label)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Send home")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_count()

    def _apply_filter(self, text):
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(text != "All" and item.data(Qt.UserRole + 1) != text)

    def _set_all(self, state):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if state == Qt.Unchecked or not item.isHidden():
                item.setCheckState(state)

    def _update_count(self):
        self.count_label.setText(f"Selected: {len(self.selected_ids())}")

    def selected_ids(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]

    def value(self):
        return self.time_edit.time().toString("HH:mm")


class ZonePickerDialog(QDialog):
    """Kilka stref / klientów naraz (autoryzacje) – ptaszki pogrupowane według hal."""

    def __init__(self, emp, parent=None):
        super().__init__(parent)
        dept = emp.active_department
        self.setWindowTitle(f"Zones – {emp.firstname} {emp.lastname}")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{emp.firstname} {emp.lastname}</b> – {SUB_POSITION_TITLES.get(dept, dept)}: "
                                "tick every zone / client this person works on now."))
        current = set(emp.positions)
        self.boxes = []
        for hall in HALLS:
            group = QGroupBox(hall)
            grid = QGridLayout(group)
            positions = [p for p in SUB_POSITIONS.get(dept, []) if hall_of(dept, p) == hall]
            for i, position in enumerate(positions):
                box = QCheckBox(position)
                box.setChecked(position in current)
                grid.addWidget(box, i // 3, i % 3)
                self.boxes.append(box)
            layout.addWidget(group)
        # strefy spoza listy (np. stara nazwa) – żeby ich nie zgubić
        known = set(SUB_POSITIONS.get(dept, []))
        self.unknown = [p for p in emp.positions if p not in known]
        if self.unknown:
            layout.addWidget(_hint("Kept (not on the board): " + ", ".join(self.unknown)))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def positions(self):
        return [b.text() for b in self.boxes if b.isChecked()] + self.unknown



class NewDepartmentDialog(QDialog):
    """„+" przy INBOUND / OTHER: nowy dział – nazwa i kolumna w pliku godzin (Uren_Lijst)."""

    ASK_LATER = "– choose when writing hours –"

    def __init__(self, column_title, hours_columns, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"New block in {column_title}")
        layout = QGridLayout(self)
        layout.addWidget(QLabel("Name:"), 0, 0)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Inbound 6")
        layout.addWidget(self.name_edit, 0, 1)
        layout.addWidget(QLabel("Hours go to column\n(hours file):"), 1, 0)
        self.column_combo = QComboBox()
        self.column_combo.addItem(self.ASK_LATER, "")
        for column in hours_columns:
            self.column_combo.addItem(column, column)
        layout.addWidget(self.column_combo, 1, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, 2, 0, 1, 2)
        self.setMinimumWidth(420)

    def values(self):
        return self.name_edit.text().strip(), self.column_combo.currentData() or ""
