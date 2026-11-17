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
    c = make_employee(lastname="Dijk", department="Laden")
    make_employee(lastname="Strange", department="Unknown")
    db.move_employees_in_db([a], "Orderpicker", "Pladis (22)", "09:00")
    db.move_employees_in_db([c], "Naar Huis", "", "12:00")

    view = MonitoringView()
    view.set_employees(db.load_employees_from_db())

    def zone_ids(dept):
        lst = view.zones[dept].list
        return [lst.item(i).data(Qt.UserRole) for i in range(lst.count())]

    def table_ids(dept):
        return [e.employee_id for e in view.tables[dept].employees]

    assert table_ids("Orderpicker") == [a]
    assert table_ids("Reachtruck") == [b]
    assert zone_ids("Naar Huis") == [c]
    assert view.other_zone.list.count() == 1

    # zielona komórka w kolumnie Pladis
    table = view.tables["Orderpicker"]
    col = table.FIXED_COLS + table.positions.index("Pladis (22)")
    assert table.item(0, col).text() == "✓"
    assert table.item(0, col - 1).text() == ""

    # kto poszedł do domu, tego nie da się przeciągnąć
    home_item = view.zones["Naar Huis"].list.item(0)
    assert not (home_item.flags() & Qt.ItemIsDragEnabled)

    received = []
    view.move_requested.connect(lambda *args: received.append(args))
    toggled = []
    view.toggle_position_requested.connect(lambda *args: toggled.append(args))

    # upuszczenie na kafel działu
    view.zones["Laden"].list.dropped.emit([a], "", False)
    # upuszczenie na kolumnę strefy w tabeli = przeniesienie od razu do tej strefy
    reach = view.tables["Reachtruck"]
    reach.handle_drop([a], reach.FIXED_COLS + reach.positions.index("Zuid"))
    # upuszczenie na nazwisko = do działu bez strefy
    reach.handle_drop([a], 0)
    assert received == [
        ([a], "Laden", "", "", False),
        ([a], "Reachtruck", "Zuid", "", False),
        ([a], "Reachtruck", "", "", False),
    ]

    # kliknięcie komórki strefy
    table._on_cell_clicked(0, col)
    table._on_cell_clicked(0, 0)  # klik w nazwisko nic nie przełącza
    assert toggled == [(a, "Pladis (22)")]


def test_several_zones_at_once(app, temp_db):
    emp_id = make_employee(department="Reachtruck")

    # klikanie komórek: kilka stref naraz
    db.toggle_position_in_db(emp_id, "Noord")
    db.toggle_position_in_db(emp_id, "Replenish")
    emp = _one()
    assert emp.positions == ["Noord", "Replenish"]
    assert emp.dept_times == [("Reachtruck", "")]   # godziny bez zmian
    assert emp.computed_hours == "8.00"

    view = MonitoringView()
    view.set_employees(db.load_employees_from_db())
    table = view.tables["Reachtruck"]
    marked = [p for i, p in enumerate(table.positions) if table.item(0, table.FIXED_COLS + i).text() == "✓"]
    assert marked == ["Noord", "Replenish"]

    db.toggle_position_in_db(emp_id, "Noord")
    assert _one().positions == ["Replenish"]
    db.undo_last()
    assert _one().positions == ["Noord", "Replenish"]

    # przeniesienie z innego działu prosto na strefę
    other = make_employee(lastname="Other", department="Laden")
    db.move_employees_in_db([other], "Reachtruck", "Kantel/Consolidatie", "10:00")
    moved = [e for e in db.load_employees_from_db() if e.employee_id == other][0]
    assert (moved.active_department, moved.positions) == ("Reachtruck", ["Kantel/Consolidatie"])

    # przejście do innego działu kasuje strefy
    db.move_employees_in_db([emp_id], "Laden", "", "10:00")
    assert [e for e in db.load_employees_from_db() if e.employee_id == emp_id][0].positions == []


