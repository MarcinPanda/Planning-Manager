"""Okna dialogowe."""
from datetime import datetime

from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QItemDelegate,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    Property,
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QThread,
    QTimer,
    Signal,
    Slot,
)

from .config import DAY8TO17_BREAKS, MIDDAG_BREAKS, OCHTEND_BREAKS, SHIFT_LIST, TEAM_LIST
from .logic import (
    Validator,
    adjust_work_hours,
    compute_hours_with_breaks,
    format_name,
    get_scheduled_start_time,
    move_lastname_prefix_to_firstname,
    to_minutes,
)


class AddEmployeeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.result_data = None

        self.setWindowTitle("Add Employee")
        self.setGeometry(300, 300, 470, 180)

        self.initUI()

    def initUI(self):
        layout = QGridLayout(self)

        layout.addWidget(QLabel("Last Name:"), 0, 0)
        self.lastname_edit = QLineEdit()
        layout.addWidget(self.lastname_edit, 0, 1)

        layout.addWidget(QLabel("First Name:"), 0, 2)
        self.firstname_edit = QLineEdit()
        layout.addWidget(self.firstname_edit, 0, 3)

        layout.addWidget(QLabel("Department:"), 1, 0)
        self.dept_combo = QComboBox()
        self.dept_combo.addItems(TEAM_LIST)
        layout.addWidget(self.dept_combo, 1, 1)

        layout.addWidget(QLabel("Shift:"), 1, 2)
        self.shift_combo = QComboBox()
        self.shift_combo.addItems(SHIFT_LIST)
        layout.addWidget(self.shift_combo, 1, 3)

        layout.addWidget(QLabel("Work Hours:"), 2, 0)
        self.work_hours_edit = QLineEdit()
        self.work_hours_edit.setReadOnly(True)
        layout.addWidget(self.work_hours_edit, 2, 1)

        layout.addWidget(QLabel("Break 1:"), 2, 2)
        self.break1_edit = QLineEdit()
        self.break1_edit.setReadOnly(True)
        layout.addWidget(self.break1_edit, 2, 3)

        layout.addWidget(QLabel("Break 2:"), 3, 0)
        self.break2_edit = QLineEdit()
        self.break2_edit.setReadOnly(True)
        layout.addWidget(self.break2_edit, 3, 1)

        layout.addWidget(QLabel("Break 3:"), 3, 2)
        self.break3_edit = QLineEdit()
        self.break3_edit.setReadOnly(True)
        layout.addWidget(self.break3_edit, 3, 3)

        btn_layout = QHBoxLayout()

        self.confirm_btn = QPushButton("Confirm")
        self.confirm_btn.setFixedHeight(35)
        self.confirm_btn.clicked.connect(self.on_confirm)
        btn_layout.addWidget(self.confirm_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedHeight(35)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout, 4, 0, 1, 4)

        self.dept_combo.currentIndexChanged.connect(self.update_displayed_times)
        self.shift_combo.currentIndexChanged.connect(self.update_displayed_times)

        self.update_displayed_times()

    def update_displayed_times(self):
        selected_shift = self.shift_combo.currentText().strip()
        selected_dept = self.dept_combo.currentText().strip()

        self.work_hours_edit.setReadOnly(True)
        self.break1_edit.setReadOnly(True)
        self.break2_edit.setReadOnly(True)
        self.break3_edit.setReadOnly(True)

        if selected_shift == "Ochtend":
            work_hours = "06:00-15:00"
            breaks = OCHTEND_BREAKS
        elif selected_shift == "Middag":
            work_hours = "15:00-00:00"
            breaks = MIDDAG_BREAKS
        elif selected_shift == "Day8to17":
            work_hours = "08:00-17:00"
            breaks = DAY8TO17_BREAKS
        elif selected_shift == "Custom":
            self.work_hours_edit.setReadOnly(False)
            self.break1_edit.setReadOnly(False)
            self.break2_edit.setReadOnly(False)
            self.break3_edit.setReadOnly(False)
            return
        else:
            work_hours = "08:00-17:00"
            breaks = []

        work_hours = adjust_work_hours(work_hours, selected_dept)
        self.work_hours_edit.setText(work_hours)

        break_edits = [self.break1_edit, self.break2_edit, self.break3_edit]

        for edit in break_edits:
            edit.setText("")

        for idx, break_interval in enumerate(breaks[:3]):
            break_edits[idx].setText(
                f"{break_interval[0] // 60:02d}:{break_interval[0] % 60:02d}-"
                f"{break_interval[1] // 60:02d}:{break_interval[1] % 60:02d}"
            )

    def on_confirm(self):
        lastname = self.lastname_edit.text().strip()
        firstname = self.firstname_edit.text().strip()
        department = self.dept_combo.currentText().strip()
        shift = self.shift_combo.currentText().strip()

        if not lastname or not firstname:
            QMessageBox.critical(self, "Error", "Enter last and first name!")
            return

        work_hours = self.work_hours_edit.text().strip()

        custom_breaks = []
        for edit in [self.break1_edit, self.break2_edit, self.break3_edit]:
            value = edit.text().strip()
            if value and "-" in value:
                start, end = value.split("-")
                custom_breaks.append((to_minutes(start), to_minutes(end)))

        computed_hours = compute_hours_with_breaks(
            work_hours,
            shift,
            custom_breaks if shift == "Custom" else None
        )

        if computed_hours == 0.0:
            QMessageBox.critical(self, "Error", "Invalid work hours or breaks.")
            return

        formatted_last, formatted_first = move_lastname_prefix_to_firstname(lastname, firstname)
        formatted_last = format_name(formatted_last)
        formatted_first = format_name(formatted_first)

        self.result_data = {
            "lastname": formatted_last,
            "firstname": formatted_first,
            "department": department,
            "work_hours": work_hours,
            "shift": shift,
            "computed_hours": computed_hours,
            "info": "",
            "custom_breaks": custom_breaks if shift == "Custom" else [],
        }

        self.accept()


