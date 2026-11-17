"""Główne okno aplikacji."""
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
    QStackedWidget,
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
from PySide6.QtGui import QKeySequence, QPageLayout, QShortcut, QTextDocument
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter

from . import db
from .config import ROW_COLOR_HOME, ROW_COLOR_LATE, ROW_COLOR_SICK, SYNC_INTERVAL_MS, col_names, columns
from .excel_io import export_rows_to_excel
from .dialogs import (
    AddDepartmentDialog,
    AddEmployeeDialog,
    EditDepartmentDialog,
    HistoryDialog,
    MarkAsLateDialog,
)
from .monitoring import MonitoringView
from .table_model import EmployeeTableModel
from .widgets import DatabaseLoadWorker, DatabaseTaskWorker, InfoItemDelegate, ToggleButton


class MainWindow(QMainWindow):
    def __init__(self, with_monitoring=False):
        super().__init__()

        self.with_monitoring = with_monitoring
        self.monitoring_view = None

        self.is_editing_info = False
        self.mark_mode = False
        self._active_threads = []

        self.setWindowTitle("Planning Manager + Monitoring" if with_monitoring else "Planning Manager")
        self.setGeometry(100, 100, 1200, 600)

        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QVBoxLayout(self.main_widget)

        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(5, 5, 5, 5)
        top_layout.setSpacing(3)
        self.main_layout.addLayout(top_layout)

        if with_monitoring:
            # Przełącznik widoków: Planning (tabela) <-> Monitoring (tablica)
            self.view_toggle = ToggleButton(width=50, height=25)
            self.view_toggle.stateChanged.connect(self.on_view_toggled)
            top_layout.addWidget(QLabel("Planning"))
            top_layout.addWidget(self.view_toggle)
            top_layout.addWidget(QLabel("Monitoring"))
            top_layout.addSpacing(15)

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

        self.undo_button = QPushButton("Undo")
        self.undo_button.setFixedWidth(80)
        self.undo_button.setMinimumHeight(40)
        self.undo_button.setToolTip("Undo the last change (Ctrl+Z)")
        self.undo_button.clicked.connect(self.undo_last)
        top_layout.addWidget(self.undo_button)

        self.history_button = QPushButton("History")
        self.history_button.setFixedWidth(80)
        self.history_button.setMinimumHeight(40)
        self.history_button.clicked.connect(self.show_history)
        top_layout.addWidget(self.history_button)

        self.export_button = QPushButton("Export Excel")
        self.export_button.setFixedWidth(110)
        self.export_button.setMinimumHeight(40)
        self.export_button.clicked.connect(self.export_excel)
        top_layout.addWidget(self.export_button)

        self.print_button = QPushButton("Print")
        self.print_button.setFixedWidth(80)
        self.print_button.setMinimumHeight(40)
        self.print_button.clicked.connect(self.print_table)
        top_layout.addWidget(self.print_button)

        top_layout.addSpacing(10)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search: name, department, hours, info...  (Ctrl+F)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumHeight(30)
        self.search_edit.setMinimumWidth(200)
        self.search_edit.setMaximumWidth(360)
        self.search_edit.textChanged.connect(self.on_search_changed)
        top_layout.addWidget(self.search_edit)

        self.count_label = QLabel("")
        top_layout.addWidget(self.count_label)

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

        if with_monitoring:
            self.monitoring_view = MonitoringView()
            self.monitoring_view.move_requested.connect(self.move_employees)

            self.stack = QStackedWidget()
            self.stack.addWidget(self.table)
            self.stack.addWidget(self.monitoring_view)
            self.main_layout.addWidget(self.stack)
        else:
            self.main_layout.addWidget(self.table)

        legend = QHBoxLayout()
        legend.setContentsMargins(5, 0, 5, 3)
        for text, color in (("Ziek", ROW_COLOR_SICK), ("Naar Huis", ROW_COLOR_HOME), ("Late", ROW_COLOR_LATE)):
            chip = QLabel(f"  {text}  ")
            chip.setStyleSheet(f"background-color: {color}; color: #000; border-radius: 3px; padding: 2px;")
            legend.addWidget(chip)
        legend.addStretch()
        self.main_layout.addLayout(legend)

        QShortcut(QKeySequence.Undo, self, activated=self.undo_last)
        QShortcut(QKeySequence.Find, self, activated=self.focus_search)

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
        if self.monitoring_view is not None and self.monitoring_view.dragging:
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
        self.undo_button.setEnabled(enabled)
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
            self.update_count_label()
            if self.monitoring_view is not None:
                self.monitoring_view.set_employees(self.model.all_employees)
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

        self.run_db_task(lambda: db.toggle_employee_marked_in_db(emp_id, marked))

    # -------------------------------------------------------------- monitoring
    def on_view_toggled(self, state):
        self.stack.setCurrentIndex(1 if self.view_toggle.isChecked() else 0)

    def move_employees(self, employee_ids, department, position):
        """Kostka upuszczona w widoku Monitoring: zapis od razu, z aktualną godziną."""
        if not employee_ids:
            return

        if department.lower() == "naar huis":
            reply = QMessageBox.question(
                self, "Confirm",
                f"Send {len(employee_ids)} employee(s) home now?\nThis shortens their work hours.",
            )
            if reply != QMessageBox.Yes:
                return

        def done(errors):
            if errors:
                QMessageBox.warning(self, "Warning", "\n".join(errors))

        self.run_db_task(
            lambda: db.move_employees_in_db(employee_ids, department, position),
            on_finished=done,
            refresh_after=True,
        )

    # ------------------------------------------------------------------ search
    def focus_search(self):
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def on_search_changed(self, text):
        selected_ids = self.selected_employee_ids()
        self.model.set_filter(text)
        self.restore_selection(selected_ids)
        self.update_count_label()

    def update_count_label(self):
        shown = len(self.model.employees)
        total = len(self.model.all_employees)
        self.count_label.setText(f"{shown} / {total}" if shown != total else f"{total}")

    # -------------------------------------------------------------- undo / log
    def undo_last(self):
        if self.is_editing_info or self._active_threads:
            return

        def done(description):
            if description is None:
                QMessageBox.information(self, "Undo", "Nothing to undo.")
            else:
                self.statusBar().showMessage(f"Undone: {description}", 8000)

        self.run_db_task(db.undo_last, on_finished=done, refresh_after=True)

    def show_history(self):
        try:
            entries = db.load_change_log()
        except Exception as exc:
            QMessageBox.critical(self, "Database Error", str(exc))
            return
        HistoryDialog(self, entries).exec()

    # ---------------------------------------------------------- export / print
    def visible_rows(self):
        """Wiersze tak, jak je widać (filtr + sortowanie), bez kolumny Marked."""
        return [emp.to_ui_values()[1:] for emp in self.model.employees]

    def export_excel(self):
        rows = self.visible_rows()
        if not rows:
            QMessageBox.information(self, "Info", "No data to export.")
            return

        default_name = f"planning_{datetime.now().strftime('%Y-%m-%d_%H%M')}.xlsx"
        filepath, _ = QFileDialog.getSaveFileName(self, "Export to Excel", default_name, "Excel files (*.xlsx)")
        if not filepath:
            return
        if not filepath.lower().endswith(".xlsx"):
            filepath += ".xlsx"

        self.run_db_task(
            lambda: export_rows_to_excel(rows, filepath),
            on_finished=lambda _: self.statusBar().showMessage(f"Exported {len(rows)} rows to {filepath}", 8000),
        )

    def print_table(self):
        rows = self.visible_rows()
        if not rows:
            QMessageBox.information(self, "Info", "No data to print.")
            return

        def esc(value):
            return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        head = "".join(f"<th>{esc(name)}</th>" for name in col_names[1:])
        body = "".join(
            "<tr>" + "".join(f"<td>{esc(value)}</td>" for value in row) + "</tr>"
            for row in rows
        )
        html = (
            "<html><head><style>"
            "table { border-collapse: collapse; width: 100%; font-size: 7pt; }"
            "th, td { border: 1px solid #555; padding: 2px 3px; text-align: center; }"
            "th { background-color: #ddd; }"
            "</style></head><body>"
            f"<h3>Planning - {datetime.now().strftime('%Y-%m-%d %H:%M')} ({len(rows)} employees)</h3>"
            f"<table cellspacing='0'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
            "</body></html>"
        )

        document = QTextDocument()
        document.setHtml(html)

        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageOrientation(QPageLayout.Landscape)

        preview = QPrintPreviewDialog(printer, self)
        preview.setWindowTitle("Print preview")
        preview.resize(1100, 750)
        preview.paintRequested.connect(document.print_)
        preview.exec()

    def sort_table(self, index):
        self.model.toggle_sort(index)

    def add_employee(self):
        dlg = AddEmployeeDialog(self)

        if dlg.exec() and dlg.result_data:
            data = dlg.result_data
            self.run_db_task(
                lambda: db.insert_employee_to_db(data),
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
                lambda: db.delete_employees_from_db(employee_ids),
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
                lambda: db.add_departments_to_db(
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
            lambda: db.remove_last_departments_from_db(employee_ids),
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
                lambda: db.edit_departments_in_db(
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

        items = []

        for emp in selected:
            dlg = MarkAsLateDialog(self, emp)

            if dlg.exec() and dlg.result_data:
                data = dlg.result_data
                items.append((data["employee_id"], data["actual_start"]))

        if not items:
            return

        def done(errors):
            if errors:
                QMessageBox.warning(self, "Warning", "\n".join(errors))

        # jedno zadanie w tle dla wszystkich osób, błędy wracają przez on_finished
        self.run_db_task(
            lambda: db.mark_employees_late_in_db(items),
            on_finished=done,
            refresh_after=True,
        )

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
            lambda: db.update_employee_info_in_db(emp_id, info)
        )

    def load_excel(self):
        dlg = QFileDialog(self, "Open Excel files", "", "Excel files (*.xlsx)")
        dlg.setFileMode(QFileDialog.ExistingFiles)

        if not dlg.exec():
            return

        filepaths = dlg.selectedFiles()

        def done(result):
            count, skipped = result
            msg = f"Data imported successfully. Imported rows: {count}"
            if skipped:
                msg += f"\nSkipped duplicates (already in the database): {skipped}"
            QMessageBox.information(self, "Success", msg)

        self.run_db_task(
            lambda: db.import_excel_to_db(filepaths),
            on_finished=done,
            refresh_after=True,
        )

    def clear_data(self):
        reply = QMessageBox.question(
            self, "Confirm",
            "Clear all data?\n\nA copy of the current data will be saved in the 'archive' folder first.",
        )

        if reply == QMessageBox.Yes:
            self.run_db_task(
                lambda: db.clear_all_data_in_db(),
                on_finished=lambda path: QMessageBox.information(
                    self, "Success",
                    "All data cleared." + (f"\nArchive saved as:\n{path}" if path else ""),
                ),
                refresh_after=True,
            )
