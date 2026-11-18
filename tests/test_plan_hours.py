"""Godziny 00:00-00:00 w planie: wykrycie po imporcie i poprawka (okienko)."""
from conftest import make_employee

from pm import db


def _emp(emp_id):
    return next(e for e in db.load_employees_from_db() if e.employee_id == emp_id)


def test_finds_only_people_with_empty_plan_hours(temp_db):
    a = make_employee("Nowak", "Ewa", department="Laco", work_hours="00:00-00:00", shift="Middag", computed_hours=0)
    make_employee("Dijk", "Piet", department="Laden", work_hours="15:00-00:00", shift="Middag")
    rows = db.employees_without_plan_hours()
    assert [(r[0], r[1], r[3], r[4]) for r in rows] == [(a, "Nowak", "Laco", "Middag")]


def test_correcting_plan_hours_recalculates_and_can_be_undone(temp_db):
    a = make_employee("Nowak", "Ewa", department="Laco", work_hours="00:00-00:00", shift="Middag", computed_hours=0)
    assert db.set_plan_hours_in_db({a: "15:00-00:00"}) == []
    emp = _emp(a)
    assert (emp.work_hours, emp.planned_hours, emp.computed_hours) == ("15:00-00:00", "15:00-00:00", "8.00")
    assert db.employees_without_plan_hours() == []

    # Naar Huis później liczy od poprawionych godzin
    assert db.leave_work_in_db([a], "home", "20:00") == []
    assert _emp(a).work_hours == "15:00-20:00"

    db.undo_last()
    db.undo_last()
    assert _emp(a).work_hours == "00:00-00:00"


def test_wrong_hours_are_refused(temp_db):
    a = make_employee("Nowak", "Ewa", work_hours="00:00-00:00", shift="Middag", computed_hours=0)
    errors = db.set_plan_hours_in_db({a: "15:00"})
    assert errors and "Nowak" in errors[0]
    assert _emp(a).work_hours == "00:00-00:00"


def test_dialog_proposes_shift_hours_and_returns_ticked(temp_db, qtbot=None):
    from PySide6.QtWidgets import QApplication
    from pm.dialogs import PlanHoursDialog

    QApplication.instance() or QApplication([])
    rows = [(1, "Nowak", "Ewa", "Laco", "Middag"), (2, "Dijk", "Piet", "Inbound 1", "Ochtend")]
    dlg = PlanHoursDialog(rows)
    assert [e.text() for e in dlg.edits] == ["15:00-00:00", "06:00-15:00"]
    assert dlg.changes() == {}
    dlg.edits[1].setText("07:00-15:00")
    dlg.boxes[1].setChecked(True)
    assert dlg.changes() == {2: "07:00-15:00"}
