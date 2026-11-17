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

    pladis = view.position_zones[("Orderpicker", "Pladis (22)")]
    assert pladis.ids() == [a]
    assert view.unassigned.ids() == [b]          # Reach bez strefy
    assert view.zones["Naar Huis"].ids() == [c]
    assert view.other_zone.ids() != [] and not view.other_zone.isHidden()
    assert pladis.list.item(0).text() == "Anna Kowalski"   # karta: imię i nazwisko (bez loginu)

    # kto poszedł do domu, tego nie da się przeciągnąć
    home_item = view.zones["Naar Huis"].list.item(0)
    assert not (home_item.flags() & Qt.ItemIsDragEnabled)

    received = []
    view.move_requested.connect(lambda *args: received.append(args))
    toggled = []
    view.toggle_position_requested.connect(lambda *args: toggled.append(args))

    # upuszczenie na dział
    view.zones["Laden"].list.dropped.emit([a], "Pladis (22)", False)
    # upuszczenie na strefę w hali South, z Ctrl = dołóż
    view.position_zones[("Reachtruck", "Zuid")].list.dropped.emit([a], "", True)
    assert received == [
        ([a], "Laden", "", "Pladis (22)", False),
        ([a], "Reachtruck", "Zuid", "", True),
    ]

    # prawy klik -> zdjęcie ze strefy
    pladis.list.action_requested.emit("remove", [a])
    assert toggled == [(a, "Pladis (22)")]

    # upuszczenie na Naar Huis / Ziek i akcje z menu idą do okienek w głównym oknie
    leave, actions = [], []
    view.leave_requested.connect(lambda *args: leave.append(args))
    view.action_requested.connect(lambda *args: actions.append(args))
    view.zones["Naar Huis"].list.dropped.emit([a], "", False)
    view.zones["Ziek"].list.dropped.emit([a], "", False)
    pladis.list.action_requested.emit("zones", [a])
    view.zones["Naar Huis"].list.action_requested.emit("time", [c])
    assert leave == [([a], "home"), ([a], "sick")]
    assert actions == [("zones", [a]), ("time", [c])]
    assert view.zones["Naar Huis"].list.item(0).text().endswith("·  12:00")   # godzina wyjścia na karcie

    # tryb „od początku zmiany": pasek widoczny, sam się wyłącza po terminie
    view.from_start_button.setChecked(True)
    assert view.from_start and not view.from_start_banner.isHidden()
    from datetime import datetime, timedelta
    view.from_start_deadline = datetime.now() - timedelta(seconds=1)
    view._check_from_start()
    assert not view.from_start and view.from_start_banner.isHidden()

    # liczniki
    assert view.kpi_labels["Picking"].text() == "Picking:  <b>1</b>"
    assert view.kpi_labels["Unassigned"].text() == "Unassigned:  <b>1</b>"
    assert view.kpi_labels["Naar Huis"].text() == "Naar Huis:  <b>1</b>"


def test_halls(app, temp_db):
    from pm.config import hall_of

    assert hall_of("Reachtruck", "Noord") == "North"
    assert hall_of("Reachtruck", "Mars ITR") == "South"
    assert hall_of("Orderpicker", "Choco (12)") == "North"
    assert hall_of("Orderpicker", "Jordan") == "South"

    emp_id = make_employee(department="Reachtruck")
    db.toggle_position_in_db(emp_id, "Noord")
    db.toggle_position_in_db(emp_id, "Zuid")
    view = MonitoringView()
    view.set_employees(db.load_employees_from_db())
    # osoba w dwóch halach naraz -> karta w obu
    assert "NORTH" in view.halls["North"].header.text()
    assert "1 people" in view.halls["North"].header.text()
    assert "1 people" in view.halls["South"].header.text()
    view.halls["South"].header.click()   # zwinięcie hali
    assert view.halls["South"].body.isHidden()


def test_old_itr_zone_renamed(temp_db):
    emp_id = make_employee(department="Orderpicker")
    db.toggle_position_in_db(emp_id, "ITR (18 20)")
    db.init_db()
    assert _one().positions == ["Mars ITR (18 20)"]


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
    marked = [pos for (dept, pos), zone in view.position_zones.items() if zone.ids()]
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
    assert view.zones["Laden"].list.item(0).text() == "007 – Jan van Dijk"


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
    assert len(window.monitoring_view.unassigned.ids()) == 1
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
    assert "Buffer" in view.zones
    assert view.position_zones[("Reachtruck", "Na-Nomi")].ids() == [by_name["Kowalski"].employee_id]

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
