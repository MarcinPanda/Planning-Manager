import sys
import os
import sqlite3
import pandas as pd
import warnings
import uuid
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
from PySide6.QtGui import QPainter, QColor

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

SESSION_ID = str(uuid.uuid4())

BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
DB_PATH = os.path.join(BASE_DIR, "planning_data.db")
SYNC_INTERVAL_MS = 10_000  # auto-odświeżanie tabeli

NAME_EXCEPTIONS = ["van", "vas", "dos", "al"]

TEAM_LIST = [
    "Accu", "Ass TL", "Buffer", "Consolidatie/Kantelen", "Controle", "Cycle Count", "Emballage", "Extra",
    "Fixing Pallets", "Helpdesk", "Inbound 1", "Inbound 2", "Inbound 3", "Inbound 4", "Inbound 5", "Klusje/Racking",
    "Laco", "Laden", "Logistiek coördinator", "Naar Huis", "Opleiding", "Orderpicker", "Pendel", "Project", "Reachtruck", "Reflex",
    "Retouren", "Shiftleader", "Schoonmaak", "Stock Control", "Sturing", "Teamleader", "VAL", "Ziek"
]
TEAM_LIST.sort(key=lambda x: x.lower())

SHIFT_LIST = ["Ochtend", "Middag", "Day8to17", "Custom"]

columns = (
    "marked", "lastname", "firstname", "work_hours", "computed_hours",
    "current_department", "time_dept1", "dept2", "time_dept2", "dept3", "time_dept3",
    "dept4", "time_dept4", "dept5", "time_dept5", "info"
)

col_names = [
    "Marked", "Last Name", "First Name", "Work Hours", "Total Work Time",
    "Department 1", "Work Time 1", "Department 2", "Work Time 2", "Department 3", "Work Time 3",
    "Department 4", "Work Time 4", "Department 5", "Work Time 5", "Info"
]

OCHTEND_BREAKS = [(8 * 60 + 15, 8 * 60 + 30), (10 * 60 + 30, 10 * 60 + 45), (12 * 60 + 30, 13 * 60)]
MIDDAG_BREAKS = [(17 * 60 + 15, 17 * 60 + 30), (19 * 60 + 30, 20 * 60), (22 * 60, 22 * 60 + 15)]
DAY8TO17_BREAKS = [(10 * 60 + 30, 10 * 60 + 45), (12 * 60 + 30, 13 * 60), (15 * 60, 15 * 60 + 15)]

SPECIAL_FUNCTIONS = ["Ass TL", "Help Desk", "Teamleider", "Transport coördinator", "Shiftleader", "Sturing"]


###############################################################################
# Database
###############################################################################

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lastname TEXT NOT NULL,
            firstname TEXT NOT NULL,
            current_department TEXT NOT NULL,
            work_hours TEXT NOT NULL,
            shift TEXT NOT NULL,
            computed_hours REAL NOT NULL,
            marked INTEGER DEFAULT 0,
            info TEXT DEFAULT '',
            lock_owner TEXT DEFAULT '',
            lock_timestamp TEXT DEFAULT ''
        )
    """)

    cursor.execute("PRAGMA table_info(employees)")
    columns_db = [col[1] for col in cursor.fetchall()]

    if "marked" not in columns_db:
        cursor.execute("ALTER TABLE employees ADD COLUMN marked INTEGER DEFAULT 0")
    if "info" not in columns_db:
        cursor.execute("ALTER TABLE employees ADD COLUMN info TEXT DEFAULT ''")
    if "lock_owner" not in columns_db:
        cursor.execute("ALTER TABLE employees ADD COLUMN lock_owner TEXT DEFAULT ''")
    if "lock_timestamp" not in columns_db:
        cursor.execute("ALTER TABLE employees ADD COLUMN lock_timestamp TEXT DEFAULT ''")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            department TEXT NOT NULL,
            time_assigned TEXT NOT NULL,
            FOREIGN KEY (employee_id) REFERENCES employees (id) ON DELETE CASCADE
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_departments_employee_id ON departments(employee_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_employees_name ON employees(lastname, firstname)")

    conn.commit()
    conn.close()


def load_employees_from_db():
    result = []

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, lastname, firstname, current_department, work_hours, shift, computed_hours, marked, info
        FROM employees
    """)
    rows = cursor.fetchall()

    for row in rows:
        emp = Employee(*row)

        cursor.execute("""
            SELECT department, time_assigned
            FROM departments
            WHERE employee_id = ?
            ORDER BY id ASC
        """, (emp.employee_id,))
        dept_data = cursor.fetchall()

        emp.dept_times = [(d, t) for d, t in dept_data]
        emp.marked = bool(row[7])
        emp.recalc_intervals_and_hours()
        result.append(emp)

    conn.close()
    return result


def insert_employee_to_db(data):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO employees (
            lastname, firstname, current_department, work_hours, shift, computed_hours, marked, info
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["lastname"],
        data["firstname"],
        data["department"],
        data["work_hours"],
        data["shift"],
        data["computed_hours"],
        0,
        data.get("info", ""),
    ))

    employee_id = cursor.lastrowid

    cursor.execute("""
        INSERT INTO departments (employee_id, department, time_assigned)
        VALUES (?, ?, ?)
    """, (employee_id, data["department"], ""))

    conn.commit()
    conn.close()
    return employee_id


