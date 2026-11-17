import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from pm import db
from pm.monitoring import MonitoringView

from conftest import make_employee


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _one():
    employees = db.load_employees_from_db()
    assert len(employees) == 1
    return employees[0]


def test_move_during_shift_adds_department(temp_db):
    emp_id = make_employee(department="Orderpicker")
    assert db.move_employees_in_db([emp_id], "Reachtruck", "Noord", "10:00") == []

    emp = _one()
    assert emp.active_department == "Reachtruck"
    assert emp.position == "Noord"
    assert emp.active_since == "10:00"
    assert dict(emp.dept_intervals) == {"Orderpicker": 3.75, "Reachtruck": 4.25}


def test_position_change_does_not_touch_hours(temp_db):
    emp_id = make_employee(department="Orderpicker")
    assert db.move_employees_in_db([emp_id], "Orderpicker", "Choco (12)", "10:00") == []

    emp = _one()
    assert emp.position == "Choco (12)"
    assert emp.dept_times == [("Orderpicker", "")]
    assert emp.computed_hours == "8.00"

    # drugi raz to samo miejsce -> nic się nie dzieje, brak wpisu w dzienniku
    before = len(db.load_change_log())
    assert db.move_employees_in_db([emp_id], "Orderpicker", "Choco (12)", "10:05") == []
    assert len(db.load_change_log()) == before


def test_move_before_shift_changes_initial_department(temp_db):
    emp_id = make_employee(department="Buffer")
    assert db.move_employees_in_db([emp_id], "Laden", "", "05:30") == []

    emp = _one()
    assert emp.dept_times == [("Laden", "")]
    assert emp.current_department == "Laden"
    assert emp.computed_hours == "8.00"


def test_move_errors(temp_db):
    emp_id = make_employee()
    errors = db.move_employees_in_db([emp_id], "Laden", "", "16:00")  # po końcu pracy
    assert len(errors) == 1 and "after the end" in errors[0]

    assert db.move_employees_in_db([emp_id], "Naar Huis", "", "12:00") == []
    assert _one().work_hours == "06:00-12:00"

    errors = db.move_employees_in_db([emp_id], "Laden", "", "12:30")
    assert len(errors) == 1 and "went home" in errors[0]


def test_move_is_undoable_and_position_resets(temp_db):
    emp_id = make_employee(department="Orderpicker")
    db.move_employees_in_db([emp_id], "Orderpicker", "Choco (12)", "09:00")
    db.move_employees_in_db([emp_id], "Reachtruck", "Zuid", "10:00")

    assert db.undo_last().startswith("Move")
    emp = _one()
    assert (emp.active_department, emp.position) == ("Orderpicker", "Choco (12)")

    # zmiana działu z tabeli (Add Department) kasuje pozycję
    db.add_departments_to_db([emp_id], "Buffer", "11:00")
    assert _one().position == ""


def test_view_groups_employees_into_zones(app, temp_db):
    a = make_employee(lastname="Kowalski", department="Orderpicker")
    b = make_employee(lastname="Nowak", department="Reachtruck")
    c = make_employee(lastname="Dijk", department="Buffer")
    make_employee(lastname="Strange", department="Unknown")
    db.move_employees_in_db([a], "Orderpicker", "Pladis (22)", "09:00")
    db.move_employees_in_db([c], "Naar Huis", "", "12:00")

    view = MonitoringView()
    view.set_employees(db.load_employees_from_db())

    def ids(key):
        lst = view.zones[key].list
        return [lst.item(i).data(Qt.UserRole) for i in range(lst.count())]

    assert ids(("Orderpicker", "Pladis (22)")) == [a]
    assert ids(("Orderpicker", "")) == []
    assert ids(("Reachtruck", "")) == [b]
    assert ids(("Naar Huis", "")) == [c]
    assert view.other_zone.list.count() == 1

    # kto poszedł do domu, tego nie da się przeciągnąć
    home_item = view.zones[("Naar Huis", "")].list.item(0)
    assert not (home_item.flags() & Qt.ItemIsDragEnabled)

    # upuszczenie na strefę wysyła prośbę o przeniesienie
    received = []
    view.move_requested.connect(lambda *args: received.append(args))
    view.zones[("Reachtruck", "Zuid")].list.dropped.emit([a], "Pladis (22)", True)
    assert received == [([a], "Reachtruck", "Zuid", "Pladis (22)", True)]