class AddDepartmentDialog(QDialog):
    def __init__(self, parent, employees):
        super().__init__(parent)

        self.employees = employees
        self.result_data = None

        self.setWindowTitle("Add Department")
        self.setGeometry(400, 400, 240, 140)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        layout.addWidget(QLabel("Select department:"))
        self.dept_combo = QComboBox()
        self.dept_combo.addItems(TEAM_LIST)
        layout.addWidget(self.dept_combo)

        layout.addWidget(QLabel("Time (HH:MM):"))
        self.time_edit = QLineEdit(datetime.now().strftime("%H:%M"))
        layout.addWidget(self.time_edit)

        layout.addSpacing(5)

        btn_layout = QHBoxLayout()

        self.btn_confirm = QPushButton("Confirm")
        self.btn_confirm.setFixedHeight(35)
        self.btn_confirm.clicked.connect(self.on_confirm)
        btn_layout.addWidget(self.btn_confirm)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setFixedHeight(35)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

    def on_confirm(self):
        department = self.dept_combo.currentText().strip()
        time_chosen = self.time_edit.text().strip()

        if not Validator.validate_time_format(time_chosen):
            QMessageBox.critical(self, "Error", "Invalid time format.")
            return

        self.result_data = {
            "employee_ids": [emp.employee_id for emp in self.employees],
            "department": department,
            "time": time_chosen,
        }

        self.accept()


class EditDepartmentDialog(QDialog):
    def __init__(self, parent, employees):
        super().__init__(parent)

        self.employees = employees
        self.result_data = None

        self.setWindowTitle("Edit Department")
        self.setGeometry(410, 410, 240, 80)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        layout.addWidget(QLabel("New department:"))
        self.new_dept_combo = QComboBox()
        self.new_dept_combo.addItems(TEAM_LIST)
        layout.addWidget(self.new_dept_combo)

        btn_layout = QHBoxLayout()

        self.btn_confirm = QPushButton("Confirm")
        self.btn_confirm.setFixedHeight(35)
        self.btn_confirm.clicked.connect(self.on_confirm)
        btn_layout.addWidget(self.btn_confirm)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setFixedHeight(35)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

    def on_confirm(self):
        self.result_data = {
            "employee_ids": [emp.employee_id for emp in self.employees],
            "department": self.new_dept_combo.currentText().strip(),
        }
        self.accept()


class MarkAsLateDialog(QDialog):
    def __init__(self, parent, emp):
        super().__init__(parent)

        self.emp = emp
        self.result_data = None

        self.setWindowTitle("Mark as Late")
        self.setGeometry(420, 420, 250, 100)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        layout.addWidget(QLabel("Enter actual start time (HH:MM):"), alignment=Qt.AlignLeft)

        self.time_edit = QLineEdit()
        layout.addWidget(self.time_edit, alignment=Qt.AlignHCenter)

        layout.addStretch()

        btn_layout = QHBoxLayout()

        self.btn_confirm = QPushButton("Confirm")
        self.btn_confirm.setFixedHeight(35)
        self.btn_confirm.clicked.connect(self.on_confirm)
        btn_layout.addWidget(self.btn_confirm)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setFixedHeight(35)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

        planned_start = get_scheduled_start_time(emp)
        if planned_start:
            planned_start_minutes = to_minutes(planned_start)
            default_late_minutes = planned_start_minutes + 10
            self.time_edit.setText(f"{default_late_minutes // 60:02d}:{default_late_minutes % 60:02d}")

    def on_confirm(self):
        actual_start = self.time_edit.text().strip()

        if not Validator.validate_time_format(actual_start):
            QMessageBox.critical(self, "Error", "Invalid time format. Please use HH:MM.")
            return

        self.result_data = {
            "employee_id": self.emp.employee_id,
            "actual_start": actual_start,
        }

        self.accept()


class HistoryDialog(QDialog):
    """Dziennik zmian: kto, kiedy i co zmienił."""

    def __init__(self, parent, entries):
        super().__init__(parent)

        self.setWindowTitle("History of changes")
        self.resize(900, 520)

        layout = QVBoxLayout(self)

        table = QTableWidget(len(entries), 4)
        table.setHorizontalHeaderLabels(["Time", "User", "Action", "Details"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)

        for row, (ts, user, action, details, undone) in enumerate(entries):
            if undone:
                action = f"{action} (undone)"
            for col, value in enumerate((ts, user, action, details)):
                table.setItem(row, col, QTableWidgetItem(str(value or "")))

        table.setColumnWidth(0, 140)
        table.setColumnWidth(1, 100)
        table.setColumnWidth(2, 150)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(35)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