def delete_employees_from_db(employee_ids):
    conn = get_connection()
    cursor = conn.cursor()

    for emp_id in employee_ids:
        cursor.execute("DELETE FROM departments WHERE employee_id = ?", (emp_id,))
        cursor.execute("DELETE FROM employees WHERE id = ?", (emp_id,))

    conn.commit()
    conn.close()


def clear_all_data_in_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM departments")
    cursor.execute("DELETE FROM employees")
    conn.commit()
    conn.close()


def update_employee_info_in_db(emp_id, info):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE employees SET info = ? WHERE id = ?", (info, emp_id))
    conn.commit()
    conn.close()


def toggle_employee_marked_in_db(emp_id, marked):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE employees SET marked = ? WHERE id = ?", (1 if marked else 0, emp_id))
    conn.commit()
    conn.close()


def add_departments_to_db(employee_ids, dept_chosen, time_chosen):
    if not Validator.validate_time_format(time_chosen):
        raise ValueError("Invalid time format.")

    conn = get_connection()
    cursor = conn.cursor()
    errors = []

    for emp_id in employee_ids:
        emp = load_employee_by_id(cursor, emp_id)
        if emp is None:
            errors.append(f"Employee ID {emp_id}: not found.")
            continue

        try:
            distinct = {d for d, _ in emp.dept_times}
            if dept_chosen not in distinct and len(distinct) >= 5:
                raise ValueError("Cannot have more than 5 different departments.")

            emp.dept_times.append((dept_chosen, time_chosen))

            cursor.execute("""
                INSERT INTO departments (employee_id, department, time_assigned)
                VALUES (?, ?, ?)
            """, (emp_id, dept_chosen, time_chosen))

            if dept_chosen.lower() == "naar huis":
                start = emp.original_work_hours.split("-")[0].strip()
                emp.work_hours = f"{start}-{time_chosen}"
                cursor.execute("""
                    UPDATE employees
                    SET work_hours = ?, marked = 0
                    WHERE id = ?
                """, (emp.work_hours, emp_id))
            else:
                cursor.execute("UPDATE employees SET marked = 0 WHERE id = ?", (emp_id,))

            emp.recalc_intervals_and_hours()
            cursor.execute("""
                UPDATE employees
                SET computed_hours = ?
                WHERE id = ?
            """, (emp.computed_hours, emp_id))

        except ValueError as exc:
            errors.append(f"{emp.lastname} {emp.firstname}: {exc}")

    conn.commit()
    conn.close()
    return errors


def remove_last_departments_from_db(employee_ids):
    conn = get_connection()
    cursor = conn.cursor()
    errors = []

    for emp_id in employee_ids:
        emp = load_employee_by_id(cursor, emp_id)
        if emp is None:
            errors.append(f"Employee ID {emp_id}: not found.")
            continue

        if len(emp.dept_times) <= 1:
            errors.append(f"{emp.lastname} {emp.firstname}: No additional departments to remove.")
            continue

        last_dept = emp.dept_times[-1][0]

        cursor.execute("""
            DELETE FROM departments
            WHERE id = (
                SELECT id
                FROM departments
                WHERE employee_id = ? AND department = ?
                ORDER BY id DESC
                LIMIT 1
            )
        """, (emp_id, last_dept))

        emp.dept_times.pop()
        emp.recalc_intervals_and_hours()

        cursor.execute("""
            UPDATE employees
            SET computed_hours = ?
            WHERE id = ?
        """, (emp.computed_hours, emp_id))

    conn.commit()
    conn.close()
    return errors


def edit_departments_in_db(employee_ids, new_dept):
    conn = get_connection()
    cursor = conn.cursor()

    for emp_id in employee_ids:
        emp = load_employee_by_id(cursor, emp_id)
        if emp is None:
            continue

        emp.edit_current_department(new_dept)

        cursor.execute("""
            UPDATE employees
            SET current_department = ?, work_hours = ?, computed_hours = ?
            WHERE id = ?
        """, (emp.current_department, emp.work_hours, emp.computed_hours, emp_id))

        cursor.execute("""
            UPDATE departments
            SET department = ?
            WHERE employee_id = ? AND time_assigned = ''
        """, (new_dept, emp_id))

    conn.commit()
    conn.close()


def mark_employee_late_in_db(emp_id, actual_start):
    if not Validator.validate_time_format(actual_start):
        raise ValueError("Invalid time format. Please use HH:MM.")

    conn = get_connection()
    cursor = conn.cursor()

    emp = load_employee_by_id(cursor, emp_id)
    if emp is None:
        conn.close()
        raise ValueError("Employee not found.")

    if not emp.work_hours or "-" not in emp.work_hours:
        conn.close()
        raise ValueError("Original work hours not set.")

    _, old_end_str = emp.work_hours.split("-")
    old_end_str = old_end_str.strip()

    emp.work_hours = f"{actual_start}-{old_end_str}"
    emp.recalc_intervals_and_hours()

    cursor.execute("""
        UPDATE employees
        SET work_hours = ?, computed_hours = ?
        WHERE id = ?
    """, (emp.work_hours, emp.computed_hours, emp_id))

    conn.commit()
    conn.close()


def lock_employee(emp_id, session_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE employees
        SET lock_owner = ?, lock_timestamp = datetime('now')
        WHERE id = ? AND (lock_owner IS NULL OR lock_owner = '')
    """, (session_id, emp_id))

    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0


def unlock_employee(emp_id, session_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE employees
        SET lock_owner = '', lock_timestamp = ''
        WHERE id = ? AND lock_owner = ?
    """, (emp_id, session_id))

    conn.commit()
    conn.close()