def test_several_zones_at_once(app, temp_db):
    emp_id = make_employee(department="Reachtruck")

    db.move_employees_in_db([emp_id], "Reachtruck", "Noord", "09:00")
    db.move_employees_in_db([emp_id], "Reachtruck", "Replenish", "09:05", from_position="Noord", add=True)
    emp = _one()
    assert emp.positions == ["Noord", "Replenish"]
    assert emp.dept_times == [("Reachtruck", "")]   # godziny bez zmian
    assert emp.computed_hours == "8.00"

    # kostka jest widoczna w obu strefach
    view = MonitoringView()
    view.set_employees(db.load_employees_from_db())
    assert view.zones[("Reachtruck", "Noord")].list.count() == 1
    assert view.zones[("Reachtruck", "Replenish")].list.count() == 1
    assert view.zones[("Reachtruck", "")].list.count() == 0

    # zwykłe przeciągnięcie kostki z Noord na Zuid zamienia tylko tę jedną strefę
    db.move_employees_in_db([emp_id], "Reachtruck", "Zuid", "09:10", from_position="Noord")
    assert _one().positions == ["Replenish", "Zuid"]

    # menu pod prawym przyciskiem: włącz / wyłącz strefę
    db.toggle_position_in_db(emp_id, "Kantel")
    assert _one().positions == ["Replenish", "Zuid", "Kantel"]
    db.toggle_position_in_db(emp_id, "Zuid")
    assert _one().positions == ["Replenish", "Kantel"]
    db.undo_last()
    assert _one().positions == ["Replenish", "Zuid", "Kantel"]

    # upuszczenie na „No position" zdejmuje tylko strefę, z której przeciągano
    db.move_employees_in_db([emp_id], "Reachtruck", "", "09:20", from_position="Kantel")
    assert _one().positions == ["Replenish", "Zuid"]

    # przejście do innego działu kasuje strefy
    db.move_employees_in_db([emp_id], "Laden", "", "10:00")
    assert _one().positions == []


def test_logins_import_and_matching(app, temp_db):
    import pandas as pd
    from pm.logic import name_key

    assert name_key("Jan van", "Dijk") == name_key("jan VAN dijk")
    assert name_key("Łukasz", "Żółw") == name_key("lukasz zolw")

    make_employee(lastname="Dijk", firstname="Jan van")
    make_employee(lastname="Nowak", firstname="Ewa")

    path = str(temp_db / "logins.xlsx")
    rows = [[None, None, None], [None, "Login:", "Name:"], [None, "007", "Jan van Dijk"],
            [None, "012", "Somebody Else"], [None, "0", "0"]]
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame([["x"]]).to_excel(writer, sheet_name="Tools", header=False, index=False)
        pd.DataFrame(rows).to_excel(writer, sheet_name="Logins", header=False, index=False)

    assert db.import_logins_from_excel(path) == (2, 1, 2)

    by_name = {e.lastname: e.login for e in db.load_employees_from_db()}
    assert by_name == {"Dijk": "7", "Nowak": ""}

    # loginy zostają po wyczyszczeniu listy i ponownym dodaniu osoby
    db.clear_all_data_in_db()
    make_employee(lastname="Dijk", firstname="Jan van")
    assert db.load_employees_from_db()[0].login == "7"

    view = MonitoringView()
    view.set_employees(db.load_employees_from_db())
    assert "[7]" in view.zones[("Buffer", "")].list.item(0).text()


def test_main_window_with_monitoring(app, temp_db):
    from pm.main_window import MainWindow

    make_employee(department="Orderpicker")
    window = MainWindow(with_monitoring=True)
    window.sync_timer.stop()

    from test_ui_smoke import QApplicationSleep
    for _ in range(200):
        app.processEvents()
        if window.model.rowCount() == 1 and not window._active_threads:
            break
        QApplicationSleep(app)

    window.view_toggle.setChecked(True)
    assert window.stack.currentIndex() == 1
    assert window.monitoring_view.zones[("Orderpicker", "")].list.count() == 1
    window.close()
