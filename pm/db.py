"""Dostęp do bazy SQLite: pracownicy, działy, dziennik zmian, cofanie, kopie zapasowe.

Każda operacja zmieniająca dane zapisuje wpis w tabeli change_log. Wpis może
zawierać „migawkę" stanu sprzed zmiany (undo_data) – dzięki niej działa Cofnij.
"""
import getpass
import glob
import json
import os
import sqlite3
from datetime import datetime

from . import config
from .excel_io import read_logins_excel, read_planning_excel
from .logic import (
    Employee,
    Validator,
    join_positions,
    move_lastname_prefix_to_firstname,
    name_key,
    parse_breaks,
    serialize_breaks,
    to_minutes,
)

EMP_COLS = (
    "id, lastname, firstname, current_department, work_hours, shift, "
    "computed_hours, marked, info, custom_breaks, late, position"
)

try:
    USER = getpass.getuser()
except Exception:
    USER = "unknown"


###############################################################################
# Connection / schema
###############################################################################

def get_connection():
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lastname TEXT NOT NULL,
            firstname TEXT NOT NULL,
            current_department TEXT NOT NULL,
            work_hours TEXT NOT NULL,
            shift TEXT NOT NULL,
            computed_hours REAL NOT NULL,
            marked INTEGER DEFAULT 0,
            info TEXT DEFAULT '',
            custom_breaks TEXT DEFAULT '',
            late INTEGER DEFAULT 0,
            position TEXT DEFAULT ''
        )
    """)

    # Migracje starszych baz (kolumny lock_* ze starych wersji zostają, ale nie są używane).
    cursor.execute("PRAGMA table_info(employees)")
    columns_db = [col[1] for col in cursor.fetchall()]

    for name, definition in (
        ("marked", "INTEGER DEFAULT 0"),
        ("info", "TEXT DEFAULT ''"),
        ("custom_breaks", "TEXT DEFAULT ''"),
        ("late", "INTEGER DEFAULT 0"),
        ("position", "TEXT DEFAULT ''"),
    ):
        if name not in columns_db:
            cursor.execute(f"ALTER TABLE employees ADD COLUMN {name} {definition}")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            department TEXT NOT NULL,
            time_assigned TEXT NOT NULL,
            FOREIGN KEY (employee_id) REFERENCES employees (id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS change_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            user TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT DEFAULT '',
            undo_data TEXT,
            undone INTEGER DEFAULT 0
        )
    """)

    # Loginy trzymamy osobno, po nazwisku – przeżywają "Clear Data" i kolejne importy planu.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS logins (
            name_key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            login TEXT NOT NULL
        )
    """)

    # Starsze wersje traktowały „Nanomi Reachtruck" jako osobny dział – teraz to Reach ze strefą Na-Nomi.
    for old_name, (new_dept, new_position) in config.DEPARTMENT_AS_POSITION.items():
        cursor.execute("""
            UPDATE employees SET position = ?
            WHERE lower(current_department) = ? AND (position IS NULL OR position = '')
        """, (new_position, old_name))
        cursor.execute(
            "UPDATE employees SET current_department = ? WHERE lower(current_department) = ?",
            (new_dept, old_name),
        )
        cursor.execute(
            "UPDATE departments SET department = ? WHERE lower(department) = ?",
            (new_dept, old_name),
        )

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_departments_employee_id ON departments(employee_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_employees_name ON employees(lastname, firstname)")

    conn.commit()
    conn.close()


###############################################################################
# Backups / archive
###############################################################################

def _copy_db_to(folder, prefix):
    """Bezpieczna kopia bazy (API backup SQLite). Zwraca ścieżkę kopii."""
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    target = os.path.join(folder, f"{prefix}_{stamp}.db")

    src = get_connection()
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def _has_employees():
    conn = get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] > 0
    finally:
        conn.close()


def backup_db():
    """Kopia przy starcie aplikacji; trzymamy BACKUP_KEEP ostatnich. Błędy nie blokują startu."""
    try:
        if not os.path.exists(config.DB_PATH) or not _has_employees():
            return None

        target = _copy_db_to(config.BACKUP_DIR, "planning_backup")

        old = sorted(glob.glob(os.path.join(config.BACKUP_DIR, "planning_backup_*.db")))
        for path in old[:-config.BACKUP_KEEP]:
            try:
                os.remove(path)
            except OSError:
                pass
        return target
    except Exception:
        return None


###############################################################################
# Change log / undo
###############################################################################

def _names(cursor, employee_ids, limit=5):
    names = []
    for emp_id in list(employee_ids)[:limit]:
        row = cursor.execute("SELECT lastname, firstname FROM employees WHERE id = ?", (emp_id,)).fetchone()
        if row:
            names.append(f"{row[0]} {row[1]}")
    extra = len(employee_ids) - limit
    if extra > 0:
        names.append(f"+{extra} more")
    return ", ".join(names)


def _snapshot(cursor, employee_ids):
    """Stan pracowników (wiersz + działy) sprzed zmiany – do Cofnij."""
    snap = []
    for emp_id in employee_ids:
        row = cursor.execute(f"SELECT {EMP_COLS} FROM employees WHERE id = ?", (emp_id,)).fetchone()
        if row is None:
            continue
        depts = cursor.execute(
            "SELECT department, time_assigned FROM departments WHERE employee_id = ? ORDER BY id ASC",
            (emp_id,),
        ).fetchall()
        snap.append({"row": list(row), "departments": [list(d) for d in depts]})
    return snap


def _record(cursor, action, details="", restore=None, delete_ids=None):
    """Wpis do dziennika. restore = migawka do przywrócenia, delete_ids = id utworzone przez operację."""
    undo = None
    if restore or delete_ids:
        undo = json.dumps({"restore": restore or [], "delete_ids": list(delete_ids or [])})

    cursor.execute(
        "INSERT INTO change_log (ts, user, action, details, undo_data) VALUES (?, ?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), USER, action, details, undo),
    )

    # Migawki trzymamy tylko dla ostatnich UNDO_DEPTH operacji, wpisy – dla LOG_KEEP.
    cursor.execute("""
        UPDATE change_log SET undo_data = NULL
        WHERE undo_data IS NOT NULL AND id NOT IN (
            SELECT id FROM change_log WHERE undo_data IS NOT NULL ORDER BY id DESC LIMIT ?
        )
    """, (config.UNDO_DEPTH,))
    cursor.execute(
        "DELETE FROM change_log WHERE id <= (SELECT MAX(id) FROM change_log) - ?",
        (config.LOG_KEEP,),
    )


def undo_last():
    """Cofa ostatnią operację, którą da się cofnąć. Zwraca jej opis albo None."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        entry = cursor.execute("""
            SELECT id, action, details, undo_data FROM change_log
            WHERE undo_data IS NOT NULL AND undone = 0
            ORDER BY id DESC LIMIT 1
        """).fetchone()

        if entry is None:
            return None

        entry_id, action, details, undo_data = entry
        data = json.loads(undo_data)

        for emp_id in data.get("delete_ids", []):
            cursor.execute("DELETE FROM departments WHERE employee_id = ?", (emp_id,))
            cursor.execute("DELETE FROM employees WHERE id = ?", (emp_id,))

        all_cols = [c.strip() for c in EMP_COLS.split(",")]
        for item in data.get("restore", []):
            emp_id = item["row"][0]
            # migawka ze starszej wersji może mieć mniej kolumn
            cols = all_cols[:len(item["row"])]
            cursor.execute("DELETE FROM departments WHERE employee_id = ?", (emp_id,))
            cursor.execute("DELETE FROM employees WHERE id = ?", (emp_id,))
            cursor.execute(
                f"INSERT INTO employees ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                item["row"][:len(cols)],
            )
            for dept, time_assigned in item["departments"]:
                cursor.execute(
                    "INSERT INTO departments (employee_id, department, time_assigned) VALUES (?, ?, ?)",
                    (emp_id, dept, time_assigned),
                )

        cursor.execute("UPDATE change_log SET undone = 1, undo_data = NULL WHERE id = ?", (entry_id,))
        description = f"{action}: {details}" if details else action
        _record(cursor, "Undo", description)

        conn.commit()
        return description
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def load_change_log(limit=500):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT ts, user, action, details, undone FROM change_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()


###############################################################################
# Loading
###############################################################################

def _employee_from_row(cursor, row):
    emp = Employee(*row[:9], custom_breaks=parse_breaks(row[9]), late=row[10], position=row[11])

    cursor.execute("""
        SELECT department, time_assigned
        FROM departments
        WHERE employee_id = ?
        ORDER BY id ASC
    """, (emp.employee_id,))

    emp.dept_times = [(d, t) for d, t in cursor.fetchall()]
    emp.recalc_intervals_and_hours()
    return emp


def load_employees_from_db():
    conn = get_connection()
    cursor = conn.cursor()

    rows = cursor.execute(f"SELECT {EMP_COLS} FROM employees").fetchall()
    result = [_employee_from_row(cursor, row) for row in rows]

    logins = dict(cursor.execute("SELECT name_key, login FROM logins").fetchall())
    if logins:
        for emp in result:
            emp.login = logins.get(name_key(emp.firstname, emp.lastname), "")

    conn.close()
    return result


def load_employee_by_id(cursor, emp_id):
    row = cursor.execute(f"SELECT {EMP_COLS} FROM employees WHERE id = ?", (emp_id,)).fetchone()
    if row is None:
        return None
    return _employee_from_row(cursor, row)


###############################################################################
# Employees
###############################################################################

def insert_employee_to_db(data):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO employees (
            lastname, firstname, current_department, work_hours, shift, computed_hours, marked, info,
            custom_breaks
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["lastname"],
        data["firstname"],
        data["department"],
        data["work_hours"],
        data["shift"],
        data["computed_hours"],
        0,
        data.get("info", ""),
        serialize_breaks(data.get("custom_breaks")),
    ))

    employee_id = cursor.lastrowid

    cursor.execute("""
        INSERT INTO departments (employee_id, department, time_assigned)
        VALUES (?, ?, ?)
    """, (employee_id, data["department"], ""))

    _record(
        cursor, "Add employee",
        f"{data['lastname']} {data['firstname']} ({data['department']}, {data['work_hours']})",
        delete_ids=[employee_id],
    )

    conn.commit()
    conn.close()
    return employee_id


def delete_employees_from_db(employee_ids):
    conn = get_connection()
    cursor = conn.cursor()

    _record(cursor, "Remove employee", _names(cursor, employee_ids), restore=_snapshot(cursor, employee_ids))

    for emp_id in employee_ids:
        cursor.execute("DELETE FROM departments WHERE employee_id = ?", (emp_id,))
        cursor.execute("DELETE FROM employees WHERE id = ?", (emp_id,))

    conn.commit()
    conn.close()


def clear_all_data_in_db():
    """Archiwizuje bazę do pliku, a potem czyści listę. Zwraca ścieżkę archiwum (albo None)."""
    archive_path = None
    if _has_employees():
        archive_path = _copy_db_to(config.ARCHIVE_DIR, "planning_archive")

    conn = get_connection()
    cursor = conn.cursor()

    all_ids = [r[0] for r in cursor.execute("SELECT id FROM employees").fetchall()]
    _record(
        cursor, "Clear data",
        f"{len(all_ids)} employees" + (f", archive: {os.path.basename(archive_path)}" if archive_path else ""),
        restore=_snapshot(cursor, all_ids),
    )

    cursor.execute("DELETE FROM departments")
    cursor.execute("DELETE FROM employees")
    conn.commit()
    conn.close()
    return archive_path


def update_employee_info_in_db(emp_id, info):
    conn = get_connection()
    cursor = conn.cursor()
    _record(cursor, "Edit info", f"{_names(cursor, [emp_id])}: {info}", restore=_snapshot(cursor, [emp_id]))
    cursor.execute("UPDATE employees SET info = ? WHERE id = ?", (info, emp_id))
    conn.commit()
    conn.close()


def toggle_employee_marked_in_db(emp_id, marked):
    # Znacznik to tylko pomoc wizualna – nie trafia do dziennika ani do Cofnij.
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE employees SET marked = ? WHERE id = ?", (1 if marked else 0, emp_id))
    conn.commit()
    conn.close()


###############################################################################
# Departments
###############################################################################

def _validate_time_in_order(emp, time_chosen):
    """Nowa godzina nie może być wcześniejsza niż poprzednia zmiana działu
    (ani początek pracy) i nie może wypadać po końcu pracy."""
    if not isinstance(emp.work_hours, str) or "-" not in emp.work_hours:
        return

    start_str, end_str = (p.strip() for p in emp.work_hours.split("-", 1))
    if not (Validator.validate_time_format(start_str) and Validator.validate_time_format(end_str)):
        return

    start_min = to_minutes(start_str)
    end_min = to_minutes(end_str)
    if end_min < start_min:
        return  # zmiana przechodząca przez północ: nie sprawdzamy

    new_min = to_minutes(time_chosen)
    previous = start_min
    for _, t in emp.dept_times:
        if t and Validator.validate_time_format(t):
            previous = max(previous, to_minutes(t))

    if new_min < previous:
        raise ValueError(
            f"Time {time_chosen} is earlier than the previous change "
            f"({previous // 60:02d}:{previous % 60:02d})."
        )
    if new_min > end_min:
        raise ValueError(f"Time {time_chosen} is after the end of work ({end_str}).")


def _apply_add_department(cursor, emp, dept_chosen, time_chosen, position=""):
    """Dodaje jednej osobie nowy dział od podanej godziny (rzuca ValueError, gdy się nie da)."""
    emp_id = emp.employee_id

    distinct = {d for d, _ in emp.dept_times}
    if dept_chosen not in distinct and len(distinct) >= 5:
        raise ValueError("Cannot have more than 5 different departments.")

    _validate_time_in_order(emp, time_chosen)

    emp.dept_times.append((dept_chosen, time_chosen))

    cursor.execute("""
        INSERT INTO departments (employee_id, department, time_assigned)
        VALUES (?, ?, ?)
    """, (emp_id, dept_chosen, time_chosen))

    if dept_chosen.lower() == "naar huis":
        # Świadoma decyzja: pójście do domu skraca godziny pracy.
        start = emp.original_work_hours.split("-")[0].strip()
        emp.work_hours = f"{start}-{time_chosen}"

    emp.recalc_intervals_and_hours()
    cursor.execute("""
        UPDATE employees
        SET work_hours = ?, computed_hours = ?, marked = 0, position = ?
        WHERE id = ?
    """, (emp.work_hours, emp.computed_hours, position, emp_id))


def add_departments_to_db(employee_ids, dept_chosen, time_chosen):
    if not Validator.validate_time_format(time_chosen):
        raise ValueError("Invalid time format.")

    conn = get_connection()
    cursor = conn.cursor()
    errors = []
    changed = []
    snapshot = _snapshot(cursor, employee_ids)

    for emp_id in employee_ids:
        emp = load_employee_by_id(cursor, emp_id)
        if emp is None:
            errors.append(f"Employee ID {emp_id}: not found.")
            continue

        try:
            _apply_add_department(cursor, emp, dept_chosen, time_chosen)
            changed.append(emp_id)

        except ValueError as exc:
            errors.append(f"{emp.lastname} {emp.firstname}: {exc}")

    if changed:
        _record(
            cursor, "Add department",
            f"{dept_chosen} @ {time_chosen}: {_names(cursor, changed)}",
            restore=[s for s in snapshot if s["row"][0] in changed],
        )

    conn.commit()
    conn.close()
    return errors


def remove_last_departments_from_db(employee_ids):
    conn = get_connection()
    cursor = conn.cursor()
    errors = []
    changed = []
    snapshot = _snapshot(cursor, employee_ids)

    for emp_id in employee_ids:
        emp = load_employee_by_id(cursor, emp_id)
        if emp is None:
            errors.append(f"Employee ID {emp_id}: not found.")
            continue

        if len(emp.dept_times) <= 1:
            errors.append(f"{emp.lastname} {emp.firstname}: No additional departments to remove.")
            continue

        last_dept = emp.dept_times[-1][0]

        cursor.execute("""
            DELETE FROM departments
            WHERE id = (
                SELECT id
                FROM departments
                WHERE employee_id = ? AND department = ?
                ORDER BY id DESC
                LIMIT 1
            )
        """, (emp_id, last_dept))

        emp.dept_times.pop()
        emp.recalc_intervals_and_hours()

        cursor.execute("""
            UPDATE employees
            SET computed_hours = ?, position = ''
            WHERE id = ?
        """, (emp.computed_hours, emp_id))
        changed.append(emp_id)

    if changed:
        _record(
            cursor, "Remove department", _names(cursor, changed),
            restore=[s for s in snapshot if s["row"][0] in changed],
        )

    conn.commit()
    conn.close()
    return errors


def edit_departments_in_db(employee_ids, new_dept):
    conn = get_connection()
    cursor = conn.cursor()

    _record(
        cursor, "Edit department", f"-> {new_dept}: {_names(cursor, employee_ids)}",
        restore=_snapshot(cursor, employee_ids),
    )

    for emp_id in employee_ids:
        emp = load_employee_by_id(cursor, emp_id)
        if emp is None:
            continue

        emp.edit_current_department(new_dept)

        cursor.execute("""
            UPDATE employees
            SET current_department = ?, work_hours = ?, computed_hours = ?, position = ''
            WHERE id = ?
        """, (emp.current_department, emp.work_hours, emp.computed_hours, emp_id))

        cursor.execute("""
            UPDATE departments
            SET department = ?
            WHERE employee_id = ? AND time_assigned = ''
        """, (new_dept, emp_id))

    conn.commit()
    conn.close()


def move_employees_in_db(employee_ids, dept, position="", time_chosen=None, from_position="", add=False):
    """Przeniesienie w widoku Monitoring (upuszczenie kostki na dział / pozycję).

    - ten sam dział, inna pozycja  -> zmienia się tylko pozycja (godziny bez zmian);
      add=True dokłada pozycję do już posiadanych (praca w kilku strefach naraz),
      inaczej pozycja from_position jest zamieniana na nową,
    - przed początkiem pracy       -> zmienia się dział początkowy (jak Edit Department),
    - w trakcie pracy              -> nowy wpis działu od teraz (jak Add Department).
    Zwraca listę błędów.
    """
    if time_chosen is None:
        time_chosen = datetime.now().strftime("%H:%M")
    if not Validator.validate_time_format(time_chosen):
        raise ValueError("Invalid time format.")

    conn = get_connection()
    cursor = conn.cursor()
    errors = []
    changed = []
    snapshot = _snapshot(cursor, employee_ids)
    now_min = to_minutes(time_chosen)

    for emp_id in employee_ids:
        emp = load_employee_by_id(cursor, emp_id)
        if emp is None:
            errors.append(f"Employee ID {emp_id}: not found.")
            continue

        label = f"{emp.lastname} {emp.firstname}"
        current = emp.active_department

        try:
            if current.lower() == "naar huis":
                raise ValueError("Already went home.")

            if current == dept:
                positions = emp.positions
                if add:
                    new_positions = positions + [position]
                else:
                    new_positions = [p for p in positions if p != from_position] + [position]
                new_value = join_positions(new_positions)
                if new_value == join_positions(positions):
                    continue
                cursor.execute("UPDATE employees SET position = ? WHERE id = ?", (new_value, emp_id))
                changed.append(emp_id)
                continue

            start_min = end_min = None
            if isinstance(emp.work_hours, str) and "-" in emp.work_hours:
                start_str, end_str = (p.strip() for p in emp.work_hours.split("-", 1))
                if Validator.validate_time_format(start_str) and Validator.validate_time_format(end_str):
                    start_min, end_min = to_minutes(start_str), to_minutes(end_str)

            before_start = (
                start_min is not None and end_min >= start_min and now_min < start_min
                and len(emp.dept_times) == 1 and dept.lower() != "naar huis"
            )

            if before_start:
                # Układanie obsady przed zmianą: podmieniamy dział początkowy.
                emp.edit_current_department(dept)
                cursor.execute("""
                    UPDATE employees
                    SET current_department = ?, work_hours = ?, computed_hours = ?, position = ?
                    WHERE id = ?
                """, (emp.current_department, emp.work_hours, emp.computed_hours, position, emp_id))
                cursor.execute("""
                    UPDATE departments
                    SET department = ?
                    WHERE employee_id = ? AND time_assigned = ''
                """, (dept, emp_id))
            else:
                _apply_add_department(cursor, emp, dept, time_chosen, position)

            changed.append(emp_id)

        except ValueError as exc:
            errors.append(f"{label}: {exc}")

    if changed:
        target = f"{dept} / {position}" if position else dept
        if add and position:
            target += " (added)"
        _record(
            cursor, "Move",
            f"-> {target} @ {time_chosen}: {_names(cursor, changed)}",
            restore=[s for s in snapshot if s["row"][0] in changed],
        )

    conn.commit()
    conn.close()
    return errors


def toggle_position_in_db(emp_id, position):
    """Włącza / wyłącza jedną pozycję (klienta, strefę) u pracownika. Godzin nie zmienia."""
    conn = get_connection()
    cursor = conn.cursor()

    emp = load_employee_by_id(cursor, emp_id)
    if emp is None:
        conn.close()
        raise ValueError("Employee not found.")

    positions = emp.positions
    if position in positions:
        positions.remove(position)
        verb = "removed"
    else:
        positions.append(position)
        verb = "added"

    _record(
        cursor, "Position",
        f"{emp.lastname} {emp.firstname}: {position} {verb}",
        restore=_snapshot(cursor, [emp_id]),
    )
    cursor.execute("UPDATE employees SET position = ? WHERE id = ?", (join_positions(positions), emp_id))

    conn.commit()
    conn.close()


def import_logins_from_excel(filepath):
    """Wczytuje spis loginów. Zwraca (liczba loginów, ilu obecnych pracowników dopasowano)."""
    pairs = read_logins_excel(filepath)

    conn = get_connection()
    cursor = conn.cursor()
    try:
        for name, login in pairs:
            cursor.execute(
                "INSERT OR REPLACE INTO logins (name_key, name, login) VALUES (?, ?, ?)",
                (name_key(name), name, login),
            )

        known = {r[0] for r in cursor.execute("SELECT name_key FROM logins").fetchall()}
        people = cursor.execute("SELECT firstname, lastname FROM employees").fetchall()
        matched = sum(1 for first, last in people if name_key(first, last) in known)

        _record(cursor, "Import logins", f"{len(pairs)} logins, {matched} of {len(people)} employees matched")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return len(pairs), matched, len(people)


def mark_employees_late_in_db(items):
    """items: lista (emp_id, actual_start). Jedna transakcja dla wszystkich; zwraca listę błędów."""
    conn = get_connection()
    cursor = conn.cursor()
    errors = []
    changed = []
    snapshot = _snapshot(cursor, [emp_id for emp_id, _ in items])

    for emp_id, actual_start in items:
        emp = load_employee_by_id(cursor, emp_id)
        if emp is None:
            errors.append(f"Employee ID {emp_id}: not found.")
            continue

        label = f"{emp.lastname} {emp.firstname}"

        if not Validator.validate_time_format(actual_start):
            errors.append(f"{label}: Invalid time format. Please use HH:MM.")
            continue

        if not emp.work_hours or "-" not in emp.work_hours:
            errors.append(f"{label}: Original work hours not set.")
            continue

        old_end_str = emp.work_hours.split("-", 1)[1].strip()
        emp.work_hours = f"{actual_start}-{old_end_str}"
        emp.recalc_intervals_and_hours()

        cursor.execute("""
            UPDATE employees
            SET work_hours = ?, computed_hours = ?, late = 1
            WHERE id = ?
        """, (emp.work_hours, emp.computed_hours, emp_id))
        changed.append((emp_id, actual_start, label))

    if changed:
        ids = [c[0] for c in changed]
        _record(
            cursor, "Late",
            ", ".join(f"{label} @ {start}" for _, start, label in changed[:5])
            + (f", +{len(changed) - 5} more" if len(changed) > 5 else ""),
            restore=[s for s in snapshot if s["row"][0] in ids],
        )

    conn.commit()
    conn.close()
    return errors


###############################################################################
# Excel import
###############################################################################

def import_excel_to_db(filepaths):
    """Zwraca (zaimportowane, pominięte duplikaty). Wszystko albo nic."""
    if not filepaths:
        return 0, 0, []

    employees_df = read_planning_excel(filepaths)

    conn = get_connection()
    cursor = conn.cursor()

    count = 0
    skipped = 0
    created_ids = []

    try:
        # Pomijamy osoby już obecne w bazie (to samo imię, nazwisko, dział, godziny, zmiana).
        cursor.execute("SELECT lastname, firstname, current_department, work_hours, shift FROM employees")
        seen = {tuple(r) for r in cursor.fetchall()}

        for _, row_ in employees_df.iterrows():
            lastname, firstname = move_lastname_prefix_to_firstname(row_["lastname"], row_["firstname"])

            key = (lastname, firstname, row_["current_department"], row_["work_hours"], row_["shift"])
            position = row_.get("position", "") or ""
            if key in seen:
                skipped += 1
                continue
            seen.add(key)

            cursor.execute("""
                INSERT INTO employees (
                    lastname, firstname, current_department, work_hours, shift, computed_hours, marked, position
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                lastname,
                firstname,
                row_["current_department"],
                row_["work_hours"],
                row_["shift"],
                row_["computed_hours"],
                0,
                position,
            ))

            employee_id = cursor.lastrowid
            created_ids.append(employee_id)

            cursor.execute("""
                INSERT INTO departments (employee_id, department, time_assigned)
                VALUES (?, ?, ?)
            """, (employee_id, row_["current_department"], ""))

            count += 1

        if created_ids:
            _record(
                cursor, "Import Excel",
                f"{count} imported, {skipped} duplicates skipped "
                f"({', '.join(os.path.basename(p) for p in filepaths)})",
                delete_ids=created_ids,
            )

        conn.commit()
    except Exception:
        conn.rollback()  # wszystko albo nic
        raise
    finally:
        conn.close()

    unknown = sorted(set(employees_df["current_department"]) - set(config.TEAM_LIST))
    return count, skipped, unknown