def load_employee_by_id(cursor, emp_id):
    cursor.execute("""
        SELECT id, lastname, firstname, current_department, work_hours, shift, computed_hours, marked, info
        FROM employees
        WHERE id = ?
    """, (emp_id,))
    row = cursor.fetchone()

    if row is None:
        return None

    emp = Employee(*row)

    cursor.execute("""
        SELECT department, time_assigned
        FROM departments
        WHERE employee_id = ?
        ORDER BY id ASC
    """, (emp_id,))
    dept_data = cursor.fetchall()

    emp.dept_times = [(d, t) for d, t in dept_data]
    emp.marked = bool(row[7])
    emp.recalc_intervals_and_hours()

    return emp


def import_excel_to_db(filepaths):
    if not filepaths:
        return 0

    employees_list = []

    for filepath in filepaths:
        data = pd.read_excel(filepath, header=None)

        if data.shape[1] < 6:
            raise ValueError(f"The file {filepath} does not contain enough columns (min. 6).")

        lastname_col = 3
        firstname_col = 4
        work_hours_col = data.shape[1] - 1
        current_department = None
        current_shift = None

        for i in range(len(data)):
            row = data.iloc[i, :]

            val_b = row[1] if len(row) > 1 else None
            if isinstance(val_b, str) and "Warehouse" in val_b and "Week" in val_b:
                parts = [p.strip() for p in val_b.split("/") if p.strip()]

                if len(parts) >= 2:
                    shift_candidate = parts[1]
                    current_shift = shift_candidate if shift_candidate in ["Ochtend", "Middag", "Day8to17"] else None

                if len(parts) >= 3:
                    current_department = parts[2]
                else:
                    current_department = None

                continue

            val_d = row[lastname_col] if len(row) > lastname_col else None
            val_e = row[firstname_col] if len(row) > firstname_col else None

            if isinstance(val_d, str) and "Achternaam" in val_d:
                continue
            if isinstance(val_e, str) and "Voornaam" in val_e:
                continue

            if isinstance(val_d, str) and val_d.strip() and isinstance(val_e, str) and val_e.strip():
                val_hours = row[work_hours_col] if len(row) > work_hours_col else None
                dept = current_department if current_department else "Unknown"

                if dept.strip().lower() == "consolidatie":
                    dept = "Consolidatie/Kantelen"
                elif dept.strip().lower() == "transport coördinator":
                    dept = "Laco"

                shift = current_shift if current_shift else ""

                if dept in SPECIAL_FUNCTIONS or dept == "Logistiek coördinator":
                    val_hours = adjust_work_hours(val_hours, dept)

                if not shift and isinstance(val_hours, str) and "08:00-17:00" in val_hours:
                    shift = "Day8to17"

                lastname, firstname = move_lastname_prefix_to_firstname(val_d, val_e)

                if lastname.lower() == "buczkowski" and firstname.lower() == "rafal" and dept.lower() in ["laco", "transport coördinator"]:
                    dept = "Logistiek coördinator"
                    val_hours = adjust_work_hours(val_hours, dept)

                employees_list.append([lastname, firstname, dept, val_hours, shift])

    employees_df = pd.DataFrame(
        employees_list,
        columns=["lastname", "firstname", "current_department", "work_hours", "shift"]
    )
    employees_df = employees_df.dropna(subset=["lastname", "firstname"])

    words_to_exclude = "Achternaam|Voornaam|Badge"
    mask = ~(
        employees_df["lastname"].str.contains(words_to_exclude, na=False, case=False) |
        employees_df["firstname"].str.contains(words_to_exclude, na=False, case=False) |
        employees_df["current_department"].str.contains(words_to_exclude, na=False, case=False) |
        employees_df["work_hours"].fillna("").str.contains(words_to_exclude, na=False, case=False)
    )

    employees_df = employees_df[mask]
    employees_df["lastname"] = employees_df["lastname"].apply(format_name)
    employees_df["firstname"] = employees_df["firstname"].apply(format_name)
    employees_df["computed_hours"] = employees_df.apply(
        lambda row_: compute_hours_with_breaks(row_["work_hours"], row_["shift"]),
        axis=1
    )

    conn = get_connection()
    cursor = conn.cursor()

    count = 0

    for _, row_ in employees_df.iterrows():
        lastname, firstname = move_lastname_prefix_to_firstname(row_["lastname"], row_["firstname"])

        cursor.execute("""
            INSERT INTO employees (lastname, firstname, current_department, work_hours, shift, computed_hours, marked)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            lastname,
            firstname,
            row_["current_department"],
            row_["work_hours"],
            row_["shift"],
            row_["computed_hours"],
            0
        ))

        employee_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO departments (employee_id, department, time_assigned)
            VALUES (?, ?, ?)
        """, (employee_id, row_["current_department"], ""))

        count += 1

    conn.commit()
    conn.close()

    return count


###############################################################################
# Business logic
###############################################################################

class Validator:
    @staticmethod
    def validate_time_format(time_str):
        try:
            hh, mm = time_str.split(":")
            hh = int(hh)
            mm = int(mm)
            return 0 <= hh < 24 and 0 <= mm < 60
        except Exception:
            return False


