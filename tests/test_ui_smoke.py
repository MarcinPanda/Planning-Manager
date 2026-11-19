"""Test „dymny" okna: czy aplikacja się składa i podstawowe elementy działają (bez wyświetlania)."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from pm import db
from pm.config import columns
from pm.table_model import EmployeeTableModel

from conftest import make_employee


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_model_filter_and_colors(app, temp_db):
    a = make_employee(lastname="Kowalski", department="Buffer")
    make_employee(lastname="Nowak", department="Reachtruck")
    db.add_departments_to_db([a], "Ziek", "10:00")

    model = EmployeeTableModel(db.load_employees_from_db())
    assert model.rowCount() == 2
    assert model.columnCount() == len(columns)

    model.set_filter("kowal")
    assert model.rowCount() == 1
    assert model.data(model.index(0, 1)) == "Kowalski"
    assert model.data(model.index(0, 0), Qt.BackgroundRole) is not None  # chory -> kolor

    model.set_filter("reach")
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0), Qt.BackgroundRole) is None

    model.set_filter("")
    assert model.rowCount() == 2


def test_main_window_builds(app, temp_db):
    from pm.main_window import MainWindow

    make_employee()
    window = MainWindow()
    window.sync_timer.stop()

    # poczekaj na wczytanie danych w wątku
    for _ in range(200):
        app.processEvents()
        if window.model.rowCount() == 1 and not window._active_threads:
            break
        QApplicationSleep(app)

    assert window.model.rowCount() == 1
    assert len(window.visible_rows()[0]) == len(columns) - 1

    assert window.count_label.text() == "1 employees"
    assert [b.text().strip() for b in window.view_buttons] == ["Planning", "Monitoring", "Consolidatie", "Logins"]
    window.view_buttons[2].click()
    assert window.stack.currentWidget() is window.consolidation_view
    assert window.page_title.text() == "Consolidatie" and window.toggle_mark_button.isHidden()

    # zmiana motywu w locie (ikony i style odświeżone), powrót do poprzedniego
    from pm import theme
    before = theme.current_name
    window.apply_theme("light")
    assert theme.current_name == "light" and window.theme_action.text() == "Switch to dark theme"
    window.apply_theme(before)
    window.close()


def QApplicationSleep(app, ms=10):
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
