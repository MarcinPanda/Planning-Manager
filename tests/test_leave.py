"""Ziek / Naar Huis: godzina wyjścia, cały dzień, zmiana godziny, powrót, wiele osób, tryb od początku zmiany."""
from pm import db

from conftest import make_employee


def _emp(emp_id):
    return [e for e in db.load_employees_from_db() if e.employee_id == emp_id][0]


def _late(**kw):
    return make_employee(work_hours="15:00-00:00", shift="Middag", department="Orderpicker", **kw)


def test_home_on_late_shift_counts_hours_until_leaving(temp_db):
    a, b = _late(lastname="A"), _late(lastname="B")
    assert db.leave_work_in_db([a, b], "home", "21:15") == []      # masowo, jedna godzina
    emp = _emp(a)
    assert (emp.status, emp.active_since, emp.work_hours, emp.computed_hours) == \
        ("home", "21:15", "15:00-21:15", "5.50")
    assert _emp(b).computed_hours == "5.50"

    # faktyczne odbicie o 22:00 -> poprawka godziny
    assert db.change_leave_time_in_db([a], "22:00") == []
    assert (_emp(a).work_hours, _emp(a).computed_hours) == ("15:00-22:00", "6.25")
    # po północy i po końcu zmiany -> błąd
    assert db.change_leave_time_in_db([a], "00:30")

    # pomyłka -> z powrotem do pracy, godziny z planu
    assert db.back_to_work_in_db([a]) == []
    emp = _emp(a)
    assert (emp.status, emp.work_hours, emp.computed_hours) == ("", "15:00-00:00", "8.00")


def test_sick_during_shift_and_all_day(temp_db):
    a, b = _late(lastname="A"), _late(lastname="B")
    db.move_employees_in_db([a], "Laden", "", "18:00")

    assert db.leave_work_in_db([a], "sick", "19:00") == []
    emp = _emp(a)
    assert emp.status == "sick" and emp.active_since == "19:00"
    assert dict(emp.dept_intervals) == {"Orderpicker": 2.75, "Laden": 1.0}   # 15-18 (minus przerwa 17:15) i 18-19

    assert db.leave_work_in_db([b], "sick", all_day=True) == []
    emp = _emp(b)
    assert (emp.status, emp.computed_hours, emp.dept_times) == ("sick", "0.00", [("Ziek", "")])
    assert db.back_to_work_in_db([b])          # cały dzień -> tylko Cofnij
    assert db.undo_last() is not None
    assert _emp(b).dept_times == [("Orderpicker", "")]


def test_no_hours_in_plan_gives_clear_error(temp_db):
    a = make_employee(work_hours="00:00-00:00", shift="Middag")
    errors = db.leave_work_in_db([a], "home", "21:15")
    assert errors and "No working hours" in errors[0]


def test_from_start_mode_replaces_plan_department(temp_db):
    a = _late(lastname="A")
    assert db.move_employees_in_db([a], "Laden", "", "15:20", from_start=True) == []
    emp = _emp(a)
    assert emp.dept_times == [("Laden", "")] and emp.computed_hours == "8.00"

    db.move_employees_in_db([a], "Buffer", "", "18:00")
    errors = db.move_employees_in_db([a], "VAL", "", "18:10", from_start=True)
    assert errors and "already has changes" in errors[0]


def test_late_shift_move_before_start(temp_db):
    a = _late(lastname="A")
    assert db.move_employees_in_db([a], "Laden", "", "14:00") == []   # przed startem zmiany 15:00
    assert _emp(a).dept_times == [("Laden", "")]
    assert db.move_employees_in_db([a], "Buffer", "", "23:30") == []  # w trakcie, przed północą
    assert _emp(a).active_department == "Buffer"


def test_set_positions_and_shift_start(temp_db):
    a = _late(lastname="A")
    db.set_positions_in_db(a, ["Choco (12)", "Pladis (22)", "Ferrero (27+28)"])
    assert _emp(a).positions == ["Choco (12)", "Pladis (22)", "Ferrero (27+28)"]
    db.undo_last()
    assert _emp(a).positions == []
    make_employee(work_hours="00:00-00:00")
    assert db.shift_start_minutes(db.load_employees_from_db()) == 15 * 60