def to_minutes(hhmm):
    if not Validator.validate_time_format(hhmm):
        return 0
    hh, mm = hhmm.split(":")
    return int(hh) * 60 + int(mm)


def compute_hours_with_breaks(work_hours, shift, custom_breaks=None):
    if not isinstance(work_hours, str) or "-" not in work_hours:
        return 0.0

    parts = work_hours.split("-")
    if len(parts) != 2:
        return 0.0

    start_str, end_str = parts
    start = to_minutes(start_str.strip())
    end = to_minutes(end_str.strip())

    if end < start:
        end += 24 * 60

    total = end - start
    breaks = []

    if shift == "Ochtend":
        breaks = OCHTEND_BREAKS
    elif shift == "Middag":
        breaks = MIDDAG_BREAKS
    elif shift == "Day8to17":
        breaks = DAY8TO17_BREAKS
    elif shift == "Custom" and custom_breaks:
        breaks = custom_breaks

    for b_start, b_end in breaks:
        if b_start < end and b_end > start:
            total -= max(0, min(end, b_end) - max(start, b_start))

    total = max(0, total)
    return round((total / 60.0) * 4) / 4.0


def interval_hours_with_breaks(s, e, shift):
    if e < s:
        e += 24 * 60
    return compute_hours_with_breaks(f"{s // 60:02d}:{s % 60:02d}-{e // 60:02d}:{e % 60:02d}", shift)


def format_name(name):
    words = name.split()
    formatted = []

    for word in words:
        lower_word = word.lower()
        if lower_word not in NAME_EXCEPTIONS:
            formatted.append(word.capitalize())
        else:
            formatted.append(lower_word)

    return " ".join(formatted)


def round_to_quarter(x):
    return round(x * 4) / 4


def move_lastname_prefix_to_firstname(lastname, firstname):
    if lastname.lower() == "azevedo carvalho":
        return "Carvalho Azevedo", firstname
    if lastname.lower() == "juliao":
        return "Ramos Juliao", firstname
    if lastname.lower() == "wlodarczyk":
        return "Wlodarkiewicz", firstname

    lastname_parts = lastname.split()
    firstname = firstname.strip()

    if len(lastname_parts) > 1 and " ".join(lastname_parts[:2]).lower() == "vas dos":
        return lastname, firstname

    for i, part in enumerate(lastname_parts):
        if part.lower() in NAME_EXCEPTIONS:
            prefix = " ".join(lastname_parts[:i + 1])
            remaining_lastname = " ".join(lastname_parts[i + 1:])

            if remaining_lastname:
                new_firstname = f"{firstname} {prefix}".strip()
                return remaining_lastname, new_firstname

            break

    return lastname, firstname


def adjust_work_hours(work_hours, department=None):
    if not isinstance(work_hours, str) or "-" not in work_hours:
        return work_hours

    start, end = work_hours.split("-")
    start = start.strip()
    end = end.strip()

    if department == "Logistiek coördinator":
        if start < "12:00":
            start = "05:30"
            end = "15:00"
        else:
            start = "14:30"
            end = "00:00"
    elif department in SPECIAL_FUNCTIONS:
        if start in ["06:00", "05:30"]:
            start = "05:45"
        elif start in ["15:00", "14:30"]:
            start = "14:45"
    else:
        if start in ["05:30", "05:45"]:
            start = "06:00"
        elif start in ["14:30", "14:45"]:
            start = "15:00"

    if start in ["14:30", "14:45"]:
        end = "00:00"

    return f"{start}-{end}"


def get_scheduled_start_time(emp):
    if not emp.work_hours or "-" not in emp.work_hours:
        return None

    start_str, _ = emp.work_hours.split("-")
    return start_str.strip()


###############################################################################
# UI helper widgets
###############################################################################

