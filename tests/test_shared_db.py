"""Etap 3: wspólna baza – zmiany (dni), przenoszenie starej bazy, licznik zmian, konflikty, cofanie."""
import glob
import os
import sqlite3

import pandas as pd
import pytest

from pm import config, db

from conftest import make_employee


def _plan(path, shift, day, people):
    rows = [[None, f" / Warehouse 1 / {shift} / Laden/ Week47", None, None, None, None, None],
            [None, "#", "Persoons#", "Achternaam", "Voornaam", "Badge", day]]
    for last, first, hours in people:
        rows.append([None, 1, "x", last, first, "1", hours])
    pd.DataFrame(rows).to_excel(path, header=False, index=False)
    return path


def test_old_database_is_migrated_with_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "old.db"))
    monkeypatch.setattr(config, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(db, "current_shift_id", None)
    conn = sqlite3.connect(config.DB_PATH)
    conn.executescript("""
        CREATE TABLE employees (id INTEGER PRIMARY KEY AUTOINCREMENT, lastname TEXT NOT NULL, firstname TEXT NOT NULL,
            current_department TEXT NOT NULL, work_hours TEXT NOT NULL, shift TEXT NOT NULL, computed_hours REAL NOT NULL);
        CREATE TABLE departments (id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id INTEGER NOT NULL,
            department TEXT NOT NULL, time_assigned TEXT DEFAULT '');
        INSERT INTO employees VALUES (1, 'Old', 'Ann', 'Laden', '15:00-00:00', 'Middag', 8);
        INSERT INTO departments VALUES (1, 1, 'Laden', '');
    """)
    conn.commit()
    conn.close()

    db.init_db()
    assert db.schema_version() == db.SCHEMA_VERSION
    assert glob.glob(os.path.join(config.BACKUP_DIR, "before_schema_v2_*.db"))   # kopia przed zmianą
    emp = db.load_employees_from_db()
    assert [e.lastname for e in emp] == ["Old"]
    assert db.resolved_shift()[2] == "Middag"
    db.init_db()   # drugi start nic nie psuje
    assert len(db.load_employees_from_db()) == 1


def test_shifts_keep_earlier_days(temp_db):
    morning = _plan(str(temp_db / "a.xlsx"), "Ochtend", "17-11-2026", [("Kowalski", "Jan", "06:00-15:00")])
    late = _plan(str(temp_db / "b.xlsx"), "Middag", "17-11-2026", [("Nowak", "Ewa", "15:00-00:00"),
                                                                   ("Dijk", "Piet", "15:00-00:00")])
    next_day = _plan(str(temp_db / "c.xlsx"), "Ochtend", "18-11-2026", [("Kowalski", "Jan", "06:00-15:00")])

    assert db.import_excel_to_db([morning])[:2] == (1, 0)
    assert db.import_excel_to_db([late])[:2] == (2, 0)
    assert db.import_excel_to_db([next_day])[:2] == (1, 0)   # ten sam człowiek, inny dzień – nie duplikat

    shifts = db.list_shifts()
    assert [(s[1], s[2], s[3]) for s in shifts] == [
        ("2026-11-18", "Ochtend", 1), ("2026-11-17", "Middag", 2), ("2026-11-17", "Ochtend", 1)]

    db.current_shift_id = shifts[1][0]
    assert sorted(e.lastname for e in db.load_employees_from_db()) == ["Dijk", "Nowak"]

    # „Delete this shift" usuwa tylko pokazywaną zmianę, z kopią w archiwum
    assert db.clear_all_data_in_db()
    assert [(s[1], s[2], s[3]) for s in db.list_shifts()][1] == ("2026-11-17", "Middag", 0)
    db.current_shift_id = shifts[0][0]
    assert [e.lastname for e in db.load_employees_from_db()] == ["Kowalski"]


def test_change_counter_and_last_change(temp_db):
    before, _ = db.change_state()
    emp = make_employee()
    db.move_employees_in_db([emp], "Laden", "", "10:00")
    after, last = db.change_state()
    assert after > before
    assert last[1] == db.USER and last[2] == "Move"


def test_conflict_when_someone_else_changed_the_person(temp_db):
    emp_id = make_employee(department="Laden")
    seen = {e.employee_id: e.fingerprint for e in db.load_employees_from_db()}
    db.assert_unchanged(seen)                                  # nic się nie zmieniło
    db.move_employees_in_db([emp_id], "Buffer", "", "10:00")   # „inny komputer"
    with pytest.raises(db.ConflictError):
        db.assert_unchanged(seen)


def test_undo_only_my_changes(temp_db, monkeypatch):
    a = make_employee(lastname="A", department="Laden")
    b = make_employee(lastname="B", department="Laden")
    db.move_employees_in_db([a], "Buffer", "", "09:00")       # moja zmiana

    me = db.USER
    monkeypatch.setattr(db, "USER", "someone-else")
    db.move_employees_in_db([b], "VAL", "", "09:30")           # cudza zmiana (inna osoba)
    monkeypatch.setattr(db, "USER", "me-again")
    assert db.undo_last() is None                              # nie mam nic do cofnięcia

    # UWAGA: nie używać monkeypatch.undo() – cofa też podmianę ścieżki bazy (test trafiłby w prawdziwą bazę)
    monkeypatch.setattr(db, "USER", me)
    assert db.undo_last().startswith("Move")                   # cofam swoją, cudza zostaje
    by_name = {e.lastname: e.active_department for e in db.load_employees_from_db()}
    assert by_name == {"A": "Laden", "B": "VAL"}


def test_undo_blocked_when_other_user_changed_same_person(temp_db, monkeypatch):
    a = make_employee(department="Laden")
    db.move_employees_in_db([a], "Buffer", "", "09:00")
    me = db.USER
    monkeypatch.setattr(db, "USER", "someone-else")
    db.move_employees_in_db([a], "VAL", "", "09:30")
    monkeypatch.setattr(db, "USER", me)
    with pytest.raises(db.ConflictError):
        db.undo_last()


def test_undo_of_old_snapshot_keeps_shift(temp_db):
    emp = make_employee(department="Laden")
    db.move_employees_in_db([emp], "Buffer", "", "09:00")
    # migawka zapisana przez starszą wersję (bez kolumny shift_id)
    conn = db.get_connection()
    entry_id, data = conn.execute("SELECT id, undo_data FROM change_log WHERE action = 'Move'").fetchone()
    import json
    payload = json.loads(data)
    payload["restore"][0]["row"] = payload["restore"][0]["row"][:13]
    conn.execute("UPDATE change_log SET undo_data = ? WHERE id = ?", (json.dumps(payload), entry_id))
    conn.commit()
    conn.close()
    db.undo_last()
    assert [e.active_department for e in db.load_employees_from_db()] == ["Laden"]   # nie znika z widoku


def test_hourly_backup_once_per_hour(temp_db):
    make_employee()
    assert db.backup_db("hourly")
    assert db.backup_db("hourly") is None
    assert len(glob.glob(os.path.join(config.BACKUP_DIR, "planning_hourly_*.db"))) == 1


def test_settings_file_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_PATH", str(tmp_path / "settings.ini"))
    assert config.read_database_folder() == config.BASE_DIR
    config.write_database_folder(r"\\server\share\planning")
    assert config.read_database_folder() == r"\\server\share\planning"


def test_plan_date_is_read_from_header(tmp_path):
    from pm.excel_io import read_plan_date
    path = _plan(str(tmp_path / "p.xlsx"), "Middag", "17-11-2026", [("X", "Y", "15:00-00:00")])
    assert read_plan_date([path]) == "2026-11-17"
