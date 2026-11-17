from pm.logic import (
    Employee,
    Validator,
    adjust_work_hours,
    compute_hours_with_breaks,
    format_name,
    move_lastname_prefix_to_firstname,
    parse_breaks,
    round_to_quarter,
    serialize_breaks,
    to_minutes,
)


def test_time_validation():
    assert Validator.validate_time_format("06:00")
    assert Validator.validate_time_format("23:59")
    assert not Validator.validate_time_format("24:00")
    assert not Validator.validate_time_format("abc")
    assert to_minutes("06:30") == 390
    assert to_minutes("bad") == 0


def test_standard_shifts_are_8_hours():
    # 9 h obecności minus 1 h przerw
    assert compute_hours_with_breaks("06:00-15:00", "Ochtend") == 8.0
    assert compute_hours_with_breaks("15:00-00:00", "Middag") == 8.0
    assert compute_hours_with_breaks("08:00-17:00", "Day8to17") == 8.0


def test_custom_breaks_are_subtracted():
    assert compute_hours_with_breaks("08:00-17:00", "Custom", [(720, 750)]) == 8.5
    assert compute_hours_with_breaks("08:00-17:00", "Custom") == 9.0


def test_invalid_hours_give_zero():
    assert compute_hours_with_breaks(None, "Ochtend") == 0.0
    assert compute_hours_with_breaks("0600", "Ochtend") == 0.0


def test_rounding_to_quarter():
    assert round_to_quarter(1.1) == 1.0
    assert round_to_quarter(1.13) == 1.25


def test_breaks_roundtrip():
    breaks = [(480, 495), (720, 750)]
    assert serialize_breaks(breaks) == "08:00-08:15;12:00-12:30"
    assert parse_breaks(serialize_breaks(breaks)) == breaks
    assert parse_breaks("") == []
    assert parse_breaks("rubbish;12:00-12:30") == [(720, 750)]


def test_name_formatting():
    assert format_name("JAN van DIJK") == "Jan van Dijk"
    assert move_lastname_prefix_to_firstname("van Dijk", "Jan") == ("Dijk", "Jan van")
    assert move_lastname_prefix_to_firstname("Kowalski", "Jan") == ("Kowalski", "Jan")


def test_adjust_work_hours():
    assert adjust_work_hours("05:45-15:00", "Buffer") == "06:00-15:00"
    assert adjust_work_hours("06:00-15:00", "Shiftleader") == "05:45-15:00"
    assert adjust_work_hours("06:00-15:00", "Logistiek coördinator") == "05:30-15:00"
    assert adjust_work_hours("15:00-00:00", "Logistiek coördinator") == "14:30-00:00"


def _employee(dept_times, work_hours="06:00-15:00", shift="Ochtend", **kwargs):
    emp = Employee(1, "Test", "Anna", dept_times[0][0], work_hours, shift, 0, 0, "", **kwargs)
    emp.dept_times = dept_times
    emp.recalc_intervals_and_hours()
    return emp


def test_hours_split_between_departments():
    emp = _employee([("Buffer", ""), ("Reachtruck", "10:00")])
    assert dict(emp.dept_intervals) == {"Buffer": 3.75, "Reachtruck": 4.25}
    assert emp.computed_hours == "8.00"


def test_sick_counts_as_zero():
    emp = _employee([("Buffer", ""), ("Ziek", "10:00")])
    assert dict(emp.dept_intervals) == {"Buffer": 3.75}
    assert emp.computed_hours == "3.75"
    assert emp.status == "sick"


def test_status_home_and_late():
    assert _employee([("Buffer", ""), ("Naar Huis", "12:00")]).status == "home"
    assert _employee([("Buffer", "")], late=True).status == "late"
    assert _employee([("Buffer", "")]).status == ""


def test_ui_values_layout():
    emp = _employee([("Consolidatie/Kantelen", "")])
    values = emp.to_ui_values()
    assert len(values) == 16
    assert values[5] == "Consolidatie/Kantelen"
    assert values[6] == "2.00/6.00"  # podział 25% / 75%