class ToggleButton(QCheckBox):
    def __init__(
        self,
        width=70,
        height=25,
        bgColor="#777",
        circleColor="#DDD",
        activeColor="#00BCff",
        animationCurve=QEasingCurve.Linear,
        parent=None
    ):
        super().__init__(parent)

        self.setFixedSize(width, height)
        self.setCursor(Qt.PointingHandCursor)

        self._bg_color = bgColor
        self._circle_color = circleColor
        self._active_color = activeColor
        self._circle_diameter = height - 6
        self._circle_position = 3

        self.animation = QPropertyAnimation(self, b"circle_position", self)
        self.animation.setDuration(200)
        self.animation.setEasingCurve(animationCurve)
        self.stateChanged.connect(self.start_transition)

    @Property(int)
    def circle_position(self):
        return self._circle_position

    @circle_position.setter
    def circle_position(self, pos):
        self._circle_position = pos
        self.update()

    def start_transition(self, state):
        self.animation.stop()
        self.animation.setEndValue(self.width() - self._circle_diameter - 3 if state == 2 else 3)
        self.animation.start()

    def hitButton(self, pos):
        return self.contentsRect().contains(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()

        painter.setBrush(QColor(self._active_color if self.isChecked() else self._bg_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, rect.height() // 2, rect.height() // 2)

        painter.setBrush(QColor(self._circle_color))
        painter.drawEllipse(self._circle_position, 3, self._circle_diameter, self._circle_diameter)

        painter.end()


###############################################################################
# Data model
###############################################################################

class Employee:
    def __init__(
        self,
        employee_id,
        lastname,
        firstname,
        current_department,
        work_hours,
        shift,
        computed_hours,
        marked,
        info,
        custom_breaks=None
    ):
        self.employee_id = employee_id
        self.lastname = lastname
        self.firstname = firstname
        self.current_department = current_department
        self.work_hours = work_hours
        self.original_work_hours = work_hours
        self.shift = shift
        self.computed_hours = str(computed_hours)
        self.marked = bool(marked)
        self.info = info or ""
        self.custom_breaks = custom_breaks if custom_breaks else []
        self.dept_intervals = []
        self.dept_times = [(current_department, "")]

    def edit_current_department(self, new_dept):
        if self.dept_times:
            first_time_assigned = self.dept_times[0][1]
            self.dept_times[0] = (new_dept, first_time_assigned)

        self.work_hours = adjust_work_hours(self.work_hours, new_dept)
        self.current_department = new_dept
        self.recalc_intervals_and_hours()

    def recalc_intervals_and_hours(self):
        if not self.dept_times or not isinstance(self.work_hours, str) or "-" not in self.work_hours:
            self.dept_intervals = []
            self.computed_hours = "0.00"
            return

        start_str, end_str = self.work_hours.split("-")
        start_str = start_str.strip()
        end_str = end_str.strip()

        if not (Validator.validate_time_format(start_str) and Validator.validate_time_format(end_str)):
            self.dept_intervals = []
            self.computed_hours = "0.00"
            return

        start_min = to_minutes(start_str)
        end_min = to_minutes(end_str)

        if end_min < start_min:
            end_min += 24 * 60

        times = []

        for dept, time_assigned in self.dept_times:
            dept = dept.strip()

            if time_assigned and Validator.validate_time_format(time_assigned):
                t = to_minutes(time_assigned.strip())
                if t < start_min:
                    t += 24 * 60
                times.append((t, dept))
            else:
                times.append((start_min, dept))

        times.append((end_min, ""))

        total_hours = 0.0
        dept_hours = {}
        dept_order = []

        for i in range(len(times) - 1):
            start, dept_name = times[i]
            end, _ = times[i + 1]

            if dept_name.lower() in ["ziek", "naar huis"]:
                duration = 0.0
            else:
                if self.shift == "Custom":
                    duration = compute_hours_with_breaks(
                        f"{start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d}",
                        "Custom",
                        self.custom_breaks
                    )
                else:
                    duration = interval_hours_with_breaks(start, end, self.shift)

            total_hours += duration

            if dept_name and dept_name.lower() not in ["ziek", "naar huis"]:
                if dept_name not in dept_hours:
                    dept_hours[dept_name] = 0.0
                    dept_order.append(dept_name)

                dept_hours[dept_name] += duration

        self.computed_hours = f"{total_hours:.2f}"
        self.dept_intervals = [(dept, dept_hours[dept]) for dept in dept_order]

    def to_ui_values(self):
        marked_symbol = "✅" if self.marked else ""
        ui = [marked_symbol, self.lastname, self.firstname, self.work_hours, self.computed_hours]

        max_depts = 5

        for dept, duration in self.dept_intervals[:max_depts]:
            ui.append(dept)

            if dept == "Consolidatie/Kantelen":
                part1 = round_to_quarter(duration * 0.25)
                part2 = round_to_quarter(duration * 0.75)
                ui.append(f"{part1:.2f}/{part2:.2f}")
            else:
                ui.append(f"{duration:.2f}")

        for _ in range(max_depts - len(self.dept_intervals)):
            ui.append("")
            ui.append("")

        ui.append(self.info)
        return ui


class EmployeeTableModel(QAbstractTableModel):
    def __init__(self, employees=None, parent=None):
        super().__init__(parent)
        self.employees = employees or []
        self.employee_index_map = {}
        self.sort_column = None
        self.sort_ascending = True
        self.rebuild_index()

    def rebuild_index(self):
        self.employee_index_map = {
            emp.employee_id: index
            for index, emp in enumerate(self.employees)
        }

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.employees)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()

        if not (0 <= row < len(self.employees)):
            return None

        emp = self.employees[row]
        values = emp.to_ui_values()

        if col >= len(values):
            return None

        if role in (Qt.DisplayRole, Qt.EditRole):
            return values[col]

        if role == Qt.TextAlignmentRole:
            return Qt.AlignCenter

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None

        if orientation == Qt.Horizontal:
            return col_names[section]

        return str(section + 1)

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags

        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable

        if index.column() == len(columns) - 1:
            flags |= Qt.ItemIsEditable

        return flags

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False

        if index.column() != len(columns) - 1:
            return False

        emp = self.employees[index.row()]
        emp.info = str(value)

        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
        return True

    def refresh(self, employees):
        self.beginResetModel()
        self.employees = employees
        self.apply_current_sort(reset_model=False)
        self.rebuild_index()
        self.endResetModel()

    def get_employee_at_row(self, row):
        if 0 <= row < len(self.employees):
            return self.employees[row]
        return None

    def get_employee_by_id(self, employee_id):
        row = self.employee_index_map.get(employee_id)
        if row is None:
            return None
        return self.get_employee_at_row(row)

    def get_selected_employees(self, selection_model):
        result = []

        for idx in selection_model.selectedRows():
            emp = self.get_employee_at_row(idx.row())
            if emp:
                result.append(emp)

        return result

    def toggle_sort(self, column):
        if self.sort_column == column:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_column = column
            self.sort_ascending = True

        self.beginResetModel()
        self.apply_current_sort(reset_model=False)
        self.rebuild_index()
        self.endResetModel()

    def sort(self, column, order=Qt.AscendingOrder):
        self.sort_column = column
        self.sort_ascending = order == Qt.AscendingOrder

        self.beginResetModel()
        self.apply_current_sort(reset_model=False)
        self.rebuild_index()
        self.endResetModel()

    def apply_current_sort(self, reset_model=True):
        if self.sort_column is None:
            return

        column_map = {
            0: lambda e: e.marked,
            1: lambda e: e.lastname.casefold(),
            2: lambda e: e.firstname.casefold(),
            3: lambda e: e.work_hours,
            4: lambda e: self._safe_float(e.computed_hours),
            5: lambda e: e.current_department.casefold() if e.current_department else "",
            7: lambda e: e.dept_intervals[1][0].casefold() if len(e.dept_intervals) > 1 else "",
            9: lambda e: e.dept_intervals[2][0].casefold() if len(e.dept_intervals) > 2 else "",
            11: lambda e: e.dept_intervals[3][0].casefold() if len(e.dept_intervals) > 3 else "",
            13: lambda e: e.dept_intervals[4][0].casefold() if len(e.dept_intervals) > 4 else "",
            15: lambda e: e.info.casefold() if e.info else "",
        }

        key_func = column_map.get(self.sort_column)
        if not key_func:
            return

        if reset_model:
            self.beginResetModel()

        self.employees.sort(key=key_func, reverse=not self.sort_ascending)

        if reset_model:
            self.rebuild_index()
            self.endResetModel()

    @staticmethod
    def _safe_float(value):
        try:
            return float(str(value).replace(",", "."))
        except Exception:
            return 0.0


###############################################################################
# Workers
###############################################################################

class DatabaseLoadWorker(QObject):
    finished = Signal(list)
    error = Signal(str)

    @Slot()
    def run(self):
        try:
            data = load_employees_from_db()
            self.finished.emit(data)
        except Exception as exc:
            self.error.emit(str(exc))


class DatabaseTaskWorker(QObject):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = task

    @Slot()
    def run(self):
        try:
            result = self.task()
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


###############################################################################
# Delegates
###############################################################################

class InfoItemDelegate(QItemDelegate):
    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)

        parent_widget = parent.window()
        if hasattr(parent_widget, "is_editing_info"):
            parent_widget.is_editing_info = True

        return editor

    def setModelData(self, editor, model, index):
        super().setModelData(editor, model, index)

        parent_widget = editor.window()
        if hasattr(parent_widget, "is_editing_info"):
            parent_widget.is_editing_info = False

    def destroyEditor(self, editor, index):
        # Anulowanie edycji (Esc) nie wywołuje setModelData – zdejmij flagę tutaj,
        # inaczej auto-odświeżanie zostałoby wstrzymane na stałe.
        parent_widget = editor.window()
        if hasattr(parent_widget, "is_editing_info"):
            parent_widget.is_editing_info = False
        super().destroyEditor(editor, index)


###############################################################################
# Dialogs
###############################################################################

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


###############################################################################
# Main window
###############################################################################

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.is_editing_info = False
        self.mark_mode = False
        self._active_threads = []

        self.setWindowTitle("Planning Manager")
        self.setGeometry(100, 100, 1200, 600)

        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QVBoxLayout(self.main_widget)

        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(5, 5, 5, 5)
        top_layout.setSpacing(3)
        self.main_layout.addLayout(top_layout)

        self.load_button = QPushButton("Import Excel")
        self.load_button.setFixedWidth(120)
        self.load_button.setMinimumHeight(40)
        self.load_button.clicked.connect(self.load_excel)
        top_layout.addWidget(self.load_button)

        self.clear_button = QPushButton("Clear Data")
        self.clear_button.setFixedWidth(120)
        self.clear_button.setMinimumHeight(40)
        self.clear_button.clicked.connect(self.clear_data)
        top_layout.addWidget(self.clear_button)

        self.add_emp_button = QPushButton("Add Employee")
        self.add_emp_button.setFixedWidth(120)
        self.add_emp_button.setMinimumHeight(40)
        self.add_emp_button.clicked.connect(self.add_employee)
        top_layout.addWidget(self.add_emp_button)

        self.remove_emp_button = QPushButton("Remove Employee")
        self.remove_emp_button.setFixedWidth(150)
        self.remove_emp_button.setMinimumHeight(40)
        self.remove_emp_button.clicked.connect(self.remove_employee)
        top_layout.addWidget(self.remove_emp_button)

        top_layout.addStretch()

        self.mark_mode_label = QLabel("Mark Mode OFF")
        self.mark_mode_label.setFixedWidth(100)

        self.toggle_mark_button = ToggleButton(
            width=50,
            height=25,
            bgColor="#777",
            circleColor="#DDD",
            activeColor="#00BCff",
        )
        self.toggle_mark_button.stateChanged.connect(self.toggle_mark_mode)

        top_layout.addWidget(self.mark_mode_label)
        top_layout.addWidget(self.toggle_mark_button)

        self.sync_button = QPushButton("Sync Now")
        self.sync_button.setFixedWidth(100)
        self.sync_button.setMinimumHeight(40)
        self.sync_button.clicked.connect(self.sync_now)
        top_layout.addWidget(self.sync_button)

        self.model = EmployeeTableModel([])
        self.model.dataChanged.connect(self.on_model_data_changed)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSortingEnabled(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.horizontalHeader().setStyleSheet("font-weight: normal;")

        widths = [60, 140, 100, 80, 100, 140, 80, 140, 80, 140, 80, 140, 80, 140, 80, 285]
        for col, width in enumerate(widths):
            self.table.setColumnWidth(col, width)

        info_col = len(columns) - 1
        self.table.setItemDelegateForColumn(info_col, InfoItemDelegate(self.table))

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.sectionClicked.connect(self.sort_table)

        self.main_layout.addWidget(self.table)

        self.context_menu = QMenu(self)
        self.context_menu.addAction("Add Department", self.add_department)
        self.context_menu.addAction("Edit Department", self.edit_department)
        self.context_menu.addAction("Remove Department", self.remove_department)
        self.context_menu.addAction("Late", self.mark_as_late)

        self.refresh_data()

        # Auto-synchronizacja co 10 s (z Planning.py) – pomijana podczas edycji Info
        # lub gdy w tle trwa inna operacja na bazie.
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.auto_refresh)
        self.sync_timer.start(SYNC_INTERVAL_MS)

    def auto_refresh(self):
        if self.is_editing_info or self._active_threads:
            return
        self.refresh_data()

    def sync_now(self):
        self.sync_timer.start(SYNC_INTERVAL_MS)  # restart odliczania
        self.refresh_data()

    def set_controls_enabled(self, enabled):
        self.load_button.setEnabled(enabled)
        self.clear_button.setEnabled(enabled)
        self.add_emp_button.setEnabled(enabled)
        self.remove_emp_button.setEnabled(enabled)
        self.sync_button.setEnabled(enabled)
        self.toggle_mark_button.setEnabled(enabled)

    def run_db_task(self, task, on_finished=None, refresh_after=False):
        self.set_controls_enabled(False)

        thread = QThread(self)
        worker = DatabaseTaskWorker(task)
        worker.moveToThread(thread)

        self._active_threads.append((thread, worker))

        thread.started.connect(worker.run)

        def cleanup():
            self._active_threads[:] = [
                (t, w)
                for t, w in self._active_threads
                if t is not thread
            ]
            thread.deleteLater()

        def finished_handler(result):
            if on_finished:
                on_finished(result)

            if refresh_after:
                self.refresh_data()
            else:
                self.set_controls_enabled(True)

            thread.quit()

        def error_handler(message):
            self.set_controls_enabled(True)
            QMessageBox.critical(self, "Database Error", message)
            thread.quit()

        worker.finished.connect(finished_handler)
        worker.error.connect(error_handler)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(cleanup)

        thread.start()

    def refresh_data(self):
        if self.is_editing_info:
            return

        selected_ids = [emp.employee_id for emp in self.selected_employees()]
        scroll_value = self.table.verticalScrollBar().value()

        self.set_controls_enabled(False)

        thread = QThread(self)
        worker = DatabaseLoadWorker()
        worker.moveToThread(thread)

        self._active_threads.append((thread, worker))

        thread.started.connect(worker.run)

        def cleanup():
            self._active_threads[:] = [
                (t, w)
                for t, w in self._active_threads
                if t is not thread
            ]
            thread.deleteLater()

        def on_finished(data):
            self.model.refresh(data)
            self.restore_selection(selected_ids)
            self.table.verticalScrollBar().setValue(scroll_value)
            self.set_controls_enabled(True)
            thread.quit()

        def on_error(message):
            self.set_controls_enabled(True)
            QMessageBox.critical(self, "Database Error", message)
            thread.quit()

        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(cleanup)

        thread.start()

    def restore_selection(self, employee_ids):
        if not employee_ids:
            return

        selection_model = self.table.selectionModel()

        # Blokujemy sygnały, żeby odtworzenie zaznaczenia nie przełączyło
        # znacznika w Mark Mode (inaczej każde odświeżenie zmieniałoby „Marked”).
        selection_model.blockSignals(True)
        try:
            selection_model.clearSelection()
            for emp_id in employee_ids:
                row = self.model.employee_index_map.get(emp_id)
                if row is not None:
                    self.table.selectRow(row)
        finally:
            selection_model.blockSignals(False)

    def selected_employees(self):
        if self.table.selectionModel() is None:
            return []
        return self.model.get_selected_employees(self.table.selectionModel())

    def selected_employee_ids(self):
        return [emp.employee_id for emp in self.selected_employees()]

    def show_context_menu(self, pos):
        if self.model.rowCount() == 0:
            return

        if not self.table.selectionModel().selectedRows():
            return

        self.context_menu.exec(self.table.viewport().mapToGlobal(pos))

    def toggle_mark_mode(self):
        self.mark_mode = self.toggle_mark_button.isChecked()
        self.mark_mode_label.setText("Mark Mode ON" if self.mark_mode else "Mark Mode OFF")

        self.table.setSelectionMode(
            QAbstractItemView.SingleSelection if self.mark_mode else QAbstractItemView.ExtendedSelection
        )

        selection_model = self.table.selectionModel()

        try:
            selection_model.selectionChanged.disconnect(self.on_selection_change_mark)
        except TypeError:
            pass

        if self.mark_mode:
            selection_model.selectionChanged.connect(self.on_selection_change_mark)

    def on_selection_change_mark(self):
        if not self.mark_mode:
            return

        selected_rows = self.table.selectionModel().selectedRows()
        if len(selected_rows) != 1:
            return

        row = selected_rows[0].row()
        emp = self.model.get_employee_at_row(row)

        if not emp:
            return

        emp.marked = not emp.marked

        self.model.dataChanged.emit(
            self.model.index(row, 0),
            self.model.index(row, len(columns) - 1),
            [Qt.DisplayRole]
        )

        emp_id = emp.employee_id
        marked = emp.marked

        self.run_db_task(lambda: toggle_employee_marked_in_db(emp_id, marked))

    def sort_table(self, index):
        self.model.toggle_sort(index)

    def add_employee(self):
        dlg = AddEmployeeDialog(self)

        if dlg.exec() and dlg.result_data:
            data = dlg.result_data
            self.run_db_task(
                lambda: insert_employee_to_db(data),
                refresh_after=True
            )

    def remove_employee(self):
        employee_ids = self.selected_employee_ids()

        if not employee_ids:
            QMessageBox.information(self, "Info", "No employee selected.")
            return

        reply = QMessageBox.question(self, "Confirm", f"Remove {len(employee_ids)} selected employees?")

        if reply == QMessageBox.Yes:
            self.run_db_task(
                lambda: delete_employees_from_db(employee_ids),
                refresh_after=True
            )

    def add_department(self):
        selected = self.selected_employees()

        if not selected:
            QMessageBox.information(self, "Info", "No employee selected.")
            return

        selected_employees = []
        skipped_employees = []

        for emp in selected:
            if emp.dept_times and emp.dept_times[-1][0].strip().lower() == "naar huis":
                skipped_employees.append(f"{emp.lastname} {emp.firstname}")
                continue

            selected_employees.append(emp)

        if not selected_employees:
            QMessageBox.information(
                self,
                "Info",
                "No employees available to add department.\nSkipped employees: " + ", ".join(skipped_employees)
            )
            return

        dlg = AddDepartmentDialog(self, selected_employees)

        if dlg.exec() and dlg.result_data:
            data = dlg.result_data

            def done(errors):
                if errors:
                    QMessageBox.warning(self, "Warning", "\n".join(errors))

            self.run_db_task(
                lambda: add_departments_to_db(
                    data["employee_ids"],
                    data["department"],
                    data["time"],
                ),
                on_finished=done,
                refresh_after=True,
            )

    def remove_department(self):
        employee_ids = self.selected_employee_ids()

        if not employee_ids:
            QMessageBox.information(self, "Info", "No employee selected.")
            return

        def done(errors):
            if errors:
                QMessageBox.warning(self, "Warning", "\n".join(errors))

        self.run_db_task(
            lambda: remove_last_departments_from_db(employee_ids),
            on_finished=done,
            refresh_after=True,
        )

    def edit_department(self):
        selected = self.selected_employees()

        if not selected:
            QMessageBox.information(self, "Info", "No employee selected.")
            return

        dlg = EditDepartmentDialog(self, selected)

        if dlg.exec() and dlg.result_data:
            data = dlg.result_data
            self.run_db_task(
                lambda: edit_departments_in_db(
                    data["employee_ids"],
                    data["department"],
                ),
                refresh_after=True,
            )

    def mark_as_late(self):
        selected = self.selected_employees()

        if not selected:
            QMessageBox.information(self, "Info", "No employee selected.")
            return

        first_error = None

        for emp in selected:
            dlg = MarkAsLateDialog(self, emp)

            if dlg.exec() and dlg.result_data:
                data = dlg.result_data

                try:
                    self.run_db_task(
                        lambda data=data: mark_employee_late_in_db(
                            data["employee_id"],
                            data["actual_start"],
                        ),
                        refresh_after=True,
                    )
                except Exception as exc:
                    first_error = str(exc)

        if first_error:
            QMessageBox.critical(self, "Error", first_error)

    def on_model_data_changed(self, top_left, bottom_right, roles):
        info_col = len(columns) - 1

        if top_left.column() != info_col or bottom_right.column() != info_col:
            return

        emp = self.model.get_employee_at_row(top_left.row())
        if not emp:
            return

        emp_id = emp.employee_id
        info = emp.info

        self.run_db_task(
            lambda: update_employee_info_in_db(emp_id, info)
        )

    def load_excel(self):
        dlg = QFileDialog(self, "Open Excel files", "", "Excel files (*.xlsx)")
        dlg.setFileMode(QFileDialog.ExistingFiles)

        if not dlg.exec():
            return

        filepaths = dlg.selectedFiles()

        def done(count):
            QMessageBox.information(self, "Success", f"Data imported successfully. Imported rows: {count}")

        self.run_db_task(
            lambda: import_excel_to_db(filepaths),
            on_finished=done,
            refresh_after=True,
        )

    def clear_data(self):
        reply = QMessageBox.question(self, "Confirm", "Are you sure to clear all data?")

        if reply == QMessageBox.Yes:
            self.run_db_task(
                lambda: clear_all_data_in_db(),
                on_finished=lambda _: QMessageBox.information(self, "Success", "All data cleared successfully!"),
                refresh_after=True,
            )


def main():
    init_db()

    app = QApplication(sys.argv)

    main_window = MainWindow()
    main_window.showMaximized()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
