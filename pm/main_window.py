"""Główne okno aplikacji."""
from datetime import datetime

from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import (
    QSettings,
    QSize,
    QTime,
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
from PySide6.QtGui import QKeySequence, QPageLayout, QPixmap, QShortcut, QTextDocument
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter

import os

from . import config, db, hours_export, theme
from .config import ROW_COLOR_HOME, ROW_COLOR_LATE, ROW_COLOR_SICK, SYNC_INTERVAL_MS, col_names, columns
from .excel_io import export_rows_to_excel
from .dialogs import (
    AddDepartmentDialog,
    AddEmployeeDialog,
    EditDepartmentDialog,
    HistoryDialog,
    MarkAsLateDialog,
    PlanHoursDialog,
)
from .consolidation_view import ConsolidationView
from .hours_dialog import HoursDialog, remember_columns, remembered_columns
from .monitoring import MonitoringView
from .monitoring_dialogs import GroupHomeDialog, LeaveDialog, TimeDialog, ZonePickerDialog
from .table_model import EmployeeTableModel
from .widgets import DatabaseLoadWorker, DatabaseTaskWorker, InfoItemDelegate, MainThreadRelay, ToggleButton

# Widoki w menu po lewej: (nazwa, opis). Indeks = pozycja w QStackedWidget.
VIEWS = [
    ("Planning", "Hours per department for the whole shift"),
    ("Monitoring", "Who is where right now – drag employees between departments"),
    ("Consolidatie", "Consolidation list (RITs) – reacher assignment changes their task on Monitoring"),
]
VIEW_ICONS = ["planning", "monitoring", "consolidation"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.is_editing_info = False
        self.mark_mode = False
        self._active_threads = []

        self.setWindowTitle("Planning Manager")
        self.setGeometry(100, 100, 1200, 600)

        self._icon_targets = []   # (widget / akcja, nazwa ikony) – odświeżane przy zmianie motywu

        # Układ okna: menu widoków po lewej; po prawej pasek z tytułem i akcjami + bieżący widok
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        outer_layout = QHBoxLayout(self.main_widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        outer_layout.addWidget(self._build_sidebar())

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        outer_layout.addWidget(content, 1)
        content_layout.addWidget(self._build_topbar())

        body = QWidget()
        self.main_layout = QVBoxLayout(body)
        self.main_layout.setContentsMargins(10, 8, 10, 6)
        content_layout.addWidget(body, 1)

        self.model = EmployeeTableModel([])
        self.model.dataChanged.connect(self.on_model_data_changed)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSortingEnabled(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(28)

        widths = [60, 140, 100, 80, 100, 140, 80, 140, 80, 140, 80, 140, 80, 140, 80, 285]
        for col, width in enumerate(widths):
            self.table.setColumnWidth(col, width)

        info_col = len(columns) - 1
        self.table.setItemDelegateForColumn(info_col, InfoItemDelegate(self.table))

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.sectionClicked.connect(self.sort_table)

        self.monitoring_view = MonitoringView()
        self.monitoring_view.move_requested.connect(self.move_employees)
        self.monitoring_view.toggle_position_requested.connect(self.toggle_position)
        self.monitoring_view.leave_requested.connect(self.leave_work)
        self.monitoring_view.action_requested.connect(self.monitoring_action)
        self.monitoring_view.group_home_requested.connect(self.group_home)

        self.consolidation_view = ConsolidationView()
        self.consolidation_view.update_requested.connect(self.update_consolidation)
        self.consolidation_view.add_requested.connect(self.add_consolidation)
        self.consolidation_view.delete_requested.connect(self.delete_consolidation)
        self.consolidation_view.import_requested.connect(self.import_consolidation)

        # Kolejność = kolejność przycisków w menu po lewej (VIEWS)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.monitoring_view)
        self.stack.addWidget(self.consolidation_view)
        self.main_layout.addWidget(self.stack)

        # legenda kolorów wierszy – tylko w Planning
        self.legend_widget = QWidget()
        legend = QHBoxLayout(self.legend_widget)
        legend.setContentsMargins(0, 4, 0, 0)
        for text, color in (("Ziek", ROW_COLOR_SICK), ("Naar Huis", ROW_COLOR_HOME), ("Late", ROW_COLOR_LATE)):
            chip = QLabel(f"  {text}  ")
            chip.setStyleSheet(f"background-color: {color}; color: #000; border-radius: 4px; padding: 3px;")
            legend.addWidget(chip)
        legend.addStretch()
        self.main_layout.addWidget(self.legend_widget)

        QShortcut(QKeySequence.Undo, self, activated=self.undo_last)
        for index in range(len(VIEWS)):  # Ctrl+1 / Ctrl+2 / Ctrl+3 = przełączenie widoku
            QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self, activated=lambda i=index: self.show_view(i))

        self.context_menu = QMenu(self)
        self.context_menu.addAction("Add Department", self.add_department)
        self.context_menu.addAction("Edit Department", self.edit_department)
        self.context_menu.addAction("Remove Department", self.remove_department)
        self.context_menu.addAction("Late", self.mark_as_late)

        # pasek stanu: gdzie jest baza i kto ostatnio coś zmienił (praca kilku komputerów naraz)
        self.last_change_label = QLabel("")
        self.last_change_label.setObjectName("muted")
        self.statusBar().addPermanentWidget(self.last_change_label)
        self._last_counter = None

        self.refresh_data()

        # Ciężkie biblioteki do Excela doczytujemy w tle, gdy okno już działa.
        QTimer.singleShot(1500, self._warm_up_excel)

        # Co kilka sekund tanie sprawdzenie licznika zmian w bazie; odświeżamy tylko, gdy ktoś coś zmienił.
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.auto_refresh)
        self.sync_timer.start(config.REFRESH_CHECK_MS)

        # Kopia bazy co godzinę (jedna na godzinę, nawet przy kilku komputerach)
        self.backup_timer = QTimer(self)
        self.backup_timer.timeout.connect(lambda: self.run_db_task(lambda: db.backup_db("hourly")))
        self.backup_timer.start(15 * 60 * 1000)

    def _warm_up_excel(self):
        import threading

        from .excel_io import warm_up

        threading.Thread(target=warm_up, name="excel-warm-up", daemon=True).start()

    def auto_refresh(self):
        """Odświeżenie tylko wtedy, gdy w bazie coś się zmieniło (np. na innym komputerze)."""
        if self.is_editing_info or self._active_threads:
            return
        if self.monitoring_view.dragging or self.consolidation_view.busy:
            return
        try:
            counter, last = db.change_state()
        except Exception as exc:   # dysk sieciowy chwilowo niedostępny
            self.last_change_label.setText(f"⚠ Database not reachable: {exc}")
            return
        self._show_last_change(last)
        if counter != self._last_counter:
            self.refresh_data()

    def _show_last_change(self, last):
        where = config.DB_FOLDER
        text = f"Database: {where}"
        if last:
            ts, user, action = last
            text += f"   ·   last change {ts[11:16]} by {user} ({action})"
        self.last_change_label.setText(text)

    def sync_now(self):
        self.refresh_data()

    def _guarded(self, employee_ids, task):
        """Zadanie, które najpierw sprawdza, czy nikt inny nie zmienił tych osób od ostatniego wczytania."""
        wanted = set(employee_ids)
        expected = {e.employee_id: e.fingerprint for e in self.model.all_employees
                    if e.employee_id in wanted and getattr(e, "fingerprint", None)}

        def run():
            db.assert_unchanged(expected)
            return task()
        return run

    def _db_error(self, message):
        """Czytelne komunikaty dla pracy kilku komputerów na wspólnej bazie."""
        if message.startswith("Someone else") or message.startswith("Cannot undo"):
            QMessageBox.warning(self, "Changed by someone else", message)
            self.refresh_data()
        elif "locked" in message.lower() or "busy" in message.lower():
            QMessageBox.warning(self, "Database busy",
                                "Another computer is saving to the shared database right now.\n"
                                "Nothing was changed – please try again in a moment.")
        elif "unable to open" in message.lower() or "disk i/o" in message.lower():
            QMessageBox.critical(self, "Database not reachable",
                                 f"The database could not be opened:\n{config.DB_PATH}\n\n"
                                 "Check the network drive connection.\n\n" + message)
        else:
            QMessageBox.critical(self, "Database Error", message)

    def set_controls_enabled(self, enabled):
        for control in (self.load_action, self.clear_action, self.add_emp_action, self.remove_emp_action,
                        self.undo_button, self.toggle_mark_button):
            control.setEnabled(enabled)

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
            relay.deleteLater()
            thread.deleteLater()

        def finished_handler(result):
            thread.quit()

            if refresh_after:
                self.refresh_data()
            else:
                self.set_controls_enabled(True)

            if on_finished:
                on_finished(result)

        def error_handler(message):
            thread.quit()
            self.set_controls_enabled(True)
            self._db_error(message)

        relay = MainThreadRelay(finished_handler, error_handler, self)
        worker.finished.connect(relay.finished, Qt.QueuedConnection)
        worker.error.connect(relay.error, Qt.QueuedConnection)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(cleanup)

        thread.start()

    def refresh_data(self):
        if self.is_editing_info:
            return

        selected_ids = [emp.employee_id for emp in self.selected_employees()]
        scroll_value = self.table.verticalScrollBar().value()
        try:
            self._last_counter, last = db.change_state()
            self._show_last_change(last)
        except Exception:
            pass

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
            relay.deleteLater()
            thread.deleteLater()

        def on_finished(data):
            self.model.refresh(data)
            self.update_count_label()
            if self.monitoring_view is not None:
                self.monitoring_view.set_employees(self.model.all_employees)
            try:
                self.consolidation_view.set_data(
                    db.load_consolidation(), self.model.all_employees, db.login_names()
                )
            except Exception as exc:  # lista konsolidacji nie może zablokować reszty
                print(f"Consolidation refresh failed: {exc}")
            self.restore_selection(selected_ids)
            self.table.verticalScrollBar().setValue(scroll_value)
            self._refresh_shifts()
            self.set_controls_enabled(True)
            thread.quit()

        def on_error(message):
            thread.quit()
            self.set_controls_enabled(True)
            self._db_error(message)

        relay = MainThreadRelay(on_finished, on_error, self)
        worker.finished.connect(relay.finished, Qt.QueuedConnection)
        worker.error.connect(relay.error, Qt.QueuedConnection)
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
        self.toggle_mark_button.setText("Mark mode: ON" if self.mark_mode else "Mark mode")

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

    # ------------------------------------------------------------------- views
    def _themed(self, target, icon_name, **kwargs):
        """Ustawia ikonę w kolorze motywu i zapamiętuje ją do odświeżenia przy zmianie motywu."""
        target.setIcon(theme.icon(icon_name, **kwargs))
        self._icon_targets.append((target, icon_name, kwargs))
        return target

    def _build_sidebar(self):
        """Menu po lewej: logo + jeden przycisk z ikoną na widok (kolejne widoki = kolejna pozycja w VIEWS)."""
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(178)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(4)

        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(theme.LOGO).scaled(34, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        brand.addWidget(logo)
        name = QLabel("Planning\nManager")
        name.setObjectName("appName")
        brand.addWidget(name, 1)
        layout.addLayout(brand)
        layout.addSpacing(18)

        self.view_buttons = []
        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, (title, tooltip) in enumerate(VIEWS):
            button = QPushButton(f"  {title}")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setIconSize(QSize(22, 22))
            button.setToolTip(f"{tooltip}  (Ctrl+{index + 1})")
            button.clicked.connect(lambda _=False, i=index: self.show_view(i))
            self._themed(button, VIEW_ICONS[index], color_key="sidebar_text")
            group.addButton(button, index)
            layout.addWidget(button)
            self.view_buttons.append(button)
        self.view_buttons[0].setChecked(True)
        layout.addStretch()

        version = QLabel("offline · local database")
        version.setObjectName("appVersion")
        layout.addWidget(version)
        return sidebar

    def _tool(self, icon_name, text, slot=None, tooltip=""):
        button = QToolButton()
        button.setObjectName("toolbarButton")
        button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(20, 20))
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(tooltip or text)
        if slot is not None:
            button.clicked.connect(slot)
        return self._themed(button, icon_name)

    def _menu_tool(self, icon_name, text, entries, tooltip=""):
        """Przycisk z menu rozwijanym: entries = [(ikona, tekst, slot) albo None = separator]."""
        button = self._tool(icon_name, f"{text}  ▾", tooltip=tooltip)
        button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(button)
        actions = []
        for entry in entries:
            if entry is None:
                menu.addSeparator()
                continue
            entry_icon, entry_text, slot = entry
            action = menu.addAction(entry_text, slot)
            self._themed(action, entry_icon)
            actions.append(action)
        button.setMenu(menu)
        return button, actions

    def _build_topbar(self):
        """Pasek u góry: ikona i nazwa widoku, liczba osób, akcje z ikonami (rzadkie – w menu)."""
        bar = QFrame()
        bar.setObjectName("topbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 8, 12, 8)
        layout.setSpacing(4)

        self.page_icon = QLabel()
        layout.addWidget(self.page_icon)
        self.page_title = QLabel(VIEWS[0][0])
        self.page_title.setObjectName("pageTitle")
        layout.addWidget(self.page_title)
        layout.addSpacing(10)
        self.count_label = QLabel("")
        self.count_label.setObjectName("muted")
        self.count_label.setToolTip("Employees on the list (shown / all)")
        layout.addWidget(self.count_label)
        layout.addSpacing(14)

        # Która zmiana (data + Ochtend / Middag) – poprzednie dni zostają w bazie
        self.shift_combo = QComboBox()
        self.shift_combo.setMinimumWidth(260)
        self.shift_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.shift_combo.setToolTip("Shift shown in this window. Importing a plan creates / fills its shift;\n"
                                    "earlier days stay in the database.")
        self.shift_combo.activated.connect(self._shift_chosen)
        layout.addWidget(self.shift_combo)
        layout.addStretch()

        self.toggle_mark_button = self._tool(
            "mark_mode", "Mark mode",
            tooltip="Mark mode: click a row to tick it as written into the hours Excel.\n"
                    "A tick disappears when the person gets a new department.")
        self.toggle_mark_button.setCheckable(True)
        self.toggle_mark_button.toggled.connect(self.toggle_mark_mode)
        layout.addWidget(self.toggle_mark_button)

        self.undo_button = self._tool("undo", "Undo", self.undo_last, "Undo the last change (Ctrl+Z)")
        layout.addWidget(self.undo_button)
        self.history_button = self._tool("history", "History", self.show_history, "Who changed what and when")
        layout.addWidget(self.history_button)

        self.import_button, (self.load_action, self.logins_action, self.import_cons_action) = self._menu_tool(
            "import", "Import", [
                ("planning", "Shift plan (Ploeglijst)…", self.load_excel),
                ("logins", "Logins (Inlognamen)…", self.import_logins),
                ("consolidation", "Consolidation list…", self.import_consolidation),
            ], "Load data from Excel files")
        layout.addWidget(self.import_button)

        self.employees_button, (self.add_emp_action, self.remove_emp_action) = self._menu_tool(
            "add_employee", "Employees", [
                ("add_employee", "Add employee…", self.add_employee),
                ("remove_employee", "Remove selected employee(s)", self.remove_employee),
            ])
        layout.addWidget(self.employees_button)

        self.export_button, _ = self._menu_tool(
            "export", "Export", [
                ("export", "Export to Excel…", self.export_excel),
                ("export", "Hours to week file (Uren_Lijst)…", self.export_hours),
                ("print", "Print…", self.print_table),
            ])
        layout.addWidget(self.export_button)

        self.more_button, (self.theme_action, self.db_action, self.clear_action) = self._menu_tool(
            "settings", "", [
                ("settings", "Switch to light theme", self.toggle_theme),
                ("database", "Database location…", self.choose_database_folder),
                None,
                ("clear", "Delete this shift…", self.clear_data),
            ], "More")
        self.more_button.setText("")
        self.more_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        layout.addWidget(self.more_button)
        self._update_theme_action()
        self._update_page_header(0)
        return bar

    def _update_page_header(self, index):
        self.page_title.setText(VIEWS[index][0])
        self.page_icon.setPixmap(theme.tinted_pixmap(VIEW_ICONS[index], theme.color("accent"), 28))
        planning = index == 0
        self.toggle_mark_button.setVisible(planning)
        if hasattr(self, "legend_widget"):
            self.legend_widget.setVisible(planning)

    def _refresh_shifts(self):
        """Lista zmian w polu wyboru (bez wywoływania zmiany przez użytkownika)."""
        try:
            shifts = db.list_shifts()
            current = db.resolved_shift()
        except Exception:
            return
        current_id = current[0] if current else None
        self.shift_combo.blockSignals(True)
        self.shift_combo.clear()
        for shift_id, shift_date, name, count in shifts:
            try:
                label_date = datetime.strptime(shift_date, "%Y-%m-%d").strftime("%a %d-%m-%Y")
            except ValueError:
                label_date = shift_date
            self.shift_combo.addItem(f"{label_date}  ·  {name}  ({count})", shift_id)
        if not shifts:
            self.shift_combo.addItem("No shift yet – import a plan", None)
        index = self.shift_combo.findData(current_id)
        self.shift_combo.setCurrentIndex(max(0, index))
        self.shift_combo.blockSignals(False)

    def _shift_chosen(self, index):
        shift_id = self.shift_combo.itemData(index)
        if shift_id is None:
            return
        db.current_shift_id = shift_id
        self.refresh_data()

    def choose_database_folder(self):
        """Folder ze wspólną bazą (np. dysk sieciowy) – zapisany w settings.ini obok programu."""
        reply = QMessageBox.question(
            self, "Database location",
            f"Current database:\n{config.DB_PATH}\n\nChoose another folder (e.g. on the network drive)?\n"
            "If the folder has no database yet, the current one can be copied there.",
        )
        if reply != QMessageBox.Yes:
            return
        folder = QFileDialog.getExistingDirectory(self, "Folder for the shared database", config.DB_FOLDER)
        if not folder or os.path.normcase(folder) == os.path.normcase(config.DB_FOLDER):
            return
        target = os.path.join(folder, config.DB_FILENAME)
        if not os.path.exists(target):
            copy = QMessageBox.question(
                self, "Database location",
                f"There is no database in:\n{folder}\n\nCopy the current database there?\n"
                "(No = start there with an empty database)",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if copy == QMessageBox.Cancel:
                return
            if copy == QMessageBox.Yes:
                try:
                    import shutil
                    shutil.copy2(config.DB_PATH, target)
                except OSError as exc:
                    QMessageBox.critical(self, "Database location", f"Copy failed:\n{exc}")
                    return
        try:
            config.write_database_folder(folder)
        except OSError as exc:
            QMessageBox.critical(self, "Database location", f"Could not save settings.ini:\n{exc}")
            return
        QMessageBox.information(self, "Database location",
                                f"Saved. Restart the program to use:\n{target}")

    def _update_theme_action(self):
        dark = theme.current_name == "dark"
        self.theme_action.setText("Switch to light theme" if dark else "Switch to dark theme")

    def toggle_theme(self):
        self.apply_theme("light" if theme.current_name == "dark" else "dark")

    def apply_theme(self, name):
        theme.apply(QApplication.instance(), name)
        for target, icon_name, kwargs in self._icon_targets:
            target.setIcon(theme.icon(icon_name, **kwargs))
        self._update_theme_action()
        self._update_page_header(self.stack.currentIndex())
        self.monitoring_view.refresh_theme()
        self.consolidation_view.refresh_theme()

    def show_view(self, index):
        self.stack.setCurrentIndex(index)
        self.view_buttons[index].setChecked(True)
        self._update_page_header(index)

    # ----------------------------------------------------------- consolidation
    def _zones_changed(self, changes):
        """Po zmianie na liście konsolidacji: krótka informacja w pasku stanu, kto zmienił strefę."""
        if changes:
            self.statusBar().showMessage("Monitoring: " + "; ".join(changes), 8000)

    def update_consolidation(self, cons_id, fields):
        self.run_db_task(
            lambda: db.update_consolidation_in_db(cons_id, **fields),
            on_finished=self._zones_changed,
            refresh_after=True,
        )

    def add_consolidation(self, datum, values):
        self.run_db_task(lambda: db.add_consolidation_in_db(datum, **values), refresh_after=True)

    def delete_consolidation(self, cons_ids):
        self.run_db_task(
            lambda: db.delete_consolidation_in_db(cons_ids), on_finished=self._zones_changed, refresh_after=True
        )

    def import_consolidation(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Open consolidation list", "", "Excel files (*.xlsx *.xlsm)"
        )
        if not filepath:
            return

        def done(result):
            added, updated, changes = result
            QMessageBox.information(
                self, "Success",
                f"New RITs: {added}\nUpdated RITs: {updated}"
                + (f"\n\nZones changed on Monitoring:\n" + "\n".join(changes) if changes else ""),
            )

        self.run_db_task(lambda: db.import_consolidation_from_excel(filepath), on_finished=done, refresh_after=True)

    def toggle_position(self, employee_id, position):
        self.run_db_task(self._guarded([employee_id], lambda: db.toggle_position_in_db(employee_id, position)),
                         refresh_after=True)

    def import_logins(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Open login list", "", "Excel files (*.xlsx *.xlsm)"
        )
        if not filepath:
            return

        def done(result):
            count, matched, total = result
            QMessageBox.information(
                self, "Success",
                f"Logins loaded: {count}\nEmployees on the list with a login: {matched} of {total}",
            )

        self.run_db_task(lambda: db.import_logins_from_excel(filepath), on_finished=done, refresh_after=True)

    def move_employees(self, employee_ids, department, position, from_position="", add=False):
        """Kostka upuszczona w widoku Monitoring: zapis od razu, z aktualną godziną."""
        if not employee_ids:
            return
        if department in ("Naar Huis", "Ziek"):
            self.leave_work(employee_ids, "home" if department == "Naar Huis" else "sick")
            return

        from_start = self.monitoring_view.from_start
        self.run_db_task(
            self._guarded(employee_ids, lambda: db.move_employees_in_db(
                employee_ids, department, position, from_position=from_position, add=add, from_start=from_start
            )),
            on_finished=self._show_errors,
            refresh_after=True,
        )

    def _show_errors(self, errors):
        if errors:
            QMessageBox.warning(self, "Warning", "\n".join(errors))

    def _employees_by_ids(self, employee_ids):
        wanted = set(employee_ids)
        return [e for e in self.model.all_employees if e.employee_id in wanted]

    def leave_work(self, employee_ids, kind):
        """Naar Huis / Ziek: okienko z godziną odbicia albo „cały dzień"."""
        people = self._employees_by_ids(employee_ids)
        if not people:
            return
        dialog = LeaveDialog(kind, [f"{e.firstname} {e.lastname}" for e in people],
                             all_day_default=self.monitoring_view.from_start, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        time_chosen, all_day = dialog.values()
        self.run_db_task(
            self._guarded(employee_ids, lambda: db.leave_work_in_db(employee_ids, kind, time_chosen,
                                                                    all_day=all_day)),
            on_finished=self._show_errors,
            refresh_after=True,
        )

    def group_home(self):
        dialog = GroupHomeDialog(self.model.all_employees, self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected_ids():
            return
        ids, time_chosen = dialog.selected_ids(), dialog.value()
        self.run_db_task(self._guarded(ids, lambda: db.leave_work_in_db(ids, "home", time_chosen)),
                         on_finished=self._show_errors, refresh_after=True)

    def monitoring_action(self, action, employee_ids):
        people = self._employees_by_ids(employee_ids)
        if not people:
            return
        if action == "time":
            current = QTime.fromString(people[0].active_since, "HH:mm")
            dialog = TimeDialog("Change time", "New clock-out time (Naar Huis / Ziek) for: "
                                + ", ".join(f"{e.firstname} {e.lastname}" for e in people),
                                current if current.isValid() else None, self)
            if dialog.exec() == QDialog.Accepted:
                time_chosen = dialog.value()
                self.run_db_task(self._guarded(employee_ids,
                                               lambda: db.change_leave_time_in_db(employee_ids, time_chosen)),
                                 on_finished=self._show_errors, refresh_after=True)
        elif action == "back":
            self.run_db_task(self._guarded(employee_ids, lambda: db.back_to_work_in_db(employee_ids)),
                             on_finished=self._show_errors, refresh_after=True)
        elif action == "zones":
            dialog = ZonePickerDialog(people[0], self)
            if dialog.exec() == QDialog.Accepted:
                positions, emp_id = dialog.positions(), people[0].employee_id
                self.run_db_task(self._guarded([emp_id], lambda: db.set_positions_in_db(emp_id, positions)),
                                 refresh_after=True)

    def update_count_label(self):
        shown = len(self.model.employees)
        total = len(self.model.all_employees)
        self.count_label.setText(f"{shown} / {total} employees" if shown != total else f"{total} employees")

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

    def export_hours(self):
        """Etap 6: godziny tej zmiany do kopii tygodniowego pliku Uren_Lijst (podgląd przed zapisem)."""
        shift = db.resolved_shift()
        employees = list(self.model.all_employees)
        if not shift or not employees:
            QMessageBox.information(self, "Hours to Excel", "There is no shift with people to export.")
            return
        _, shift_date, shift_name = shift
        day = hours_export.parse_date(shift_date)
        settings = QSettings("PlanningManager", "PlanningManager")
        start_dir = settings.value("hours_folder", "")
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Week file with hours (the original is only read)", start_dir, "Excel files (*.xlsx)")
        if not filepath:
            return
        settings.setValue("hours_folder", os.path.dirname(filepath))
        sheet_name = hours_export.day_sheet_name(day)
        original = hours_export.original_path(filepath)
        target = hours_export.copy_path(original)
        base = original
        if os.path.exists(target):
            box = QMessageBox(QMessageBox.Question, "Hours to Excel",
                              f"{os.path.basename(target)} already exists.\n\n"
                              "Add this shift to the existing copy (hours written earlier stay), "
                              "or start a new copy from the original (earlier hours in the copy are lost)?", parent=self)
            keep = box.addButton("Add to the copy", QMessageBox.AcceptRole)
            fresh = box.addButton("New copy from the original", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(keep)
            box.exec()
            if box.clickedButton() is keep:
                base = target
            elif box.clickedButton() is not fresh:
                return

        def show_preview(loaded):
            sheet, zones = loaded
            lines = hours_export.propose(employees, sheet, remembered_columns(), zones)
            source = "existing copy" if base == target else "original"
            title = (f"{os.path.basename(base)} ({source}) → sheet {sheet_name} "
                     f"({day:%d-%m-%Y}, {shift_name}) → {os.path.basename(target)}")
            dialog = HoursDialog(lines, sheet, title, hours_export.check_week(sheet, day), self)
            if dialog.exec() != QDialog.Accepted:
                return
            remember_columns(dialog.column_choices())
            values, notes, _ = hours_export.build_changes(dialog.lines, sheet)

            def done(path):
                QMessageBox.information(
                    self, "Hours to Excel",
                    f"Written and checked: {len(values)} hour cells, {len(notes)} notes.\n\n{path}\n\n"
                    "Excel recalculates the totals when the copy is opened.")

            self.run_db_task(
                lambda: self._hours_step(hours_export.write_copy, base, sheet, values, notes,
                                         dst=target, overwrite=True, original=original),
                on_finished=lambda result: self._hours_result(result, done),
            )

        def load():
            return (hours_export.read_day_sheet(base, sheet_name),
                    db.zone_periods(emp.employee_id for emp in employees))

        self.run_db_task(lambda: self._hours_step(load),
                         on_finished=lambda result: self._hours_result(result, show_preview))

    @staticmethod
    def _hours_step(func, *args, **kwargs):
        """Błędy pliku godzin wracają jako tekst (własny komunikat zamiast „Database Error")."""
        try:
            return True, func(*args, **kwargs)
        except PermissionError:
            return False, "The file is open in Excel or there is no write permission.\nClose the copy and try again."
        except Exception as exc:  # noqa: BLE001 – każdy błąd ma trafić do użytkownika
            return False, str(exc)

    def _hours_result(self, result, on_success):
        ok, value = result
        if ok:
            on_success(value)
        else:
            QMessageBox.warning(self, "Hours to Excel", f"Nothing was written.\n\n{value}")

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
                self._guarded(employee_ids, lambda: db.delete_employees_from_db(employee_ids)),
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
                self._guarded(data["employee_ids"], lambda: db.add_departments_to_db(
                    data["employee_ids"],
                    data["department"],
                    data["time"],
                )),
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
            self._guarded(employee_ids, lambda: db.remove_last_departments_from_db(employee_ids)),
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
                self._guarded(data["employee_ids"], lambda: db.edit_departments_in_db(
                    data["employee_ids"],
                    data["department"],
                )),
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
            self._guarded([i for i, _ in items], lambda: db.mark_employees_late_in_db(items)),
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

        def task():
            return db.import_excel_to_db(filepaths), db.employees_without_plan_hours()

        def done(result):
            (count, skipped, unknown), no_hours = result
            msg = f"Data imported successfully. Imported rows: {count}"
            if skipped:
                msg += f"\nSkipped duplicates (already in the database): {skipped}"
            if unknown:
                msg += (
                    "\n\nDepartments not on the department list "
                    "(shown under 'Other / unknown' in Monitoring):\n- " + "\n- ".join(unknown)
                )
                QMessageBox.warning(self, "Imported with warnings", msg)
            else:
                QMessageBox.information(self, "Success", msg)
            if no_hours:
                self.fix_plan_hours(no_hours)

        self.run_db_task(task, on_finished=done, refresh_after=True)

    def fix_plan_hours(self, rows):
        """Osoby z 00:00-00:00 w planie: okienko z możliwością wpisania godzin."""
        dlg = PlanHoursDialog(rows, self)
        if dlg.exec() != QDialog.Accepted:
            return
        changes = dlg.changes()

        def done(errors):
            if errors:
                QMessageBox.warning(self, "Plan without working hours", "Not changed:\n\n" + "\n".join(errors))

        self.run_db_task(lambda: db.set_plan_hours_in_db(changes), on_finished=done, refresh_after=True)

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
