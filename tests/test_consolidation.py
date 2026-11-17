from datetime import date, datetime, time, timedelta

import openpyxl
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from pm import db
from pm.consolidation_view import COL, ConsolidationView
from pm.excel_io import parse_reachers

from conftest import make_employee

TODAY = date.today().isoformat()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _emp(emp_id):
    return [e for e in db.load_employees_from_db() if e.employee_id == emp_id][0]


def _add_login(name, login):
    conn = db.get_connection()
    conn.execute("INSERT INTO logins (name_key, name, login) VALUES (?, ?, ?)", (db.name_key(name), name, login))
    conn.commit()
    conn.close()


def test_parse_reachers():
    assert parse_reachers("R003R/R091R") == ["003", "091"]
    assert parse_reachers("R052R / R105R") == ["052", "105"]
    assert parse_reachers("r118r") == ["118"]
    assert parse_reachers("???") == []
    assert parse_reachers(None) == []


def test_assign_reacher_switches_zone_until_v(temp_db):
    reacher = make_employee(lastname="Reach", firstname="Ron", department="Reachtruck")
    db.toggle_position_in_db(reacher, "Noord")
    _add_login("Ron Reach", "052")

    kantel_rit = db.add_consolidation_in_db(TODAY, "526001", time="10:00", amount=20, kantel=20)
    mixed_rit = db.add_consolidation_in_db(TODAY, "526002", time="11:00", amount=10, kantel=4)

    # przypisanie -> strefa Kantel zamiast Noord
    changes = db.update_consolidation_in_db(kantel_rit, reachers=["052"])
    assert changes and _emp(reacher).positions == ["Kantel"]

    # drugi RIT z paletami do kantelowania i konsolidacji -> obie strefy
    db.update_consolidation_in_db(mixed_rit, reachers=["052"])
    assert _emp(reacher).positions == ["Consolidatie", "Kantel"]

    # pierwszy zwieziony -> zostaje to, czego wymaga drugi RIT
    db.update_consolidation_in_db(kantel_rit, v=True)
    assert _emp(reacher).positions == ["Consolidatie", "Kantel"]

    # oba zwiezione -> wraca Noord
    db.update_consolidation_in_db(mixed_rit, v=True)
    assert _emp(reacher).positions == ["Noord"]
    assert _emp(reacher).dept_times == [("Reachtruck", "")]  # godziny bez zmian

    # Done (konsolidacja zrobiona) niczego już nie zmienia
    assert db.update_consolidation_in_db(mixed_rit, done=True) == []


def test_reacher_without_login_and_outside_reach(temp_db):
    reacher = make_employee(lastname="NoLogin", department="Reachtruck")
    picker = make_employee(lastname="Picker", department="Orderpicker")
    rit = db.add_consolidation_in_db(TODAY, "1", amount=5, kantel=0)

    db.update_consolidation_in_db(rit, reachers=[f"id:{reacher}", f"id:{picker}"])
    assert _emp(reacher).positions == ["Consolidatie"]
    assert _emp(picker).positions == []   # nie jest w Reach – na Monitoringu bez zmian

    # osoba przeniesiona do Reach w trakcie dostaje od razu strefę z RIT-u
    db.move_employees_in_db([picker], "Reachtruck", "Zuid", "10:00")
    assert _emp(picker).positions == ["Consolidatie"]

    # zdjęcie reachera z RIT-u -> wracają poprzednie strefy
    db.update_consolidation_in_db(rit, reachers=[])
    assert _emp(reacher).positions == []
    assert _emp(picker).positions == ["Zuid"]


def test_delete_rit_releases_reacher(temp_db):
    reacher = make_employee(department="Reachtruck")
    rit = db.add_consolidation_in_db(TODAY, "7", amount=3, kantel=3)
    db.update_consolidation_in_db(rit, reachers=[f"id:{reacher}"])
    assert _emp(reacher).positions == ["Kantel"]
    db.delete_consolidation_in_db([rit])
    assert _emp(reacher).positions == []
    assert db.load_consolidation() == []


