"""Model tabeli pracowników."""
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

from .config import ROW_COLOR_HOME, ROW_COLOR_LATE, ROW_COLOR_SICK, col_names, columns

STATUS_COLORS = {
    "sick": QColor(ROW_COLOR_SICK),
    "home": QColor(ROW_COLOR_HOME),
    "late": QColor(ROW_COLOR_LATE),
}
STATUS_TEXT_COLOR = QColor("#000000")


class EmployeeTableModel(QAbstractTableModel):
    def __init__(self, employees=None, parent=None):
        super().__init__(parent)
        self.all_employees = employees or []   # wszyscy z bazy
        self.employees = list(self.all_employees)  # widoczni (po filtrze)
        self.filter_text = ""
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

        if role in (Qt.DisplayRole, Qt.EditRole):
            values = emp.to_ui_values()
            return values[col] if col < len(values) else None

        if role == Qt.TextAlignmentRole:
            return Qt.AlignCenter

        if role == Qt.BackgroundRole:
            return STATUS_COLORS.get(emp.status)

        if role == Qt.ForegroundRole:
            return STATUS_TEXT_COLOR if emp.status else None

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
        self.all_employees = employees
        self._apply_filter()
        self.apply_current_sort(reset_model=False)
        self.rebuild_index()
        self.endResetModel()

    def _apply_filter(self):
        words = self.filter_text.casefold().split()
        if not words:
            self.employees = list(self.all_employees)
            return

        def matches(emp):
            haystack = " ".join([*(str(v) for v in emp.to_ui_values()[1:]), emp.login, emp.position]).casefold()
            return all(word in haystack for word in words)

        self.employees = [emp for emp in self.all_employees if matches(emp)]

    def set_filter(self, text):
        """Pokazuje tylko wiersze zawierające wszystkie wpisane słowa (nazwisko, dział, godziny, info)."""
        self.beginResetModel()
        self.filter_text = text or ""
        self._apply_filter()
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
