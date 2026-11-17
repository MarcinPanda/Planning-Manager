import os

import pandas as pd

from pm import config, db

from conftest import make_employee


def _one():
    employees = db.load_employees_from_db()
    assert len(employees) == 1
    return employees[0]


def test_insert_and_load(temp_db):
    make_employee()
    emp = _one()
    assert (emp.lastname, emp.firstname, emp.work_hours) == ("Test", "Anna", "06:00-15:00")
    assert emp.computed_hours == "8.00"


def test_custom_breaks_are_persisted(temp_db):
    make_employee(work_hours="08:00-17:00", shift="Custom", computed_hours=8.5, custom_breaks=[(720, 750)])
    emp = _one()
    assert emp.custom_breaks == [(720, 750)]
    assert emp.computed_hours == "8.50"


def test_add_department_and_order_validation(temp_db):
    emp_id = make_employee()
    assert db.add_departments_to_db([emp_id], "Reachtruck", "10:00") == []

    errors = db.add_departments_to_db([emp_id], "Laden", "09:00")
    assert len(errors) == 1 and "earlier" in errors[0]

    errors = db.add_departments_to_db([emp_id], "Laden", "16:00")
    assert len(errors) == 1 and "after the end" in errors[0]

    assert dict(_one().dept_intervals) == {"Buffer": 3.75, "Reachtruck": 4.25}


def test_naar_huis_shortens_work_hours(temp_db):
    emp_id = make_employee()
    db.add_departments_to_db([emp_id], "Naar Huis", "12:00")
    emp = _one()
    assert emp.work_hours == "06:00-12:00"
    assert emp.status == "home"


def test_remove_last_department(temp_db):
    emp_id = make_employee()
    db.add_departments_to_db([emp_id], "Reachtruck", "10:00")
    assert db.remove_last_departments_from_db([emp_id]) == []
    assert dict(_one().dept_intervals) == {"Buffer": 8.0}
    assert len(db.remove_last_departments_from_db([emp_id])) == 1  # nie ma już czego usuwać


def test_mark_late(temp_db):
    emp_id = make_employee()
    errors = db.mark_employees_late_in_db([(emp_id, "07:00"), (999, "07:00")])
    assert len(errors) == 1
    emp = _one()
    assert emp.work_hours == "07:00-15:00"
    assert emp.late and emp.status == "late"


def test_undo_restores_previous_state(temp_db):
    emp_id = make_employee()
    db.add_departments_to_db([emp_id], "Reachtruck", "10:00")
    db.mark_employees_late_in_db([(emp_id, "07:00")])

    assert db.undo_last().startswith("Late")
    assert _one().work_hours == "06:00-15:00" and not _one().late

    assert db.undo_last().startswith("Add department")
    assert dict(_one().dept_intervals) == {"Buffer": 8.0}

    assert db.undo_last().startswith("Add employee")
    assert db.load_employees_from_db() == []

    assert db.undo_last() is None


def test_undo_delete_and_clear(temp_db):
    emp_id = make_employee()
    db.add_departments_to_db([emp_id], "Reachtruck", "10:00")

    db.delete_employees_from_db([emp_id])
    assert db.load_employees_from_db() == []
    db.undo_last()
    assert dict(_one().dept_intervals) == {"Buffer": 3.75, "Reachtruck": 4.25}

    archive = db.clear_all_data_in_db()
    assert archive and os.path.exists(archive)
    assert db.load_employees_from_db() == []
    db.undo_last()
    assert _one().employee_id == emp_id


def test_change_log(temp_db):
    emp_id = make_employee()
    db.update_employee_info_in_db(emp_id, "note")
    db.undo_last()
    actions = [row[2] for row in db.load_change_log()]
    assert actions == ["Undo", "Edit info", "Add employee"]
    assert _one().info == ""


def test_backup_only_when_there_is_data(temp_db):
    assert db.backup_db() is None  # pusta baza – bez kopii
    make_employee()
    path = db.backup_db()
    assert path and os.path.exists(path)


def _write_plan(path):
    rows = [
        [None, "Warehouse / Ochtend / Buffer / Week 47", None, None, None, None],
        [None, None, None, "Achternaam", "Voornaam", "Uren"],
        [None, None, None, "KOWALSKI", "JAN", "06:00-15:00"],
        [None, None, None, "van DIJK", "PIET", "06:00-15:00"],
    ]
    pd.DataFrame(rows).to_excel(path, header=False, index=False)


def test_import_skips_duplicates(temp_db):
    plan = str(temp_db / "plan.xlsx")
    _write_plan(plan)

    assert db.import_excel_to_db([plan]) == (2, 0, [])
    assert db.import_excel_to_db([plan]) == (0, 2, [])

    names = sorted((e.lastname, e.firstname) for e in db.load_employees_from_db())
    assert names == [("Dijk", "Piet van"), ("Kowalski", "Jan")]

    db.undo_last()  # cofnięcie importu usuwa zaimportowane osoby
    assert db.load_employees_from_db() == []


def test_section_header_and_cleanup():
    from pm.excel_io import normalize_department, normalize_hours, parse_section_header

    assert parse_section_header(" / Warehouse 1 / Ochtend / Ass TL/ Week47") == ("Ochtend", "Ass TL")
    assert parse_section_header(" / Warehouse 1 / Middag / Stuwarooij/Omstapelen/ Week47") == (
        "Middag", "Stuwarooij/Omstapelen")
    assert normalize_department("Bufferzone") == "Buffer"
    assert normalize_department("Stock Controle") == "Stock Control"
    assert normalize_department("Consolidatie") == "Consolidatie/Kantelen"
    assert normalize_department("orderpicker") == "Orderpicker"
    assert normalize_department("Nanomi  Reachtruck") == "Nanomi Reachtruck"
    assert normalize_department("Orderpicker/Picking") == "Orderpicker"
    assert normalize_department("Picking / Orderpicker") == "Orderpicker"
    assert normalize_department("Stock-Controle") == "Stock Control"
    assert normalize_department("Something New") == "Something New"
    assert normalize_department("Overig") == "Extra"
    assert normalize_department("Rangeren") == "Pendel"
    assert normalize_department("Inleren Orderpicker") == "Inleren Orderpicker"
    assert normalize_hours("06:00-15:00 ") == "06:00-15:00"
    assert normalize_hours("6:00 - 15:00") == "06:00-15:00"


def test_old_database_is_migrated(temp_db):
    import sqlite3

    os.remove(config.DB_PATH)
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("""
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT, lastname TEXT NOT NULL, firstname TEXT NOT NULL,
            current_department TEXT NOT NULL, work_hours TEXT NOT NULL, shift TEXT NOT NULL,
            computed_hours REAL NOT NULL
        )
    """)
    conn.execute("INSERT INTO employees (lastname, firstname, current_department, work_hours, shift, computed_hours) "
                 "VALUES ('Old', 'Row', 'Buffer', '06:00-15:00', 'Ochtend', 8.0)")
    conn.commit()
    conn.close()

    db.init_db()
    assert _one().lastname == "Old"