def _write_cons_file(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Consolidatie"
    ws.append(["Datum", "RIT", "noord", "Time", "Amount", "Kantel", "Reacher", "V", 'Done " X "', "Lane", None,
               "Who was busy"])
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_import_from_excel_and_merge(temp_db):
    reacher = make_employee(lastname="Reach", firstname="Ron", department="Reachtruck")
    _add_login("Ron Reach", "003")

    today = datetime.combine(date.today(), time())
    old = today - timedelta(days=30)
    path = str(temp_db / "cons.xlsx")
    _write_cons_file(path, [
        [old, 1, "noord", time(8), 5, 5, "R003R", None, None, None, None, None],       # za stary
        [today, 526145, "noord", time(8), 12, 12, "R003R/R091R", None, None, "K-25", "action", None],
        [today, 526146, "zuid", time(9), 29, 0, None, None, None, None, None, None],
        [today, 526146, "zuid", time(9, 30), 3, 0, "???", "v", "x", None, None, "Johan"],  # ten sam RIT drugi raz
    ])

    added, updated, changes = db.import_consolidation_from_excel(path)
    assert (added, updated) == (3, 0)
    assert _emp(reacher).positions == ["Kantel"]

    rows = db.load_consolidation(TODAY)
    assert [(r["rit"], r["seq"]) for r in rows] == [("526145", 1), ("526146", 1), ("526146", 2)]
    first = rows[0]
    assert (first["time"], first["area"], first["reachers"], first["lane"], first["comment"]) == \
        ("08:00", "noord", ["003", "091"], "K-25", "action")
    assert rows[2]["reacher_text"] == "???" and rows[2]["v"] and rows[2]["done"]

    # zmiana w aplikacji nie jest nadpisywana kolejnym importem, a V z pliku dochodzi
    db.update_consolidation_in_db(rows[1]["id"], reachers=["003"], lane="B-1")
    _write_cons_file(path, [
        [today, 526145, "noord", time(8), 12, 12, "R003R/R091R", "v", None, "K-25", "action", None],
        [today, 526146, "zuid", time(9), 30, 0, "R099R", None, None, "A-9", None, None],
    ])
    added, updated, _ = db.import_consolidation_from_excel(path)
    assert (added, updated) == (0, 2)
    rows = {r["seq"] if r["rit"] == "526146" else 0: r for r in db.load_consolidation(TODAY)}
    assert rows[0]["v"] is True
    assert (rows[1]["reachers"], rows[1]["lane"], rows[1]["amount"]) == (["003"], "B-1", 30)
    assert _emp(reacher).positions == ["Consolidatie"]  # 526145 zwieziony, 526146 (bez kantelowania) otwarty


def test_consolidation_view(app, temp_db):
    reacher = make_employee(lastname="Reach", firstname="Ron", department="Reachtruck")
    _add_login("Ron Reach", "052")
    rit = db.add_consolidation_in_db(TODAY, "526001", time="10:00", amount=20, kantel=15)
    db.update_consolidation_in_db(rit, reachers=["052"], lane="K-1")

    view = ConsolidationView()
    view.set_data(db.load_consolidation(), db.load_employees_from_db(), db.login_names())
    assert view.table.rowCount() == 1
    assert view.table.item(0, COL["Reacher"]).text() == "Ron Reach [052]"
    assert view.table.item(0, COL["Consol."]).text() == "5"
    assert "to drive (no V): 1" in view.summary_label.text()

    received = []
    view.update_requested.connect(lambda *args: received.append(args))
    view.table.item(0, COL["V"]).setCheckState(Qt.Checked)
    view.table.item(0, COL["Lane"]).setText("K-2")
    assert received == [(rit, {"v": True}), (rit, {"lane": "K-2"})]
    assert reacher


def test_main_window_has_consolidation_view(app, temp_db):
    from pm.main_window import MainWindow
    from test_ui_smoke import QApplicationSleep

    make_employee(department="Reachtruck")
    db.add_consolidation_in_db(TODAY, "1", amount=1)
    window = MainWindow(with_monitoring=True)
    window.sync_timer.stop()
    for _ in range(200):
        app.processEvents()
        if window.model.rowCount() == 1 and not window._active_threads:
            break
        QApplicationSleep(app)

    window.show_view(2)
    assert window.stack.currentWidget() is window.consolidation_view
    assert window.consolidation_view.table.rowCount() == 1
    window.close()
