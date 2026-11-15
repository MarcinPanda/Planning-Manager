import sys
import os
import sqlite3
import pandas as pd
import warnings
from datetime import datetime


from PySide6.QtGui import QPainter, QColor, QDrag, QCursor

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QComboBox,
    QMessageBox,
    QDialog,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMenu,
    QAbstractItemView,
    QScrollArea,
    QFrame,
    QStackedWidget,
    QCheckBox,
    QGroupBox,
)

from PySide6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, Property, QMimeData, QByteArray, QDataStream, QIODevice
)



warnings.filterwarnings("ignore", category=UserWarning, module='openpyxl')



class DraggableTableWidget(QTableWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        # Ustawiamy tryb wewnętrznego przesuwania – będziemy nadpisywać startDrag oraz dropEvent
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def startDrag(self, supportedActions):
        # Pobierz pozycję kursora względem viewportu
        pos = self.viewport().mapFromGlobal(QCursor.pos())
        item = self.itemAt(pos)
        if item is None:
            return

        # Przygotuj obiekt QDrag i MIME data
        drag = QDrag(self)
        mimeData = QMimeData()
        data = QByteArray()
        stream = QDataStream(data, QIODevice.WriteOnly)
        # Zapisujemy numer wiersza i kolumny przeciąganego elementu – używamy writeInt32 (nie writeInt)
        stream.writeInt32(self.row(item))
        stream.writeInt32(self.column(item))
        mimeData.setData("application/x-employee-item", data)
        drag.setMimeData(mimeData)

        # Ustaw pixmapę przeciąganego elementu (przechwycony obszar komórki)
        rect = self.visualItemRect(item)
        drag.setPixmap(self.viewport().grab(rect))
        drag.exec_(Qt.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-employee-item"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-employee-item"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat("application/x-employee-item"):
            event.ignore()
            return

        data = event.mimeData().data("application/x-employee-item")
        stream = QDataStream(data, QIODevice.ReadOnly)
        source_row = stream.readInt32()
        source_col = stream.readInt32()

        # Ustalamy docelowy wiersz – jeśli upuszczamy na komórkę, pobieramy jej wiersz
        pos = event.pos()
        drop_index = self.indexAt(pos)
        target_row = drop_index.row()
        if target_row < 0:
            # Jeżeli upuściliśmy poza komórkami, przyjmujemy ostatni wiersz
            target_row = self.rowCount() - 1

        # Jeżeli przeciągamy element na siebie – nic nie robimy
        if source_row == target_row:
            event.ignore()
            return

        # Pobieramy przeciągany element
        dragged_item = self.takeItem(source_row, source_col)
        if dragged_item is None:
            event.ignore()
            return

        # Jeśli cel (docelowa komórka) jest zajęty (niepusta), to przesuwamy wszystkie elementy od target_row w dół
        target_item = self.item(target_row, source_col)
        if target_item is not None and target_item.text().strip() != "":
            self.insertRow(target_row)
            # Jeśli źródłowy wiersz znajduje się poniżej lub równy target_row, numeracja się przesunie
            adjusted_source = source_row + 1 if source_row >= target_row else source_row
            for col in range(self.columnCount()):
                item = self.takeItem(adjusted_source, col)
                # Jeśli komórka źródłowa jest pusta, ustawiamy pusty QTableWidgetItem
                if item is None:
                    item = QTableWidgetItem("")
                self.setItem(target_row, col, item)
        else:
            # Jeśli cel jest pusty, wstawiamy przeciągany element w jego miejsce
            self.setItem(target_row, source_col, dragged_item)

        event.acceptProposedAction()



###############################################################################
#                     Globalne stałe i listy
###############################################################################
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
DB_PATH = os.path.join(BASE_DIR, "planning_data.db")

NAME_EXCEPTIONS = ["van", "vas", "dos", "al"]

TEAM_LIST = [
    "Accu", "Ass TL", "Bufferzone", "Consolidatie", "Controle", "Cycle Count", "Emballage", "Extern",
    "Fixing Pallets", "Help Desk", "Inbound 1", "Inbound 2", "Inbound 3", "Inbound 4", "Inbound 5", "Laco",
    "Laden", "Naar Huis", "Nanomi", "Opleiding", "Orderpicker", "Porto", "Projekt", "Rangeren", "Reachtruck", "Retouren",
    "Schoonmaak", "Shiftleader", "Stock Controle", "Sturing", "Teamleider", "VAL", "Ziek"
]
TEAM_LIST.sort(key=lambda x: x.lower())

SHIFT_LIST = ["Ochtend", "Middag", "Day8to17", "Custom"]

marked_employees = set()

employees = []           # list of Employee objects
employee_index_map = {}  # employee_id -> index in employees

sort_states = {
    "lastname": True,
    "firstname": True,
    "work_hours": True,
    "computed_hours": True,
    "current_department": True
}

current_sort_column = None
current_sort_order = True

columns = (
    "marked", "lastname", "firstname", "work_hours", "computed_hours",
    "current_department", "time_dept1", "dept2", "time_dept2", "dept3", "time_dept3",
    "dept4", "time_dept4", "dept5", "time_dept5", "dept6", "time_dept6"
)

col_names = [
    "Marked", "Last Name", "First Name", "Work Hours", "Total Work Time",
    "Department 1", "Work Time 1", "Department 2", "Work Time 2", "Department 3", "Work Time 3",
    "Department 4", "Work Time 4", "Department 5", "Work Time 5", "Department 6", "Work Time 6"
]

OCHTEND_BREAKS = [(8*60+15, 8*60+30), (10*60+30, 10*60+45), (12*60+30, 13*60)]
MIDDAG_BREAKS = [(17*60+15, 17*60+30), (19*60+30, 20*60), (22*60, 22*60+15)]
DAY8TO17_BREAKS = [(10*60+30, 10*60+45), (12*60+30, 13*60), (15*60, 15*60+15)]

employee_data = []
employee_ids = []
mark_mode = False
done_state = {}
dept_intervals = {}
tree_item_index_map = {}

SPECIAL_FUNCTIONS = ["Ass TL", "Help Desk", "Teamleider", "Laco", "Shiftleader", "Sturing"]

###############################################################################
#                           Funkcje walidujące i logika
###############################################################################
class Validator:
    @staticmethod
    def validate_time_format(time_str):
        try:
            hh, mm = time_str.split(':')
            hh = int(hh)
            mm = int(mm)
            return 0 <= hh < 24 and 0 <= mm < 60
        except:
            return False

    @staticmethod
    def get_scheduled_start_time(employee):
        """Zwraca planowany czas rozpoczęcia pracy na podstawie zmian."""
        if not employee or not isinstance(employee, Employee):
            return None

        work_hours = employee.work_hours.strip()
        if "-" in work_hours:
            start_time, _ = work_hours.split("-")
            return start_time.strip()
        return None

def to_minutes(hhmm):
    if not Validator.validate_time_format(hhmm):
        return 0
    hh, mm = hhmm.split(':')
    return int(hh)*60 + int(mm)

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
        end += 24*60

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
            overlap_start = max(start, b_start)
            overlap_end = min(end, b_end)
            overlap = max(0, overlap_end - overlap_start)
            total -= overlap

    if total < 0:
        total = 0

    hours = total / 60.0
    rounded_hours = round(hours * 4) / 4.0
    return rounded_hours

def interval_hours_with_breaks(s, e, shift):
    if e < s:
        e += 24*60
    return compute_hours_with_breaks(
        f"{s//60:02d}:{s%60:02d}-{e//60:02d}:{e%60:02d}", shift
    )

def format_name(name: str) -> str:
    words = name.split()
    formatted = []
    for w in words:
        lw = w.lower()
        if lw not in NAME_EXCEPTIONS:
            formatted.append(w.capitalize())
        else:
            formatted.append(lw)
    return " ".join(formatted)

def move_lastname_prefix_to_firstname(lastname: str, firstname: str) -> (str, str):
    # Specjalne przypadki
    if lastname.lower() == "azevedo carvalho":
        lastname = "Carvalho Azevedo"
        return lastname, firstname
    if lastname.lower() == "juliao":
        lastname = "Ramos Juliao"
        return lastname, firstname
    if lastname.lower() == "wlodarczyk":
        lastname = "Wlodarkiewicz"
        return lastname, firstname

    # Ogólna logika
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


###############################################################################
#           Klasa Employee + metody
###############################################################################
class Employee:
    def __init__(self, employee_id, lastname, firstname, current_department,
                 work_hours, original_work_hours, shift, computed_hours, custom_breaks=None):
        self.employee_id = employee_id
        self.lastname = lastname
        self.firstname = firstname
        self.current_department = current_department
        self.work_hours = work_hours
        # Jeśli nie przekazano oryginalnych godzin, użyj work_hours
        self.original_work_hours = original_work_hours if original_work_hours is not None else work_hours
        self.shift = shift
        self.computed_hours = computed_hours
        self.custom_breaks = custom_breaks if custom_breaks else []
        self.dept_intervals = []
        if self.shift == "Custom" and "-" in self.work_hours:
            start_str = self.work_hours.split("-")[0].strip()
            self.dept_times = [(current_department, start_str)]
        else:
            self.dept_times = [(current_department, "")]

    def add_department(self, department, time_assigned):
        if len(self.dept_times) >= 6:
            raise ValueError("Cannot add more than 6 departments.")
        if not Validator.validate_time_format(time_assigned):
            raise ValueError("Invalid time format for department assignment.")

        new_time_assigned = to_minutes(time_assigned)
        if self.dept_times:
            last_dept, last_time_assigned = self.dept_times[-1]
            last_start = to_minutes(last_time_assigned) if last_time_assigned else 0
            # Jeśli dział nie jest "naar huis", wymuszamy, aby czas był późniejszy niż poprzedni
            if department.lower() != "naar huis" and new_time_assigned <= last_start:
                raise ValueError(
                    f"New department start time must be after the previous department ({last_dept})."
                )

        # Zachowaj kopię dept_times na wypadek potrzeby wycofania zmian
        original_dept_times = self.dept_times.copy()

        if department.lower() == "naar huis":
            # Zapisz backup oryginalnych work_hours oraz shift (jeśli jeszcze nie został ustawiony)
            if not hasattr(self, "_backup_work_hours"):
                self._backup_work_hours = self.original_work_hours
                self._backup_shift = self.shift
            start_str = self.work_hours.split("-")[0].strip()
            self.work_hours = f"{start_str}-{time_assigned}"
        # Dodajemy dział do listy
        self.dept_times.append((department, time_assigned))
        self.recalc_intervals_and_hours()

        # Zapis do bazy
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO departments (employee_id, department, time_assigned)
                VALUES (?, ?, ?)
            """, (self.employee_id, department, time_assigned))
            # Jeśli dział to "naar huis", zaktualizuj również pola work_hours oraz computed_hours w tabeli employees
            if department.lower() == "naar huis":
                cursor.execute("""
                    UPDATE employees
                    SET work_hours = ?, computed_hours = ?
                    WHERE id = ?
                """, (self.work_hours, self.computed_hours, self.employee_id))
            conn.commit()
        except Exception:
            # W przypadku błędu przywracamy poprzedni stan
            self.dept_times = original_dept_times
            self.recalc_intervals_and_hours()
            raise
        finally:
            conn.close()

    def edit_current_department(self, new_dept):
        # Najpierw zaktualizuj work_hours, jeśli to dział Porto lub inny specjalny
        # Możesz skorzystać z istniejącej funkcji adjust_work_hours.
        self.work_hours = adjust_work_hours(self.work_hours, new_dept)

        # Następnie ustaw w dept_times oraz current_department
        if self.current_department.lower() == "late":
            if self.dept_times:
                last_dept, last_time_assigned = self.dept_times[-1]
                self.dept_times[-1] = (new_dept, last_time_assigned)
            self.current_department = new_dept
        else:
            if self.dept_times:
                last_dept, last_time_assigned = self.dept_times[-1]
                self.dept_times[-1] = (new_dept, last_time_assigned)
            self.current_department = new_dept

        # Na koniec przelicz godziny
        self.recalc_intervals_and_hours()

    def recalc_intervals_and_hours(self):
        # Walidacja wejściowa
        if not self.dept_times or not isinstance(self.work_hours, str) or "-" not in self.work_hours:
            self.dept_intervals = []
            self.computed_hours = "0.00"
            return

        start_str, end_str = self.work_hours.split("-")
        start_str, end_str = start_str.strip(), end_str.strip()
        if not (Validator.validate_time_format(start_str) and Validator.validate_time_format(end_str)):
            self.dept_intervals = []
            self.computed_hours = "0.00"
            return

        start_min = to_minutes(start_str)
        end_min = to_minutes(end_str)
        if end_min < start_min:
            end_min += 24 * 60

        # Przygotowujemy listę punktów czasowych: (czas w minutach, nazwa działu)
        # Jeśli czas przypisania nie jest podany lub niepoprawny, przyjmujemy początek pracy
        times = []
        for dept, t_assigned in self.dept_times:
            dept = dept.strip()
            if t_assigned and Validator.validate_time_format(t_assigned):
                t = to_minutes(t_assigned.strip())
                if t < start_min:
                    t += 24 * 60
                times.append((t, dept))
            else:
                times.append((start_min, dept))
        # Dodajemy punkt końca pracy
        times.append((end_min, ""))

        # Agregujemy czasy dla poszczególnych działów
        dept_hours = {}
        dept_order = []
        total_hours = 0.0

        for i in range(len(times) - 1):
            s, dept = times[i]
            e, _ = times[i + 1]
            # Dla specjalnych nazw działów (np. "ziek", "naar huis") pomijamy obliczenia
            if dept.lower() in ["ziek", "naar huis"]:
                dur = 0.0
            else:
                if self.shift == "Custom":
                    start_interval = f"{s // 60:02d}:{s % 60:02d}"
                    end_interval = f"{e // 60:02d}:{e % 60:02d}"
                    dur = compute_hours_with_breaks(f"{start_interval}-{end_interval}", "Custom", self.custom_breaks)
                else:
                    dur = interval_hours_with_breaks(s, e, self.shift)
            total_hours += dur

            if dept and dept.lower() not in ["ziek", "naar huis"]:
                if dept not in dept_hours:
                    dept_hours[dept] = 0.0
                    dept_order.append(dept)
                dept_hours[dept] += dur

        self.computed_hours = f"{total_hours:.2f}"
        # Ustawiamy dept_intervals jako listę krotek (nazwa działu, łączny czas w godzinach)
        self.dept_intervals = [(d, dept_hours[d]) for d in dept_order]

    def remove_last_department(self):
        if len(self.dept_times) <= 1:
            raise ValueError("Cannot remove the initial department.")
        # Pobieramy ostatni dodany dział
        removed_dept, removed_time = self.dept_times[-1]
        self.dept_times.pop()

        # Jeśli usuwamy dział "naar huis", przywracamy oryginalne godziny pracy zapisane w kolumnie original_work_hours
        if removed_dept.lower() == "naar huis":
            conn = sqlite3.connect(DB_PATH)
            try:
                cursor = conn.cursor()
                # Odczytujemy oryginalne godziny pracy z bazy
                cursor.execute("SELECT original_work_hours FROM employees WHERE id = ?", (self.employee_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    original_hours = row[0]
                    # Przywracamy oryginalne godziny w obiekcie
                    self.work_hours = original_hours
                    # Przeliczamy godziny, aby zaktualizować computed_hours
                    self.recalc_intervals_and_hours()
                    # Aktualizujemy rekord w bazie – przywracamy work_hours i computed_hours oraz ewentualnie shift
                    cursor.execute(
                        "UPDATE employees SET work_hours = ?, computed_hours = ? WHERE id = ?",
                        (self.work_hours, self.computed_hours, self.employee_id)
                    )
                    conn.commit()
            finally:
                conn.close()

        # Przeliczamy godziny również po usunięciu działu (dla pozostałych przypadków)
        self.recalc_intervals_and_hours()

    def to_ui_values(self):
        self.recalc_intervals_and_hours()
        marked_symbol = "✅" if self.employee_id in marked_employees else ""
        ui = [marked_symbol, self.lastname, self.firstname, self.work_hours, self.computed_hours]

        max_depts = 5  # Maksymalna liczba kolumn na działy
        for (dept, dur) in self.dept_intervals[:max_depts]:
            ui.append(dept)
            ui.append(f"{dur:.2f}")
        # Uzupełnienie pustymi wartościami, gdy liczba działów jest mniejsza niż max_depts
        for _ in range(max_depts - len(self.dept_intervals)):
            ui.append("")
            ui.append("")
        return ui


###############################################################################
#                      Baza danych, init_db, reload_data
###############################################################################
def init_db():
    conn = sqlite3.connect(DB_PATH)
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
            marked INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sorting_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            column_name TEXT NOT NULL,
            sort_order TEXT NOT NULL
        )
    """)

    # Jeśli tabela już istnieje, sprawdzamy, czy kolumna original_work_hours jest obecna
    cursor.execute("PRAGMA table_info(employees)")
    columns_db = [col[1] for col in cursor.fetchall()]
    if "original_work_hours" not in columns_db:
        # Dodajemy kolumnę i ustawiamy jej wartość na bieżące work_hours dla istniejących rekordów
        cursor.execute("ALTER TABLE employees ADD COLUMN original_work_hours TEXT")
        cursor.execute("UPDATE employees SET original_work_hours = work_hours")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            department TEXT NOT NULL,
            time_assigned TEXT NOT NULL,
            FOREIGN KEY (employee_id) REFERENCES employees (id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_breaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            start INTEGER NOT NULL,
            end INTEGER NOT NULL,
            FOREIGN KEY (employee_id) REFERENCES employees (id)
        )
    """)
    conn.commit()
    conn.close()

def find_employee(lastname, firstname, work_hours):
    """Znajduje pracownika na podstawie nazwiska, imienia i godzin pracy."""
    for emp in employees:
        if (emp.lastname.lower() == lastname.lower() and
            emp.firstname.lower() == firstname.lower() and
            emp.work_hours.strip() == work_hours.strip()):
            return emp
    return None

def reload_data():
    global employees, employee_index_map, marked_employees
    employees.clear()
    employee_index_map.clear()
    marked_employees.clear()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Pobieramy 9 kolumn, w tym original_work_hours
    cursor.execute("""
        SELECT id, lastname, firstname, current_department, work_hours, original_work_hours, shift, computed_hours, marked
        FROM employees
    """)
    rows = cursor.fetchall()

    for row in rows:
        # row[:-1] zwraca 8 elementów: id, lastname, firstname, current_department,
        # work_hours, original_work_hours, shift, computed_hours
        emp = Employee(*row[:-1])
        if row[-1]:
            marked_employees.add(emp.employee_id)

        cursor.execute("""
            SELECT department, time_assigned
            FROM departments
            WHERE employee_id = ?
            ORDER BY id ASC
        """, (emp.employee_id,))
        dept_rows = cursor.fetchall()

        if dept_rows:
            emp.dept_times = [(d[0], d[1]) for d in dept_rows]
        else:
            if "-" in emp.work_hours:
                start_str, _ = emp.work_hours.split("-")
                start_str = start_str.strip()
            else:
                start_str = "06:00"
            emp.dept_times = [(emp.current_department, start_str)]

        emp.recalc_intervals_and_hours()
        employees.append(emp)
        employee_index_map[emp.employee_id] = len(employees) - 1

    conn.close()

def save_marked_state():
    """Zapisuje stan zaznaczonych pracowników w bazie danych."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE employees SET marked = 0")
    for emp_id in marked_employees:
        cursor.execute("UPDATE employees SET marked = 1 WHERE id = ?", (emp_id,))
    conn.commit()
    conn.close()


