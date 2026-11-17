"""Logika biznesowa: czas pracy, przerwy, nazwiska, model pracownika (bez Qt i bez bazy)."""
from .config import (
    DAY8TO17_BREAKS,
    LASTNAME_CORRECTIONS,
    MIDDAG_BREAKS,
    NAME_EXCEPTIONS,
    OCHTEND_BREAKS,
    SPECIAL_FUNCTIONS,
)


class Validator:
    @staticmethod
    def validate_time_format(time_str):
        try:
            hh, mm = time_str.split(":")
            hh = int(hh)
            mm = int(mm)
            return 0 <= hh < 24 and 0 <= mm < 60
        except Exception:
            return False


def to_minutes(hhmm):
    if not Validator.validate_time_format(hhmm):
        return 0
    hh, mm = hhmm.split(":")
    return int(hh) * 60 + int(mm)


def compute_hours_with_breaks(work_hours, shift, custom_breaks=None):
    if not isinstance(work_hours, str) or "-" not in work_hours:
        return 0.0

    parts = work_hours.split("-")
    if len(parts) != 2:
        return 0.0

    start_str, end_str = parts
    start = to_minutes(start_str.strip())
    end = to_minutes(end_str.strip())

    if end < start:
        end += 24 * 60

    total = end - start
    breaks = []

    if shift == "Ochtend":
        breaks = OCHTEND_BREAKS
    elif shift == "Middag":
        breaks = MIDDAG_BREAKS
    elif shift == "Day8to17":
        breaks = DAY8TO17_BREAKS
    elif shift == "Custom" and custom_breaks:
        breaks = custom_breaks

    for b_start, b_end in breaks:
        if b_start < end and b_end > start:
            total -= max(0, min(end, b_end) - max(start, b_start))

    total = max(0, total)
    return round((total / 60.0) * 4) / 4.0


def interval_hours_with_breaks(s, e, shift):
    if e < s:
        e += 24 * 60
    return compute_hours_with_breaks(f"{s // 60:02d}:{s % 60:02d}-{e // 60:02d}:{e % 60:02d}", shift)


def format_name(name):
    words = name.split()
    formatted = []

    for word in words:
        lower_word = word.lower()
        if lower_word not in NAME_EXCEPTIONS:
            formatted.append(word.capitalize())
        else:
            formatted.append(lower_word)

    return " ".join(formatted)


def round_to_quarter(x):
    return round(x * 4) / 4


def move_lastname_prefix_to_firstname(lastname, firstname):
    corrected = LASTNAME_CORRECTIONS.get(lastname.lower())
    if corrected:
        return corrected, firstname

    lastname_parts = lastname.split()
    firstname = firstname.strip()

    if len(lastname_parts) > 1 and " ".join(lastname_parts[:2]).lower() == "vas dos":
        return lastname, firstname

    for i, part in enumerate(lastname_parts):
        if part.lower() in NAME_EXCEPTIONS:
            prefix = " ".join(lastname_parts[:i + 1])
            remaining_lastname = " ".join(lastname_parts[i + 1:])

            if remaining_lastname:
                new_firstname = f"{firstname} {prefix}".strip()
                return remaining_lastname, new_firstname

            break

    return lastname, firstname


def adjust_work_hours(work_hours, department=None):
    if not isinstance(work_hours, str) or "-" not in work_hours:
        return work_hours

    start, end = work_hours.split("-")
    start = start.strip()
    end = end.strip()

    if department == "Logistiek coördinator":
        if start < "12:00":
            start = "05:30"
            end = "15:00"
        else:
            start = "14:30"
            end = "00:00"
    elif department in SPECIAL_FUNCTIONS:
        if start in ["06:00", "05:30"]:
            start = "05:45"
        elif start in ["15:00", "14:30"]:
            start = "14:45"
    else:
        if start in ["05:30", "05:45"]:
            start = "06:00"
        elif start in ["14:30", "14:45"]:
            start = "15:00"

    if start in ["14:30", "14:45"]:
        end = "00:00"

    return f"{start}-{end}"


def get_scheduled_start_time(emp):
    if not emp.work_hours or "-" not in emp.work_hours:
        return None

    start_str, _ = emp.work_hours.split("-")
    return start_str.strip()


def serialize_breaks(breaks):
    """[(480, 495), ...] -> '08:00-08:15;...' (do zapisu w bazie)."""
    return ";".join(
        f"{s // 60:02d}:{s % 60:02d}-{e // 60:02d}:{e % 60:02d}" for s, e in (breaks or [])
    )


def parse_breaks(text):
    """'08:00-08:15;...' -> [(480, 495), ...]; błędne wpisy są pomijane."""
    result = []
    for part in (text or "").split(";"):
        if "-" not in part:
            continue
        start, end = part.split("-", 1)
        if Validator.validate_time_format(start.strip()) and Validator.validate_time_format(end.strip()):
            result.append((to_minutes(start.strip()), to_minutes(end.strip())))
    return result