def test_logins_import_and_matching(app, temp_db):
    import pandas as pd
    from pm.excel_io import normalize_login
    from pm.logic import name_key

    assert name_key("Jan van", "Dijk") == name_key("jan VAN dijk")
    assert name_key("Łukasz", "Żółw") == name_key("lukasz zolw")
    assert [normalize_login(x) for x in ["N012P", "Z012P", "R012R", "12", "012", "12.0", "0", "abc", None]] == \
        ["012", "012", "012", "012", "012", "012", "", "", ""]

    make_employee(lastname="Dijk", firstname="Jan van")
    make_employee(lastname="Nowak", firstname="Ewa")

    # układ jak w pliku Inlognamen: Naam + kody N…P / Z…P / R…R
    path = str(temp_db / "inlognamen.xlsx")
    rows = [["R", "Nummer-1", "Naam", "Noord", "Zuid", "Reach"],
            ["7", "7", "Jan van Dijk", "N007P", "Z007P", "R007R"],
            ["12", "12", "Somebody Else", "N012P", "Z012P", "R012R"],
            ["13", "13", None, "N013P", "Z013P", "R013R"]]
    pd.DataFrame(rows).to_excel(path, sheet_name="Inlognamen", header=False, index=False)

    assert db.import_logins_from_excel(path) == (2, 1, 2)

    by_name = {e.lastname: e.login for e in db.load_employees_from_db()}
    assert by_name == {"Dijk": "007", "Nowak": ""}

    # starszy układ: zakładka Logins z kolumnami Login: / Name:
    path2 = str(temp_db / "logins.xlsx")
    rows2 = [[None, None, None], [None, "Login:", "Name:"], [None, "021", "Ewa Nowak"], [None, "0", "0"]]
    with pd.ExcelWriter(path2) as writer:
        pd.DataFrame([["x"]]).to_excel(writer, sheet_name="Tools", header=False, index=False)
        pd.DataFrame(rows2).to_excel(writer, sheet_name="Logins", header=False, index=False)
    assert db.import_logins_from_excel(path2) == (1, 2, 2)

    # loginy zostają po wyczyszczeniu listy i ponownym dodaniu osoby
    db.clear_all_data_in_db()
    make_employee(lastname="Dijk", firstname="Jan van", department="Laden")
    assert db.load_employees_from_db()[0].login == "007"

    view = MonitoringView()
    view.set_employees(db.load_employees_from_db())
    assert "[007]" in view.zones["Laden"].list.item(0).text()


def test_main_window_with_monitoring(app, temp_db):
    from pm.main_window import MainWindow

    make_employee(department="Orderpicker")
    window = MainWindow()
    window.sync_timer.stop()

    from test_ui_smoke import QApplicationSleep
    for _ in range(200):
        app.processEvents()
        if window.model.rowCount() == 1 and not window._active_threads:
            break
        QApplicationSleep(app)

    window.show_view(1)
    assert window.stack.currentIndex() == 1
    assert len(window.monitoring_view.tables["Orderpicker"].employees) == 1
    window.close()


def test_nanomi_is_reach_zone_and_buffer_is_plain(app, temp_db):
    import sqlite3

    import pandas as pd

    from pm import config

    plan = str(temp_db / "plan.xlsx")
    rows = [
        [None, " / Warehouse 1 / Ochtend / Nanomi Reachtruck/ Week47", None, None, None, None],
        [None, None, None, "Achternaam", "Voornaam", "Uren"],
        [None, None, None, "Kowalski", "Jan", "06:00-15:00"],
        [None, " / Warehouse 1 / Ochtend / Bufferzone/ Week47", None, None, None, None],
        [None, None, None, "Nowak", "Ewa", "06:00-15:00"],
    ]
    pd.DataFrame(rows).to_excel(plan, header=False, index=False)
    assert db.import_excel_to_db([plan]) == (2, 0, [])

    by_name = {e.lastname: e for e in db.load_employees_from_db()}
    assert (by_name["Kowalski"].active_department, by_name["Kowalski"].positions) == ("Reachtruck", ["Na-Nomi"])
    assert by_name["Kowalski"].computed_hours == "8.00"
    assert (by_name["Nowak"].active_department, by_name["Nowak"].positions) == ("Buffer", [])

    view = MonitoringView()
    view.set_employees(db.load_employees_from_db())
    assert "Buffer" in view.zones and "Buffer" not in view.tables
    assert [e.lastname for e in view.tables["Reachtruck"].employees] == ["Kowalski"]

    # baza z poprzedniej wersji: „Nanomi Reachtruck" jako osobny dział -> Reach + Na-Nomi
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("UPDATE employees SET current_department = 'Nanomi Reachtruck', position = '' WHERE lastname = 'Kowalski'")
    conn.execute("UPDATE departments SET department = 'Nanomi Reachtruck' WHERE department = 'Reachtruck'")
    conn.commit()
    conn.close()
    db.init_db()
    emp = {e.lastname: e for e in db.load_employees_from_db()}["Kowalski"]
    assert (emp.active_department, emp.positions) == ("Reachtruck", ["Na-Nomi"])


def test_logins_reader_does_not_need_pandas(temp_db):
    import subprocess
    import sys

    import pandas as pd

    path = str(temp_db / "inlognamen.xlsx")
    pd.DataFrame([["Naam", "Noord", "Reach"], ["Jan Kowalski", "N012P", "R012R"]]).to_excel(
        path, sheet_name="Inlognamen", header=False, index=False)

    code = (
        "import sys; sys.path.insert(0, '.');"
        "from pm.excel_io import read_logins_excel;"
        f"print(read_logins_excel({path!r}));"
        "print('pandas' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.split("\n")
    assert out[0] == "[('Jan Kowalski', '012')]"
    assert out[1] == "False"