###############################################################################
#  Pomocnicze
###############################################################################
def adjust_work_hours(work_hours, department=None):
    if not isinstance(work_hours, str) or "-" not in work_hours:
        return work_hours

    start, end = work_hours.split("-")
    start = start.strip()
    end = end.strip()

    if department == "Porto":
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


###############################################################################
#               Funkcje do pliku Excel (import) i czyszczenia
###############################################################################
def load_excel_files():
    from PySide6.QtWidgets import QFileDialog
    dlg = QFileDialog(None, "Open Excel files", "", "Excel files (*.xlsx)")
    dlg.setFileMode(QFileDialog.ExistingFiles)
    filenames = []
    if dlg.exec():
        filenames = dlg.selectedFiles()
    return filenames

def load_excel(main_window):
    filepaths = load_excel_files()
    if not filepaths:
        return

    try:
        employees_list = []
        for filepath in filepaths:
            data = pd.read_excel(filepath, header=None)

            if data.shape[1] < 6:
                QMessageBox.critical(None, "Error", f"The file {filepath} does not contain enough columns (min. 6).")
                return

            lastname_col = 3
            firstname_col = 4
            work_hours_col = data.shape[1] - 1
            current_department = None
            current_shift = None

            for i in range(len(data)):
                row = data.iloc[i, :]

                val_b = row[1] if len(row) > 1 else None
                if isinstance(val_b, str) and "Warehouse" in val_b and "Week" in val_b:
                    parts = [p.strip() for p in val_b.split('/') if p.strip()]
                    if len(parts) >= 2:
                        shift_candidate = parts[1]
                        if shift_candidate in ["Ochtend", "Middag", "Day8to17"]:
                            current_shift = shift_candidate
                        else:
                            current_shift = None
                    if len(parts) >= 3:
                        current_department = parts[2]
                        if current_department == "Transport coördinator":
                            current_department = "Laco"
                    else:
                        current_department = None
                    continue

                val_d = row[lastname_col] if len(row) > lastname_col else None
                val_e = row[firstname_col] if len(row) > firstname_col else None

                if isinstance(val_d, str) and "Achternaam" in val_d:
                    continue
                if isinstance(val_e, str) and "Voornaam" in val_e:
                    continue

                if isinstance(val_d, str) and val_d.strip() != "" and isinstance(val_e, str) and val_e.strip() != "":
                    val_hours = row[work_hours_col] if len(row) > work_hours_col else None
                    dept = current_department if current_department else "Unknown"
                    shift = current_shift if current_shift else ""

                    if dept in SPECIAL_FUNCTIONS or dept == "Porto":
                        val_hours = adjust_work_hours(val_hours, dept)

                    if not shift and isinstance(val_hours, str) and "08:00-17:00" in val_hours:
                        shift = "Day8to17"

                    lastname, firstname = move_lastname_prefix_to_firstname(val_d, val_e)
                    employees_list.append([lastname, firstname, dept, val_hours, shift])

        employees_df = pd.DataFrame(employees_list, columns=['lastname', 'firstname', 'current_department', 'work_hours', 'shift'])
        employees_df = employees_df.dropna(subset=['lastname', 'firstname'])

        words_to_exclude = "Achternaam|Voornaam|Badge"
        mask = ~(
            employees_df['lastname'].str.contains(words_to_exclude, na=False, case=False) |
            employees_df['firstname'].str.contains(words_to_exclude, na=False, case=False) |
            employees_df['current_department'].str.contains(words_to_exclude, na=False, case=False) |
            employees_df['work_hours'].fillna("").str.contains(words_to_exclude, na=False, case=False)
        )
        employees_df = employees_df[mask]

        employees_df['lastname'] = employees_df['lastname'].apply(format_name)
        employees_df['firstname'] = employees_df['firstname'].apply(format_name)

        employees_df['computed_hours'] = employees_df.apply(
            lambda row_: compute_hours_with_breaks(row_['work_hours'], row_['shift']), axis=1
        )

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        for _, row_ in employees_df.iterrows():
            lastname, firstname = move_lastname_prefix_to_firstname(row_['lastname'], row_['firstname'])
            lastname = format_name(lastname)
            firstname = format_name(firstname)

            cursor.execute("""
                SELECT id FROM employees
                WHERE lastname = ? AND firstname = ? AND current_department = ? AND work_hours = ?
            """, (lastname, firstname, row_['current_department'], row_['work_hours']))
            exists = cursor.fetchone()

            if exists:
                emp_id = exists[0]
                cursor.execute("""
                    UPDATE employees
                    SET shift = ?,
                        computed_hours = ?
                    WHERE id = ?
                """, (
                    row_['shift'],
                    row_['computed_hours'],
                    emp_id
                ))
            else:
                cursor.execute("""
                    INSERT INTO employees (lastname, firstname, current_department, work_hours, shift, computed_hours, marked)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    lastname,
                    firstname,
                    row_['current_department'],
                    row_['work_hours'],
                    row_['shift'],
                    row_['computed_hours'],
                    0
                ))
                emp_id = cursor.lastrowid
                if isinstance(row_['work_hours'], str) and "-" in row_['work_hours']:
                    start_str = row_['work_hours'].split("-")[0].strip()

                cursor.execute("""
                    INSERT INTO departments (employee_id, department, time_assigned)
                    VALUES (?, ?, ?)
                """, (emp_id, row_['current_department'], start_str))

        conn.commit()
        conn.close()

        reload_data()
        main_window.display_all_employees()

        QMessageBox.information(None, "Success", "Data imported successfully!")

    except Exception as e:
        QMessageBox.critical(None, "Error", f"Failed to load data: {e}")

###############################################################################
#   Główne okno PySide6
###############################################################################
class ToggleButton(QCheckBox):
    def __init__(self,
                 width=10,
                 height=25,
                 bgColor='#777',
                 circleColor='#DDD',
                 activeColor='#00BCff',
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
        if state == 2:  # checked
            self.animation.setEndValue(self.width() - self._circle_diameter - 3)
        else:  # unchecked
            self.animation.setEndValue(3)
        self.animation.start()

    def hitButton(self, pos):
        return self.contentsRect().contains(pos)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        p.setBrush(QColor(self._active_color if self.isChecked() else self._bg_color))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(rect, rect.height() // 2, rect.height() // 2)

        p.setBrush(QColor(self._circle_color))
        p.drawEllipse(self._circle_position, 3, self._circle_diameter, self._circle_diameter)
        p.end()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Planning Manager")
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        self.setCentralWidget(central_widget)

        top_bar = QWidget()
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 10, 10, 10)
        top_layout.setSpacing(5)
        top_layout.setAlignment(Qt.AlignLeft)

        self.label_planning = QLabel("Planning")
        top_layout.addWidget(self.label_planning)

        self.toggle_button = ToggleButton(
            width=70,
            bgColor='#777',
            circleColor='#DDD',
            activeColor='#00BCff',
            animationCurve=QEasingCurve.Linear
        )
        self.toggle_button.setChecked(False)
        self.toggle_button.stateChanged.connect(self.on_toggle_state_changed)
        top_layout.addWidget(self.toggle_button)

        self.label_monitoring = QLabel("Monitoring")
        top_layout.addWidget(self.label_monitoring)
        main_layout.addWidget(top_bar)

        self.stacked_widget = QStackedWidget()
        self.planning_view = PlanningView(self)
        self.monitoring_view = MonitoringView(self)
        self.stacked_widget.addWidget(self.planning_view)
        self.stacked_widget.addWidget(self.monitoring_view)
        main_layout.addWidget(self.stacked_widget)

        self.show_planning()

    def closeEvent(self, event):
        reply = QMessageBox.question(self, "Exit", "Are you sure you want to exit?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            event.accept()
        else:
            event.ignore()

    def on_toggle_state_changed(self, state):
        if state == 2:
            self.show_monitoring()
        else:
            self.show_planning()

    def handle_toggle_view(self, checked: bool):
        if checked:
            self.show_monitoring()
        else:
            self.show_planning()

    def show_planning(self):
        self.stacked_widget.setCurrentIndex(0)

    def show_monitoring(self):
        self.monitoring_view.load_departments_employees()
        self.stacked_widget.setCurrentIndex(1)

    def display_all_employees(self):
        self.planning_view.display_all_employees()

    def refresh_monitoring(self):
        if hasattr(self.monitoring_view, 'load_departments_employees'):
            self.monitoring_view.load_departments_employees()


class EmployeeBlock(QLabel):
    def __init__(self, name, color):
        super().__init__(name)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"background-color: {color}; color: white; border-radius: 5px; padding: 10px;")
        self.setFixedSize(50, 25)


###############################################################################
#   MonitoringView
###############################################################################
class MonitoringView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        """
        Inicjuje interfejs widoku monitoringu z trzema sekcjami:
         1) Piking – tabela z pracownikami z działu Orderpicker
         2) Reach Outbound – tabela z pracownikami z działu Reachtruck
         3) Pozostałe działy – siatka działów (tak jak dotychczas)
        Całość opakowujemy w QScrollArea, dzięki czemu cały widok jest przewijalny.
        """
        main_layout = QVBoxLayout(self)

        # Utwórz obszar przewijany i ustaw, że widget wewnętrzny ma się rozciągać
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)

        # Główny kontener – umieszczamy w nim wszystkie sekcje
        container = QWidget()
        container_layout = QVBoxLayout(container)

        # --- Sekcja 1: Piking ---
        piking_box = QGroupBox("Piking")
        piking_layout = QVBoxLayout(piking_box)
        self.piking_table = EmployeeTableWidget()
        self.setup_piking_table()  # Nowa metoda konfigurująca tabelę Piking
        piking_layout.addWidget(self.piking_table)
        container_layout.addWidget(piking_box)

        # --- Sekcja 2: Reach Outbound ---
        reach_box = QGroupBox("Reach Outbound")
        reach_box.setFixedWidth(815)
        reach_layout = QVBoxLayout(reach_box)
        self.reach_outbound_table = EmployeeTableWidget()
        self.setup_reach_outbound_table()  # Konfigurujemy tabelę Reach Outbound (patrz niżej)
        reach_layout.addWidget(self.reach_outbound_table)
        container_layout.addWidget(reach_box)

        # --- Sekcja 2: Pozostałe działy ---
        # Lista działów – z pominięciem działu, który obsługujemy w Reach Outbound (np. "Reachtruck")
        departments = [
            "Accu", "Ass TL", "Bufferzone", "Consolidatie", "Controle",
            "Cycle Count", "Emballage", "Extern", "Fixing Pallets", "Help Desk",
            "Inbound 1", "Inbound 2", "Inbound 3", "Inbound 4", "Inbound 5",
            "Laco", "Laden", "Naar Huis", "Nanomi", "Opleiding", "Orderpicker",
            "Porto", "Projekt", "Rangeren", "Retouren", "Schoonmaak", "Shiftleader",
            "Stock Controle", "Sturing", "Teamleider", "VAL", "Ziek"
        ]
        grid_container = QWidget()
        grid_layout = QGridLayout(grid_container)
        self.dept_tables = {}  # Słownik: nazwa_działu -> QTableWidget

        columns_in_row = 4
        row_idx, col_idx = 0, 0
        for dept_name in departments:
            group_box = QFrame()
            group_box.setFrameShape(QFrame.StyledPanel)
            group_layout = QVBoxLayout(group_box)

            label_dept = QLabel(dept_name)
            label_dept.setAlignment(Qt.AlignCenter)
            label_dept.setStyleSheet("font-weight: bold;")
            group_layout.addWidget(label_dept)

            table = EmployeeTableWidget(0, 1)
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setVisible(False)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

            group_layout.addWidget(table)
            self.dept_tables[dept_name] = table

            grid_layout.addWidget(group_box, row_idx, col_idx)
            col_idx += 1
            if col_idx >= columns_in_row:
                col_idx = 0
                row_idx += 1

        container_layout.addWidget(grid_container)

        # Ustaw widget kontenera jako widget w obszarze przewijanym
        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area)
        self.setLayout(main_layout)

    def setup_piking_table(self):
        """
        Konfiguruje tabelę 'Piking' z 11 kolumnami:
        Kolumny: Employee, Choco (12), Pladis (22), Grenade (24), Pieterciel (15),
                 Nutricia (10), Essity (14), Alpro (23), Petfood (13), ITR (18, 20), Info
        """
        headers = [
            "Employee", "Choco (12)", "Pladis (22)", "Grenade (24)", "Pieterciel (15)", "Nutricia (10)", "Essity (14)",
            "Alpro (23)", "Petfood (13)", "ITR (18, 20)", "Info"]
        self.piking_table.setColumnCount(len(headers))  # Ustawiamy 11 kolumn
        self.piking_table.setHorizontalHeaderLabels(headers)

        # Ustawiamy stałą szerokość dla kolumny Employee oraz kolumn 1-9
        self.piking_table.setColumnWidth(0, 180)  # Employee
        for col in range(1, 10):
            self.piking_table.setColumnWidth(col, 85)

        # Ostatnia kolumna ("Info") rozciąga się na pozostałą szerokość
        self.piking_table.horizontalHeader().setSectionResizeMode(10, QHeaderView.Stretch)

        # Wyłączamy paski przewijania
        self.piking_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.piking_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Ustawienia drag & drop
        self.piking_table.setDragDropMode(QAbstractItemView.DragDrop)
        self.piking_table.setDefaultDropAction(Qt.MoveAction)
        self.piking_table.setDragEnabled(True)
        self.piking_table.setAcceptDrops(True)
        self.piking_table.setDropIndicatorShown(True)

    def setup_reach_outbound_table(self):
        """
        Konfiguruje tabelę 'Reach Outbound':
        8 kolumn -> Employee, Noord, Zuid, Replenish, Consolidatie, Kantel, Extra, Info
        """
        headers = ["Employee", "Noord", "Zuid", "Replenish", "Consolidatie", "Kantel", "Extra", "Info"]
        self.reach_outbound_table.setColumnCount(len(headers))
        self.reach_outbound_table.setHorizontalHeaderLabels(headers)

        # Ustawiamy stałe szerokości dla kolumn z nazwami pracownika i poddziałami
        self.reach_outbound_table.setColumnWidth(0, 180)  # Employee
        for col in range(1, 7):
            self.reach_outbound_table.setColumnWidth(col, 85)  # Poddziały

        # Kolumna "Info" rozciąga się na pozostałą szerokość:
        self.reach_outbound_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Fixed)
        self.reach_outbound_table.setColumnWidth(7, 85)  # lub inna szerokość, która Ci odpowiada

        self.reach_outbound_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.reach_outbound_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Włączamy obsługę drag & drop
        self.reach_outbound_table.setDragDropMode(QAbstractItemView.DragDrop)
        self.reach_outbound_table.setDefaultDropAction(Qt.MoveAction)
        self.reach_outbound_table.setDragEnabled(True)
        self.reach_outbound_table.setAcceptDrops(True)
        self.reach_outbound_table.setDropIndicatorShown(True)

    def fill_piking_table(self, piking_emps):
        """
        Wstawia do tabeli 'Piking' pracowników z listy piking_emps.
        Tabela ma zawsze 15 wierszy.
        """
        sub_depts = ["Noord", "Zuid", "Replenish", "Consolidatie", "Kantel", "Extra"]
        fixed_rows = 15
        self.piking_table.setRowCount(fixed_rows)
        for row_idx in range(fixed_rows):
            if row_idx < len(piking_emps):
                emp = piking_emps[row_idx]
                emp_item = QTableWidgetItem(f"{emp.firstname} {emp.lastname}")
                self.piking_table.setItem(row_idx, 0, emp_item)
                # W tym przykładzie nie wstawiamy automatycznie X dla poddziałów – jak wspomniałeś
                # Możesz pominąć wypełnianie kolumn 1-6 (lub ustawić je puste)
                for col in range(1, 8):
                    self.piking_table.setItem(row_idx, col, QTableWidgetItem(""))
            else:
                for col in range(self.piking_table.columnCount()):
                    self.piking_table.setItem(row_idx, col, QTableWidgetItem(""))
        # Ustaw stałą wysokość tak, aby widocznych było 15 wierszy
        default_row_height = self.piking_table.verticalHeader().defaultSectionSize()
        header_height = self.piking_table.horizontalHeader().height()
        fixed_height = default_row_height * 15 + header_height
        self.piking_table.setFixedHeight(fixed_height)


    def fill_reach_outbound_table(self, reach_emps):
        """
        Wstawia do tabeli 'Reach Outbound' pracowników z listy reach_emps.
        Kolumna 0 – Employee,
        Kolumny 1-6 – poddziały: Noord, Zuid, Replenish, Consolidatie, Kantel, Extra,
        Kolumna 7 – Info.
        Tabela ma zawsze 15 wierszy (puste wiersze są wyświetlane, jeśli brak danych).
        """
        sub_depts = ["Noord", "Zuid", "Replenish", "Consolidatie", "Kantel", "Extra"]
        fixed_rows = 15  # Stała liczba wierszy
        self.reach_outbound_table.setRowCount(fixed_rows)

        for row_idx in range(fixed_rows):
            if row_idx < len(reach_emps):
                emp = reach_emps[row_idx]
                # Kolumna 0 – Employee Name
                emp_item = QTableWidgetItem(f"{emp.firstname} {emp.lastname}")
                self.reach_outbound_table.setItem(row_idx, 0, emp_item)
                # Kolumny 1-6 – dla każdego poddziału
                existing_depts = [d.lower() for (d, dur) in emp.dept_intervals]
                # Kolumna 7 – Info (na razie pusta, możesz dodać dowolną informację)
                info_item = QTableWidgetItem("")
                info_item.setTextAlignment(Qt.AlignCenter)
                self.reach_outbound_table.setItem(row_idx, 7, info_item)
            else:
                # Dla pustych wierszy – ustawiamy puste komórki we wszystkich kolumnach
                for col in range(self.reach_outbound_table.columnCount()):
                    self.reach_outbound_table.setItem(row_idx, col, QTableWidgetItem(""))

        # Ustawiamy stałą wysokość tabeli tak, aby zawsze wyświetlała 15 wierszy
        default_row_height = self.reach_outbound_table.verticalHeader().defaultSectionSize()
        header_height = self.reach_outbound_table.horizontalHeader().height()
        fixed_height = default_row_height * 15 + header_height
        self.reach_outbound_table.setFixedHeight(fixed_height)

    def load_departments_employees(self):
        # --- Sekcja Piking ---
        self.piking_table.clearContents()
        self.piking_table.setRowCount(15)
        piking_emps = [emp for emp in employees if emp.current_department.lower() == "orderpicker"]
        self.fill_piking_table(piking_emps)

        # --- Sekcja Reach Outbound ---
        self.reach_outbound_table.clearContents()
        self.reach_outbound_table.setRowCount(15)
        reach_emps = [emp for emp in employees if emp.current_department.lower() == "reachtruck"]
        self.fill_reach_outbound_table(reach_emps)

        # --- Sekcja pozostałych działów (jak wcześniej) ---
        for dept_name, table in self.dept_tables.items():
            table.clearContents()
            table.setRowCount(0)
        dept_emps = {dept: [] for dept in self.dept_tables.keys()}
        for emp in employees:
            if emp.current_department.lower() in ["reachtruck", "orderpicker"]:
                continue
            if emp.current_department in dept_emps:
                dept_emps[emp.current_department].append(emp)
        for dept_name, emp_list in dept_emps.items():
            table = self.dept_tables[dept_name]
            row_count = max(3, len(emp_list))
            table.setRowCount(row_count)
            for i, emp in enumerate(emp_list):
                item = QTableWidgetItem(f"{emp.firstname} {emp.lastname}")
                table.setItem(i, 0, item)
            table.resizeRowsToContents()


class EmployeeTableWidget(QTableWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        # Ustawiamy tryb wewnętrznego przesuwania – będziemy jednak modyfikować dropEvent
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def startDrag(self, supportedActions):
        # Przygotowujemy MIME data z informacją o źródłowym wierszu
        selected = self.selectedItems()
        if not selected:
            return
        source_row = selected[0].row()
        mimeData = QMimeData()
        data = QByteArray()
        stream = QDataStream(data, QIODevice.WriteOnly)
        stream.writeInt32(source_row)  # zapisujemy numer wiersza
        mimeData.setData("application/x-employee-row", data)
        drag = QDrag(self)
        drag.setMimeData(mimeData)
        drag.exec(supportedActions)

    def dropEvent(self, event):
        # Pobieramy docelową pozycję dropa
        pos = event.pos()
        drop_index = self.indexAt(pos)
        target_row = drop_index.row()
        if target_row < 0:
            # Jeśli nie trafiliśmy na żadną komórkę, ustaw target_row na ostatni widoczny wiersz
            target_row = self.rowCount() - 1

        # Odczytujemy numer wiersza źródłowego z MIME data
        mime = event.mimeData()
        if not mime.hasFormat("application/x-employee-row"):
            super().dropEvent(event)
            return
        data = mime.data("application/x-employee-row")
        stream = QDataStream(data, QIODevice.ReadOnly)
        source_row = stream.readInt()

        # Jeżeli przeciągamy wiersz na siebie, nic nie robimy
        if source_row == target_row:
            event.ignore()
            return

        # Sprawdzamy, czy wiersz źródłowy jest zajęty (tzn. zawiera dane – np. w kolumnie 0)
        source_item = self.item(source_row, 0)
        if not source_item or source_item.text().strip() == "":
            event.ignore()
            return

        # Sprawdzamy, czy wiersz docelowy jest zajęty (czyli zawiera jakiś tekst)
        target_item = self.item(target_row, 0)
        if target_item and target_item.text().strip() != "":
            # Jeżeli cel jest zajęty, to:
            # 1. Wstawiamy nowy wiersz na pozycji target_row (przesuwając w dół istniejące)
            self.insertRow(target_row)
            # 2. Przenosimy zawartość wiersza źródłowego do nowo wstawionego wiersza
            # (uwzględniamy, że jeśli source_row >= target_row, to po wstawieniu nowego wiersza numeracja ulegnie zmianie)
            adjusted_source = source_row + 1 if source_row >= target_row else source_row
            for col in range(self.columnCount()):
                item = self.takeItem(adjusted_source, col)
                self.setItem(target_row, col, item)
            # Uwaga: wiersze poniżej zostaną automatycznie przesunięte – puste wiersze pozostaną puste.
        else:
            # Jeżeli cel jest pusty, to przenosimy wiersz źródłowy na target_row
            for col in range(self.columnCount()):
                item = self.takeItem(source_row, col)
                self.setItem(target_row, col, item)
        event.accept()


###############################################################################
#   PlanningView
###############################################################################
class PlanningView(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(5)

        top_layout = QHBoxLayout()
        self.main_layout.addLayout(top_layout)
        top_layout.setContentsMargins(5, 5, 5, 5)
        top_layout.setSpacing(3)

        self.load_button = QPushButton("Import Excel")
        self.load_button.setFixedWidth(120)
        self.load_button.setMinimumHeight(40)
        self.load_button.clicked.connect(lambda: load_excel(self.main_window))
        top_layout.addWidget(self.load_button)

        self.clear_button = QPushButton("Clear Data")
        self.clear_button.setFixedWidth(120)
        self.clear_button.setMinimumHeight(40)
        self.clear_button.clicked.connect(self.clear_data_clicked)
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

        self.toggle_mark_button = QPushButton("Marking Mode OFF")
        self.toggle_mark_button.setFixedWidth(150)
        self.toggle_mark_button.setMinimumHeight(40)
        self.toggle_mark_button.clicked.connect(self.toggle_mark_mode)
        top_layout.addWidget(self.toggle_mark_button)

        self.table = DraggableTableWidget(0, 1)
        self.table.cellClicked.connect(self.mark_employee)
        self.table.setColumnCount(5 + 12)
        self.table.setHorizontalHeaderLabels(col_names)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().sectionClicked.connect(self.sort_table)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        self.table.currentCellChanged.connect(self.on_current_cell_changed)
        self.table.horizontalHeader().setStyleSheet("font-weight: normal;")

        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 140)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 100)
        self.table.setColumnWidth(5, 100)
        self.table.setColumnWidth(6, 100)
        self.table.setColumnWidth(7, 100)
        self.table.setColumnWidth(8, 100)
        self.table.setColumnWidth(9, 100)
        self.table.setColumnWidth(10, 100)
        self.table.setColumnWidth(11, 100)
        self.table.setColumnWidth(12, 100)
        self.table.setColumnWidth(13, 100)
        self.table.setColumnWidth(14, 100)
        self.table.setColumnWidth(15, 100)
        self.table.setColumnWidth(16, 100)
        self.table.setColumnWidth(17, 100)
        self.table.setColumnWidth(16, 100)

        self.main_layout.addWidget(self.table)

    def toggle_mark_mode(self):
        """Przełączanie trybu oznaczania pracowników (marking mode)."""
        global mark_mode
        mark_mode = not mark_mode
        self.toggle_mark_button.setText("Marking Mode ON" if mark_mode else "Marking Mode OFF")
        save_marked_state()

    def on_current_cell_changed(self, currentRow, currentColumn, previousRow, previousColumn):
        """Automatyczne oznaczanie/odznaczanie przy nawigacji klawiaturą w Mark Mode."""
        global mark_mode, marked_employees
        if not mark_mode or currentRow == previousRow:
            return
        if currentRow < 0 or currentRow >= self.table.rowCount():
            return

        lastname_item = self.table.item(currentRow, 1)
        firstname_item = self.table.item(currentRow, 2)
        work_hours_item = self.table.item(currentRow, 3)
        if not (lastname_item and firstname_item and work_hours_item):
            return

        lastname = lastname_item.text().strip()
        firstname = firstname_item.text().strip()
        work_hours = work_hours_item.text().strip()
        emp = find_employee(lastname, firstname, work_hours)
        if not emp:
            return

        is_marked = False
        if emp.employee_id in marked_employees:
            marked_employees.remove(emp.employee_id)
        else:
            marked_employees.add(emp.employee_id)
            is_marked = True

        self.table.blockSignals(True)
        try:
            self.update_marked_icon_in_row(currentRow, is_marked)
            self.table.selectRow(currentRow)
        finally:
            self.table.blockSignals(False)

    def update_marked_icon_in_row(self, row, is_marked):
        if row < 0 or row >= self.table.rowCount():
            return
        symbol = "✅" if is_marked else ""
        item = QTableWidgetItem(symbol)
        item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 0, item)

    def add_employee(self):
        """Wywołuje dialog AddEmployeeDialog i dodaje pracownika."""
        dlg = AddEmployeeDialog(self)
        if dlg.exec():
            self.display_all_employees()
            self.main_window.refresh_monitoring()

    def remove_employee(self):
        """Usuwa zaznaczonych pracowników z bazy i zapisuje stan."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "Info", "No employee selected.")
            return

        reply = QMessageBox.question(self, "Confirm", f"Remove {len(selected_rows)} selected employees?")
        if reply == QMessageBox.Yes:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            for row_idx in selected_rows:
                row = row_idx.row()
                lastname = self.table.item(row, 1).text()
                firstname = self.table.item(row, 2).text()
                work_hours = self.table.item(row, 3).text()
                emp = find_employee(lastname, firstname, work_hours)
                if emp:
                    cursor.execute("DELETE FROM employees WHERE id = ?", (emp.employee_id,))
                    marked_employees.discard(emp.employee_id)

            conn.commit()
            conn.close()
            save_marked_state()
            reload_data()
            self.display_all_employees()
            self.main_window.refresh_monitoring()

    def mark_employee(self, row, column):
        """Zaznaczanie i odznaczanie pracowników w trybie Marking Mode."""
        global mark_mode, marked_employees
        clicked_row = row
        self.table.selectRow(clicked_row)
        if not mark_mode:
            return

        lastname_item = self.table.item(row, 1)
        firstname_item = self.table.item(row, 2)
        work_hours_item = self.table.item(row, 3)
        if lastname_item and firstname_item and work_hours_item:
            lastname = lastname_item.text().strip()
            firstname = firstname_item.text().strip()
            work_hours = work_hours_item.text().strip()

            emp = find_employee(lastname, firstname, work_hours)
            if emp:
                if emp.employee_id in marked_employees:
                    marked_employees.remove(emp.employee_id)
                else:
                    marked_employees.add(emp.employee_id)

        self.display_all_employees()
        if clicked_row < self.table.rowCount():
            self.table.selectRow(clicked_row)

    def show_context_menu(self, pos):
        """Menu kontekstowe po kliknięciu PPM w tabeli."""
        if self.table.rowCount() == 0:
            return
        row_index = self.table.currentRow()
        if row_index < 0:
            return

        context_menu = QMenu(self)
        context_menu.addAction("Add department", self.add_department)
        context_menu.addAction("Edit department", self.edit_department)
        context_menu.addAction("Remove last department", self.remove_department)
        context_menu.addAction("Late", self.mark_as_late)
        context_menu.exec(self.table.mapToGlobal(pos))

    def display_all_employees(self):
        """Wyświetla pracowników w tabeli z poprawioną obsługą oznaczania i optymalizacją wydajności."""
        global employees, current_sort_column, current_sort_order
        load_sorting_state()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        col_map = {
            "marked": lambda e: e.employee_id in marked_employees,
            "lastname": lambda e: e.lastname.casefold() if e.lastname else "",
            "firstname": lambda e: e.firstname.casefold() if e.firstname else "",
            "work_hours": lambda e: e.work_hours if e.work_hours else "",
            "computed_hours": lambda e: float(str(e.computed_hours).replace(',', '.')) if e.computed_hours else 0.0,
            "current_department": lambda e: e.current_department.casefold() if e.current_department else "",
        }

        if current_sort_column in col_map:
            key_func = col_map[current_sort_column]
            sorted_emps = sorted(employees, key=key_func, reverse=not current_sort_order)
        else:
            sorted_emps = employees

        if not sorted_emps:
            self.table.setSortingEnabled(True)
            return

        self.table.setRowCount(len(sorted_emps))

        for row_idx, emp in enumerate(sorted_emps):
            row_vals = emp.to_ui_values()
            formatted_vals = [
                str(row_vals[i]) if i < len(row_vals) and row_vals[i] is not None else ""
                for i in range(len(columns))
            ]
            for col_idx, val in enumerate(formatted_vals):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                if col_idx == 0:
                    marked_symbol = "✅" if emp.employee_id in marked_employees else ""
                    item.setText(marked_symbol)
                self.table.setItem(row_idx, col_idx, item)

        self.table.setSortingEnabled(True)

    def sort_table(self, index):
        global current_sort_column, current_sort_order
        column_map = {
            0: "marked",
            1: "lastname",
            2: "firstname",
            3: "work_hours",
            4: "computed_hours",
            5: "current_department"
        }

        if index in column_map:
            column_name = column_map[index]
            if column_name == current_sort_column:
                current_sort_order = not current_sort_order
            else:
                current_sort_column = column_name
                current_sort_order = True

            save_sorting_state(current_sort_column, current_sort_order)
            self.table.setSortingEnabled(False)

            key_func = {
                "marked": lambda e: e.employee_id in marked_employees,
                "lastname": lambda e: e.lastname.casefold(),
                "firstname": lambda e: e.firstname.casefold(),
                "work_hours": lambda e: e.work_hours,
                "computed_hours": lambda e: float(e.computed_hours) if e.computed_hours else 0.0,
                "current_department": lambda e: e.current_department.casefold(),
            }.get(current_sort_column, lambda e: e.lastname.casefold())

            sorted_emps = sorted(employees, key=key_func, reverse=not current_sort_order)
            self.table.clearContents()
            self.table.setRowCount(len(sorted_emps))

            for row_idx, emp in enumerate(sorted_emps):
                row_vals = emp.to_ui_values()
                for col_idx, val in enumerate(row_vals):
                    item = QTableWidgetItem(str(val) if val else "")
                    item.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(row_idx, col_idx, item)

            self.table.setSortingEnabled(True)

    def add_department(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "Info", "No employee selected.")
            return

        selected_employees = []
        for row_idx in selected_rows:
            row = row_idx.row()
            lastname = self.table.item(row, 1).text()
            firstname = self.table.item(row, 2).text()
            work_hours = self.table.item(row, 3).text()
            emp = find_employee(lastname, firstname, work_hours)
            if emp:
                selected_employees.append(emp)

        if not selected_employees:
            QMessageBox.information(self, "Info", "No valid employees selected.")
            return

        dlg = AddDepartmentDialog(self, selected_employees)
        if dlg.exec():
            # Po dodaniu działu usuwamy oznaczenie:
            for emp in selected_employees:
                if emp.employee_id in marked_employees:
                    marked_employees.remove(emp.employee_id)
            save_marked_state()  # Zapisujemy stan do bazy

            reload_data()
            self.display_all_employees()
            self.main_window.refresh_monitoring()

    def edit_department(self):
        """Edytuje (zmienia) aktualny dział zaznaczonym pracownikom."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "Info", "No employee selected.")
            return

        selected_employees = []
        for row_idx in selected_rows:
            row = row_idx.row()
            vals = [
                self.table.item(row, c).text() if self.table.item(row, c) else ""
                for c in range(self.table.columnCount())
            ]
            if len(vals) < 4:
                continue
            lastname, firstname, work_hours = vals[1], vals[2], vals[3]
            emp = find_employee(lastname, firstname, work_hours)
            if emp:
                selected_employees.append(emp)

        if not selected_employees:
            QMessageBox.information(self, "Info", "No valid employees selected.")
            return

        dlg = EditDepartmentDialog(self, selected_employees)
        if dlg.exec():
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            for emp in selected_employees:
                cursor.execute("""
                    UPDATE employees
                    SET current_department = ?, computed_hours = ?, work_hours = ?
                    WHERE id = ?
                """, (emp.current_department, emp.computed_hours, emp.work_hours, emp.employee_id))

                if emp.dept_times:
                    cursor.execute("""
                        UPDATE departments
                        SET department = ?
                        WHERE id = (
                            SELECT id FROM departments
                            WHERE employee_id = ?
                            ORDER BY id DESC
                            LIMIT 1
                        )
                    """, (emp.current_department, emp.employee_id))
            conn.commit()
            conn.close()

            # Po edycji działu usuwamy oznaczenie:
            for emp in selected_employees:
                if emp.employee_id in marked_employees:
                    marked_employees.remove(emp.employee_id)
            save_marked_state()

            reload_data()
            self.display_all_employees()
            self.main_window.refresh_monitoring()

    def remove_department(self):
        """Usuwa ostatni dodany dział zaznaczonemu pracownikowi."""
        row = self.table.currentRow()
        if row < 0:
            return
        vals = [
            self.table.item(row, c).text() if self.table.item(row, c) else ""
            for c in range(self.table.columnCount())
        ]
        if len(vals) < 4:
            return
        lastname, firstname, work_hours = vals[1], vals[2], vals[3]
        emp = find_employee(lastname, firstname, work_hours)
        if not emp:
            return
        if len(emp.dept_times) <= 1:
            QMessageBox.information(self, "Info", "No additional departments to remove.")
            return

        last_dept = emp.dept_times[-1][0]
        emp.remove_last_department()

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM departments
            WHERE id = (
                SELECT id FROM departments
                WHERE employee_id = ? AND department = ?
                ORDER BY id DESC LIMIT 1
            )
        """, (emp.employee_id, last_dept))
        conn.commit()
        conn.close()

        # (Tu nie ma informacji, czy mamy usuwać oznaczenie —
        #  w razie potrzeby można też usunąć z marked_employees.)

        reload_data()
        self.display_all_employees()
        self.main_window.refresh_monitoring()

    def mark_as_late(self):
        """Oznacza zaznaczonych pracowników jako 'Late' (spóźnionych)."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "Info", "No employees selected.")
            return

        selected_employees = []
        for row_idx in selected_rows:
            row = row_idx.row()
            vals = [
                self.table.item(row, c).text() if self.table.item(row, c) else ""
                for c in range(self.table.columnCount())
            ]
            if len(vals) < 4:
                continue
            lastname, firstname, work_hours = vals[1], vals[2], vals[3]
            emp = find_employee(lastname, firstname, work_hours)
            if emp:
                selected_employees.append(emp)

        if not selected_employees:
            QMessageBox.information(self, "Info", "No valid employees selected.")
            return

        dlg = MarkAsLateDialog(self, selected_employees)
        if dlg.exec():
            self.display_all_employees()
            self.main_window.refresh_monitoring()

    def clear_data_clicked(self):
        reply = QMessageBox.question(self, "Confirm", "Are you sure to clear all data?")
        if reply == QMessageBox.Yes:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='employees'")
            if not cursor.fetchone():
                QMessageBox.critical(self, "Error", "Table 'employees' does not exist!")
                return

            cursor.execute("DELETE FROM employees")
            cursor.execute("DELETE FROM departments")
            conn.commit()
            conn.close()

            reload_data()
            self.display_all_employees()
            self.main_window.refresh_monitoring()

###############################################################################
#   MarkAsLateDialog
###############################################################################
class MarkAsLateDialog(QDialog):
    def __init__(self, parent, employees):
        super().__init__(parent)
        self.setWindowTitle("Mark as Late")
        self.setGeometry(420, 420, 250, 150)
        self.employees = employees

        layout = QVBoxLayout(self)
        self.label_info = QLabel("Enter actual start time of employee:")
        layout.addWidget(self.label_info)

        self.time_edit = QLineEdit()
        layout.addWidget(self.time_edit)

        if employees:
            planned_start = Validator.get_scheduled_start_time(employees[0])
            if planned_start:
                planned_start_minutes = to_minutes(planned_start)
                default_late_minutes = planned_start_minutes + 10
                default_time_str = f"{default_late_minutes // 60:02d}:{default_late_minutes % 60:02d}"
                self.time_edit.setText(default_time_str)

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
        """Ustawia nowy czas rozpoczęcia pracy dla zaznaczonych pracowników,
           przelicza godziny, zapisuje do bazy."""
        actual_start = self.time_edit.text().strip()
        if not Validator.validate_time_format(actual_start):
            QMessageBox.critical(self, "Error", "Invalid time format. Please use HH:MM.")
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        for emp in self.employees:
            old_work_hours = emp.work_hours
            if "-" not in old_work_hours:
                continue
            old_start, old_end = old_work_hours.split("-")
            old_start = old_start.strip()
            old_end = old_end.strip()

            emp.work_hours = f"{actual_start}-{old_end}"
            emp.recalc_intervals_and_hours()

            cursor.execute("""
                UPDATE employees
                SET work_hours = ?, computed_hours = ?
                WHERE id = ?
            """, (emp.work_hours, emp.computed_hours, emp.employee_id))

        conn.commit()
        conn.close()
        self.accept()

###############################################################################
#   AddEmployeeDialog
###############################################################################
class AddEmployeeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Employee")
        self.setGeometry(300, 300, 470, 180)
        self.work_hours_var = ""
        self.break1_var = ""
        self.break2_var = ""
        self.break3_var = ""

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
        layout.addWidget(self.work_hours_edit, 2, 1)

        layout.addWidget(QLabel("Break 1:"), 2, 2)
        self.break1_edit = QLineEdit()
        layout.addWidget(self.break1_edit, 2, 3)

        layout.addWidget(QLabel("Break 2:"), 3, 0)
        self.break2_edit = QLineEdit()
        layout.addWidget(self.break2_edit, 3, 1)

        layout.addWidget(QLabel("Break 3:"), 3, 2)
        self.break3_edit = QLineEdit()
        layout.addWidget(self.break3_edit, 3, 3)

        btn_layout = QHBoxLayout()
        self.confirm_btn = QPushButton("Confirm")
        self.confirm_btn.clicked.connect(self.on_confirm)
        self.confirm_btn.setFixedHeight(35)
        btn_layout.addWidget(self.confirm_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.cancel_btn.setFixedHeight(35)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout, 4, 0, 1, 4)

        self.dept_combo.currentIndexChanged.connect(self.update_displayed_times)
        self.shift_combo.currentIndexChanged.connect(self.update_displayed_times)
        self.update_displayed_times()
        self.setLayout(layout)

    def update_displayed_times(self):
        selected_shift = self.shift_combo.currentText().strip()
        selected_dept = self.dept_combo.currentText().strip()

        if selected_shift == "Custom":
            self.work_hours_edit.setReadOnly(False)
            self.break1_edit.setReadOnly(False)
            self.break2_edit.setReadOnly(False)
            self.break3_edit.setReadOnly(False)
            # Przykład: ciemne tło, biały tekst:
            editable_style = "background-color: #2b2b2b; color: white;"
        else:
            self.work_hours_edit.setReadOnly(True)
            self.break1_edit.setReadOnly(True)
            self.break2_edit.setReadOnly(True)
            self.break3_edit.setReadOnly(True)
            editable_style = "background-color: gray; color: black;"

        self.work_hours_edit.setStyleSheet(editable_style)
        self.break1_edit.setStyleSheet(editable_style)
        self.break2_edit.setStyleSheet(editable_style)
        self.break3_edit.setStyleSheet(editable_style)

        if selected_shift == "Ochtend":
            self.work_hours_edit.setText("06:00-15:00")
        elif selected_shift == "Middag":
            self.work_hours_edit.setText("15:00-00:00")
        elif selected_shift == "Day8to17":
            self.work_hours_edit.setText("08:00-17:00")
        else:
            self.work_hours_edit.clear()

        breaks = {
            "Ochtend": OCHTEND_BREAKS,
            "Middag": MIDDAG_BREAKS,
            "Day8to17": DAY8TO17_BREAKS,
        }.get(selected_shift, [])

        self.break1_edit.setText(self.format_break(breaks, 0))
        self.break2_edit.setText(self.format_break(breaks, 1))
        self.break3_edit.setText(self.format_break(breaks, 2))

    @staticmethod
    def format_break(breaks, index):
        if index < len(breaks):
            b_start, b_end = breaks[index]
            return f"{b_start // 60:02d}:{b_start % 60:02d}-{b_end // 60:02d}:{b_end % 60:02d}"
        return ""

    def on_confirm(self):
        ln = self.lastname_edit.text().strip()
        fn = self.firstname_edit.text().strip()
        dept = self.dept_combo.currentText().strip()
        sh = self.shift_combo.currentText().strip()

        if not ln or not fn:
            QMessageBox.critical(self, "Error", "Enter last and first name!")
            return

        wh = self.work_hours_edit.text().strip()
        b1 = self.break1_edit.text().strip()
        b2 = self.break2_edit.text().strip()
        b3 = self.break3_edit.text().strip()

        custom_breaks = []
        if b1 and "-" in b1:
            try:
                b1_start, b1_end = b1.split("-")
                custom_breaks.append((to_minutes(b1_start), to_minutes(b1_end)))
            except ValueError:
                QMessageBox.critical(self, "Error", f"Invalid format for Break 1: {b1}")
                return
        if b2 and "-" in b2:
            try:
                b2_start, b2_end = b2.split("-")
                custom_breaks.append((to_minutes(b2_start), to_minutes(b2_end)))
            except ValueError:
                QMessageBox.critical(self, "Error", f"Invalid format for Break 2: {b2}")
                return
        if b3 and "-" in b3:
            try:
                b3_start, b3_end = b3.split("-")
                custom_breaks.append((to_minutes(b3_start), to_minutes(b3_end)))
            except ValueError:
                QMessageBox.critical(self, "Error", f"Invalid format for Break 3: {b3}")
                return

        computed_hours = compute_hours_with_breaks(wh, sh, custom_breaks)
        if computed_hours == 0.0:
            QMessageBox.critical(self, "Error", "Invalid work hours or breaks.")
            return

        formatted_last, formatted_first = move_lastname_prefix_to_firstname(ln, fn)
        formatted_last = format_name(formatted_last)
        formatted_first = format_name(formatted_first)

        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO employees (lastname, firstname, current_department, work_hours, shift, computed_hours, marked)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (formatted_last, formatted_first, dept, wh, sh, computed_hours, 0)
            )
            employee_id = cursor.lastrowid

            if sh == "Custom":
                for (start_break, end_break) in custom_breaks:
                    cursor.execute(
                        """
                        INSERT INTO custom_breaks (employee_id, start, end)
                        VALUES (?, ?, ?)
                        """,
                        (employee_id, start_break, end_break)
                    )

            conn.commit()
            conn.close()

            new_employee = Employee(
                employee_id, formatted_last, formatted_first, dept, wh, sh, computed_hours, custom_breaks
            )
            employees.append(new_employee)
            employee_index_map[employee_id] = len(employees) - 1

            self.parent().display_all_employees()
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add employee: {e}")


class AddDepartmentDialog(QDialog):
    def __init__(self, parent, employees):
        super().__init__(parent)
        self.employees = employees
        self.setWindowTitle("Add Department")
        self.setGeometry(400, 400, 240, 140)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        self.label_dept = QLabel("Select department:")
        layout.addWidget(self.label_dept)
        self.dept_combo = QComboBox()
        self.dept_combo.addItems(TEAM_LIST)
        layout.addWidget(self.dept_combo)

        self.label_time = QLabel("Time (HH:MM):")
        layout.addWidget(self.label_time)
        self.time_edit = QLineEdit()
        now_str = datetime.now().strftime("%H:%M")
        self.time_edit.setText(now_str)
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

        self.setLayout(layout)

    def on_confirm(self):
        dept_chosen = self.dept_combo.currentText().strip()
        time_chosen = self.time_edit.text().strip()

        if not Validator.validate_time_format(time_chosen):
            QMessageBox.critical(self, "Error", "Invalid time format. Please use HH:MM.")
            return

        errors = []
        for emp in self.employees:
            try:
                emp.add_department(dept_chosen, time_chosen)
            except ValueError as e:
                errors.append(f"{emp.firstname} {emp.lastname}: {e}")
            except sqlite3.Error as e:
                errors.append(f"Database error for {emp.firstname} {emp.lastname}: {e}")

        if errors:
            QMessageBox.warning(self, "Warning", "\n".join(errors))

        self.parent().display_all_employees()
        self.parent().main_window.refresh_monitoring()
        self.accept()

class EditDepartmentDialog(QDialog):
    def __init__(self, parent, employees):
        super().__init__(parent)
        self.employees = employees
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

        self.setLayout(layout)

    def on_confirm(self):
        new_dept = self.new_dept_combo.currentText().strip()
        for emp in self.employees:
            emp.edit_current_department(new_dept)
        self.accept()

def save_sorting_state(column_name, order):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sorting_settings")
    cursor.execute("INSERT INTO sorting_settings (column_name, sort_order) VALUES (?, ?)",
                   (column_name, "ASC" if order else "DESC"))
    conn.commit()
    conn.close()

def load_sorting_state():
    global current_sort_column, current_sort_order
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT column_name, sort_order FROM sorting_settings LIMIT 1")
    result = cursor.fetchone()
    if result:
        current_sort_column = result[0]
        current_sort_order = (result[1] == "ASC")
    else:
        current_sort_column = "lastname"
        current_sort_order = True
    conn.close()

###############################################################################
#                     Uruchomienie PySide6
###############################################################################
def main():
    init_db()
    reload_data()
    load_sorting_state()
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.display_all_employees()
    main_window.showMaximized()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