class Employee:
    def __init__(
        self,
        employee_id,
        lastname,
        firstname,
        current_department,
        work_hours,
        shift,
        computed_hours,
        marked,
        info,
        custom_breaks=None,
        late=False,
        position=""
    ):
        self.employee_id = employee_id
        self.lastname = lastname
        self.firstname = firstname
        self.current_department = current_department
        self.work_hours = work_hours
        self.original_work_hours = work_hours
        self.shift = shift
        self.computed_hours = str(computed_hours)
        self.marked = bool(marked)
        self.info = info or ""
        self.custom_breaks = custom_breaks if custom_breaks else []
        self.late = bool(late)
        self.position = position or ""  # klient / strefa w Monitoringu
        self._dept_ui = [""] * 10
        self.dept_intervals = []
        self.dept_times = [(current_department, "")]

    def edit_current_department(self, new_dept):
        if self.dept_times:
            first_time_assigned = self.dept_times[0][1]
            self.dept_times[0] = (new_dept, first_time_assigned)

        self.work_hours = adjust_work_hours(self.work_hours, new_dept)
        self.current_department = new_dept
        self.recalc_intervals_and_hours()

    def recalc_intervals_and_hours(self):
        if not self.dept_times or not isinstance(self.work_hours, str) or "-" not in self.work_hours:
            self.dept_intervals = []
            self.computed_hours = "0.00"
            self._build_dept_ui()
            return

        start_str, end_str = self.work_hours.split("-")
        start_str = start_str.strip()
        end_str = end_str.strip()

        if not (Validator.validate_time_format(start_str) and Validator.validate_time_format(end_str)):
            self.dept_intervals = []
            self.computed_hours = "0.00"
            self._build_dept_ui()
            return

        start_min = to_minutes(start_str)
        end_min = to_minutes(end_str)

        if end_min < start_min:
            end_min += 24 * 60

        times = []

        for dept, time_assigned in self.dept_times:
            dept = dept.strip()

            if time_assigned and Validator.validate_time_format(time_assigned):
                t = to_minutes(time_assigned.strip())
                if t < start_min:
                    t += 24 * 60
                times.append((t, dept))
            else:
                times.append((start_min, dept))

        times.append((end_min, ""))

        total_hours = 0.0
        dept_hours = {}
        dept_order = []

        for i in range(len(times) - 1):
            start, dept_name = times[i]
            end, _ = times[i + 1]

            if dept_name.lower() in ["ziek", "naar huis"]:
                duration = 0.0
            else:
                if self.shift == "Custom":
                    duration = compute_hours_with_breaks(
                        f"{start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d}",
                        "Custom",
                        self.custom_breaks
                    )
                else:
                    duration = interval_hours_with_breaks(start, end, self.shift)

            total_hours += duration

            if dept_name and dept_name.lower() not in ["ziek", "naar huis"]:
                if dept_name not in dept_hours:
                    dept_hours[dept_name] = 0.0
                    dept_order.append(dept_name)

                dept_hours[dept_name] += duration

        self.computed_hours = f"{total_hours:.2f}"
        self.dept_intervals = [(dept, dept_hours[dept]) for dept in dept_order]
        self._build_dept_ui()

    @property
    def active_department(self):
        """Dział, w którym pracownik jest teraz (ostatni wpis)."""
        return self.dept_times[-1][0].strip() if self.dept_times else self.current_department

    @property
    def active_since(self):
        """Godzina ostatniej zmiany działu ('' = od początku pracy)."""
        return self.dept_times[-1][1].strip() if self.dept_times else ""

    @property
    def status(self):
        """'sick' / 'home' / 'late' / '' – do kolorowania wiersza."""
        last = self.dept_times[-1][0].strip().lower() if self.dept_times else ""
        if last == "ziek":
            return "sick"
        if last == "naar huis":
            return "home"
        return "late" if self.late else ""

    def to_ui_values(self):
        marked_symbol = "✅" if self.marked else ""
        return [
            marked_symbol, self.lastname, self.firstname, self.work_hours, self.computed_hours,
            *self._dept_ui, self.info,
        ]

    def _build_dept_ui(self):
        # Liczone raz po przeliczeniu godzin, a nie przy każdej komórce tabeli.
        ui = []
        max_depts = 5

        for dept, duration in self.dept_intervals[:max_depts]:
            ui.append(dept)

            if dept == "Consolidatie/Kantelen":
                part1 = round_to_quarter(duration * 0.25)
                part2 = round_to_quarter(duration * 0.75)
                ui.append(f"{part1:.2f}/{part2:.2f}")
            else:
                ui.append(f"{duration:.2f}")

        for _ in range(max_depts - len(self.dept_intervals)):
            ui.append("")
            ui.append("")

        self._dept_ui = ui
