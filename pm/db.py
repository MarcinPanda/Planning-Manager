"""Dostęp do bazy SQLite: pracownicy, działy, dziennik zmian, cofanie, kopie zapasowe.

Każda operacja zmieniająca dane zapisuje wpis w tabeli change_log. Wpis może
zawierać „migawkę" stanu sprzed zmiany (undo_data) – dzięki niej działa Cofnij.
"""
import collections
import getpass
import glob
import json
import os
import sqlite3
from datetime import date, datetime, timedelta

from . import config
from .excel_io import read_consolidation_excel, read_logins_excel, read_planning_excel
from .logic import (
    Employee,
    Validator,
    join_positions,
    split_positions,
    move_lastname_prefix_to_firstname,
    name_key,
    parse_breaks,
    serialize_breaks,
    to_minutes,
)

EMP_COLS = (
    "id, lastname, firstname, current_department, work_hours, shift, "
    "computed_hours, marked, info, custom_breaks, late, position, planned_hours"
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
        ("planned_hours", "TEXT DEFAULT ''"),   # godziny z planu przed skróceniem przez Naar Huis
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

    # Lista konsolidacji (RIT-y). reachers = loginy '003' albo 'id:17' (osoba bez loginu), rozdzielone ';'.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS consolidation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datum TEXT NOT NULL,
            rit TEXT NOT NULL,
            seq INTEGER NOT NULL DEFAULT 1,
            area TEXT DEFAULT '',
            time TEXT DEFAULT '',
            amount INTEGER DEFAULT 0,
            kantel INTEGER DEFAULT 0,
            reachers TEXT DEFAULT '',
            reacher_text TEXT DEFAULT '',
            v INTEGER DEFAULT 0,
            done INTEGER DEFAULT 0,
            lane TEXT DEFAULT '',
            comment TEXT DEFAULT '',
            busy TEXT DEFAULT '',
            UNIQUE (datum, rit, seq)
        )
    """)
    # Strefy, które reacher miał przed wejściem na konsolidację – wracają po „V".
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS consolidation_prev (
            employee_id INTEGER PRIMARY KEY,
            positions TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (employee_id) REFERENCES employees (id) ON DELETE CASCADE
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

    # Stare nazwy stref -> nowe (np. „Kantel" + „Consolidatie" -> jedna strefa, „ITR" -> „Mars ITR")
    for table, key in (("employees", "id"), ("consolidation_prev", "employee_id")):
        column = "position" if table == "employees" else "positions"
        rows = cursor.execute(f"SELECT {key}, {column} FROM {table} WHERE {column} != ''").fetchall()
        for row_id, value in rows:
            if not value:
                continue
            merged = join_positions([config.POSITION_RENAMES.get(p, p) for p in split_positions(value)])
            if merged != value:
                cursor.execute(f"UPDATE {table} SET {column} = ? WHERE {key} = ?", (merged, row_id))

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
    emp.planned_hours = (row[12] if len(row) > 12 else "") or emp.work_hours

    cursor.execute("""
        SELECT department, time_assigned
        FROM departments
        WHERE employee_id = ?
        ORDER BY id ASC
    """, (emp.employee_id,))

    emp.dept_times = [(d, t) for d, t in cursor.fetchall()]
    emp.recalc_intervals_and_hours()
    return emp


def _load_employees(cursor):
    rows = cursor.execute(f"SELECT {EMP_COLS} FROM employees").fetchall()
    result = [_employee_from_row(cursor, row) for row in rows]

    logins = dict(cursor.execute("SELECT name_key, login FROM logins").fetchall())
    if logins:
        for emp in result:
            emp.login = find_login(name_key(emp.firstname, emp.lastname), logins)
    return result


def find_login(key, logins):
    """Login dla osoby: najpierw dokładnie to samo imię i nazwisko, potem – gdy w jednym pliku jest
    dłuższa wersja (np. plan „Ahmad Khalaf", plik loginów „AHMAD-NICOLAE KHALAF") – jedyny login,
    którego słowa zawierają wszystkie słowa osoby (albo odwrotnie). Przy kilku kandydatach: brak."""
    if key in logins:
        return logins[key]
    words = set(key.split())
    if len(words) < 2:
        return ""
    candidates = set()
    for other_key, login in logins.items():
        other = set(other_key.split())
        if len(other) >= 2 and (words <= other or other <= words):
            candidates.add(login)
    return candidates.pop() if len(candidates) == 1 else ""


def load_employees_from_db():
    conn = get_connection()
    try:
        return _load_employees(conn.cursor())
    finally:
        conn.close()


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
    if start_min == end_min:
        raise ValueError(f"No working hours in the plan ({emp.work_hours}). Set the work hours first.")
    overnight = end_min < start_min   # np. 15:00-00:00
    if overnight:
        end_min += 24 * 60

    def on_shift(minutes):
        """Godzina po północy na zmianie nocnej liczy się jako „następny dzień"."""
        return minutes + 24 * 60 if overnight and minutes < start_min else minutes

    new_min = on_shift(to_minutes(time_chosen))
    previous = start_min
    for _, t in emp.dept_times:
        if t and Validator.validate_time_format(t):
            previous = max(previous, on_shift(to_minutes(t)))

    if new_min < previous:
        raise ValueError(
            f"Time {time_chosen} is earlier than the previous change "
            f"({previous % 1440 // 60:02d}:{previous % 60:02d})."
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
        # Godziny z planu zapamiętujemy, żeby dało się zmienić godzinę wyjścia albo wrócić do pracy.
        start = emp.original_work_hours.split("-")[0].strip()
        emp.work_hours = f"{start}-{time_chosen}"

    emp.recalc_intervals_and_hours()
    cursor.execute("""
        UPDATE employees
        SET work_hours = ?, computed_hours = ?, marked = 0, position = ?, planned_hours = ?
        WHERE id = ?
    """, (emp.work_hours, emp.computed_hours, position, emp.planned_hours, emp_id))


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


def move_employees_in_db(employee_ids, dept, position="", time_chosen=None, from_position="", add=False,
                         from_start=False):
    """Przeniesienie w widoku Monitoring (upuszczenie kostki na dział / pozycję).

    - ten sam dział, inna pozycja  -> zmienia się tylko pozycja (godziny bez zmian);
      add=True dokłada pozycję do już posiadanych (praca w kilku strefach naraz),
      inaczej pozycja from_position jest zamieniana na nową,
    - przed początkiem pracy albo from_start=True (tryb „od początku zmiany")
                                   -> zmienia się dział początkowy (jak Edit Department),
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

            # przed początkiem zmiany (do 6 h wcześniej) – także dla zmiany przez północ
            minutes_to_start = (start_min - now_min) % (24 * 60) if start_min is not None else None
            before_start = (
                start_min is not None and start_min != end_min and 0 < minutes_to_start <= 6 * 60
                and len(emp.dept_times) == 1 and dept.lower() not in ("naar huis", "ziek")
            )
            if from_start:
                if len(emp.dept_times) > 1:
                    raise ValueError("already has changes during the shift – change it in Planning.")
                before_start = True

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
        _sync_consolidation_zones(cursor)  # nowa osoba w Reach może mieć już przypisany RIT
        target = f"{dept} / {position}" if position else dept
        if add and position:
            target += " (added)"
        if from_start:
            target += " (from start of shift)"
        _record(
            cursor, "Move",
            f"-> {target} @ {time_chosen}: {_names(cursor, changed)}",
            restore=[s for s in snapshot if s["row"][0] in changed],
        )

    conn.commit()
    conn.close()
    return errors


LEAVE_DEPARTMENTS = {"home": "Naar Huis", "sick": "Ziek"}


def _shift_bounds(emp):
    """(start, koniec) z godzin z planu w minutach, koniec po północy jako +24 h; None gdy brak godzin."""
    hours = emp.planned_hours or emp.work_hours
    if not isinstance(hours, str) or "-" not in hours:
        return None
    start_str, end_str = (p.strip() for p in hours.split("-", 1))
    if not (Validator.validate_time_format(start_str) and Validator.validate_time_format(end_str)):
        return None
    start, end = to_minutes(start_str), to_minutes(end_str)
    if start == end:
        return None
    return start, end + 24 * 60 if end < start else end


def _fmt(minutes):
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def leave_work_in_db(employee_ids, kind, time_chosen=None, all_day=False):
    """Naar Huis (kind='home') albo Ziek (kind='sick') dla jednej lub wielu osób naraz.

    - all_day=True: cały dzień nieobecny (chorobowe od rana / nie przyszedł) -> 0 h,
      wcześniejsze zmiany działów tego dnia są usuwane,
    - inaczej: od podanej godziny (godzina odbicia); godziny liczą się do niej.
      Naar Huis skraca godziny pracy (jak dotąd), Ziek nie – po Ziek godziny i tak liczą się jako 0.
    Godziny z planu zostają zapamiętane (planned_hours), żeby dało się zmienić godzinę albo cofnąć.
    Zwraca listę błędów.
    """
    dept = LEAVE_DEPARTMENTS[kind]
    if time_chosen is None:
        time_chosen = datetime.now().strftime("%H:%M")
    if not all_day and not Validator.validate_time_format(time_chosen):
        raise ValueError("Invalid time format.")

    conn = get_connection()
    cursor = conn.cursor()
    errors, changed = [], []
    snapshot = _snapshot(cursor, employee_ids)

    for emp_id in employee_ids:
        emp = load_employee_by_id(cursor, emp_id)
        if emp is None:
            continue
        label = f"{emp.lastname} {emp.firstname}"
        try:
            if emp.status in ("home", "sick"):
                raise ValueError(f"is already on {emp.active_department} – use 'Change time' or 'Back to work'.")
            if all_day:
                # cały dzień: od początku zmiany Ziek / Naar Huis (zmiany działów z tego dnia znikają)
                cursor.execute("DELETE FROM departments WHERE employee_id = ?", (emp_id,))
                cursor.execute(
                    "INSERT INTO departments (employee_id, department, time_assigned) VALUES (?, ?, '')",
                    (emp_id, dept),
                )
                emp.dept_times = [(dept, "")]
                emp.work_hours = emp.planned_hours
                emp.current_department = dept
                emp.recalc_intervals_and_hours()
                cursor.execute("""
                    UPDATE employees SET current_department = ?, work_hours = ?, computed_hours = ?,
                        marked = 0, position = '', planned_hours = ?
                    WHERE id = ?
                """, (dept, emp.work_hours, emp.computed_hours, emp.planned_hours, emp_id))
            else:
                _apply_add_department(cursor, emp, dept, time_chosen, "")
            changed.append(emp_id)
        except ValueError as exc:
            errors.append(f"{label}: {exc}")

    if changed:
        _sync_consolidation_zones(cursor)
        when = "all day" if all_day else f"@ {time_chosen}"
        _record(cursor, dept, f"{when}: {_names(cursor, changed)}",
                restore=[s for s in snapshot if s["row"][0] in changed])
    conn.commit()
    conn.close()
    return errors


def change_leave_time_in_db(employee_ids, time_chosen):
    """Zmiana godziny wyjścia (Naar Huis / Ziek) – np. na godzinę faktycznego odbicia. Zwraca błędy."""
    if not Validator.validate_time_format(time_chosen):
        raise ValueError("Invalid time format.")
    conn = get_connection()
    cursor = conn.cursor()
    errors, changed = [], []
    snapshot = _snapshot(cursor, employee_ids)

    for emp_id in employee_ids:
        emp = load_employee_by_id(cursor, emp_id)
        if emp is None:
            continue
        label = f"{emp.lastname} {emp.firstname}"
        try:
            if emp.status not in ("home", "sick") or not emp.active_since:
                raise ValueError("is not on Naar Huis / Ziek with a time (all-day absence has no time).")
            bounds = _shift_bounds(emp)
            if bounds is None:
                raise ValueError("has no working hours in the plan.")
            start, end = bounds
            new = to_minutes(time_chosen)
            if new < start:
                new += 24 * 60
            previous = start
            for _, t in emp.dept_times[:-1]:
                if t and Validator.validate_time_format(t):
                    m = to_minutes(t)
                    previous = max(previous, m + 24 * 60 if m < start else m)
            if not previous <= new <= end:
                raise ValueError(f"time must be between {_fmt(previous)} and {_fmt(end)}.")

            last_id = cursor.execute(
                "SELECT id FROM departments WHERE employee_id = ? ORDER BY id DESC LIMIT 1", (emp_id,)
            ).fetchone()[0]
            cursor.execute("UPDATE departments SET time_assigned = ? WHERE id = ?", (time_chosen, last_id))
            emp.dept_times[-1] = (emp.dept_times[-1][0], time_chosen)
            if emp.status == "home":
                emp.work_hours = f"{_fmt(start)}-{time_chosen}"
            emp.recalc_intervals_and_hours()
            cursor.execute("UPDATE employees SET work_hours = ?, computed_hours = ? WHERE id = ?",
                           (emp.work_hours, emp.computed_hours, emp_id))
            changed.append(emp_id)
        except ValueError as exc:
            errors.append(f"{label}: {exc}")

    if changed:
        _record(cursor, "Leave time", f"-> {time_chosen}: {_names(cursor, changed)}",
                restore=[s for s in snapshot if s["row"][0] in changed])
    conn.commit()
    conn.close()
    return errors


def back_to_work_in_db(employee_ids):
    """Cofnięcie Naar Huis / Ziek (pomyłka albo wrócił): usuwa ostatni wpis, przywraca godziny z planu."""
    conn = get_connection()
    cursor = conn.cursor()
    errors, changed = [], []
    snapshot = _snapshot(cursor, employee_ids)

    for emp_id in employee_ids:
        emp = load_employee_by_id(cursor, emp_id)
        if emp is None:
            continue
        if emp.status not in ("home", "sick"):
            continue
        if len(emp.dept_times) == 1:
            errors.append(f"{emp.lastname} {emp.firstname}: absent all day – use Undo or Edit Department.")
            continue
        last_id = cursor.execute(
            "SELECT id FROM departments WHERE employee_id = ? ORDER BY id DESC LIMIT 1", (emp_id,)
        ).fetchone()[0]
        cursor.execute("DELETE FROM departments WHERE id = ?", (last_id,))
        emp.dept_times.pop()
        emp.work_hours = emp.planned_hours
        emp.recalc_intervals_and_hours()
        cursor.execute("UPDATE employees SET work_hours = ?, computed_hours = ? WHERE id = ?",
                       (emp.work_hours, emp.computed_hours, emp_id))
        changed.append(emp_id)

    if changed:
        _sync_consolidation_zones(cursor)
        _record(cursor, "Back to work", _names(cursor, changed),
                restore=[s for s in snapshot if s["row"][0] in changed])
    conn.commit()
    conn.close()
    return errors


def set_positions_in_db(emp_id, positions):
    """Ustawia od razu wszystkie strefy / klientów osoby (kilka autoryzacji naraz). Godzin nie zmienia."""
    conn = get_connection()
    cursor = conn.cursor()
    emp = load_employee_by_id(cursor, emp_id)
    if emp is None:
        conn.close()
        raise ValueError("Employee not found.")
    new_value = join_positions(positions)
    if new_value != (emp.position or ""):
        _record(cursor, "Position", f"{emp.lastname} {emp.firstname}: {new_value.replace(';', ', ') or '-'}",
                restore=_snapshot(cursor, [emp_id]))
        cursor.execute("UPDATE employees SET position = ? WHERE id = ?", (new_value, emp_id))
        _sync_consolidation_zones(cursor)
    conn.commit()
    conn.close()


def shift_start_minutes(employees):
    """Najczęstsza godzina startu w planie (= start zmiany), w minutach; None gdy brak."""
    starts = collections.Counter()
    for emp in employees:
        hours = emp.planned_hours or emp.work_hours
        if isinstance(hours, str) and "-" in hours:
            start = hours.split("-", 1)[0].strip()
            if Validator.validate_time_format(start) and hours.split("-", 1)[1].strip() != start:
                starts[to_minutes(start)] += 1
    return starts.most_common(1)[0][0] if starts else None


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

        known = dict(cursor.execute("SELECT name_key, login FROM logins").fetchall())
        people = cursor.execute("SELECT firstname, lastname FROM employees").fetchall()
        matched = sum(1 for first, last in people if find_login(name_key(first, last), known))

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


###############################################################################
# Consolidation list (RIT-y) -> strefy Kantel / Consolidatie w Reach
###############################################################################

CONS_COLS = (
    "id, datum, rit, seq, area, time, amount, kantel, reachers, reacher_text, v, done, lane, comment, busy"
)


def employee_token(emp):
    """Jak zapisujemy reachera przy RIT-cie: login '003', a bez loginu 'id:17'."""
    return emp.login or f"id:{emp.employee_id}"


def consolidation_zones(amount=0, kantel=0):
    """Strefa, którą daje RIT reacherowi: zawsze jedna – „Kantel/Consolidatie"."""
    return [config.CONSOLIDATION_ZONE]


def _row_to_dict(row):
    data = dict(zip([c.strip() for c in CONS_COLS.split(",")], row))
    data["reachers"] = split_positions(data["reachers"])
    data["v"] = bool(data["v"])
    data["done"] = bool(data["done"])
    return data


def load_consolidation(datum=None):
    """RIT-y z danego dnia ('YYYY-MM-DD'), albo wszystkie, gdy datum=None; posortowane po godzinie."""
    conn = get_connection()
    try:
        if datum:
            rows = conn.execute(
                f"SELECT {CONS_COLS} FROM consolidation WHERE datum = ? ORDER BY time, rit, seq", (datum,)
            ).fetchall()
        else:
            rows = conn.execute(f"SELECT {CONS_COLS} FROM consolidation ORDER BY datum, time, rit, seq").fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def consolidation_dates():
    conn = get_connection()
    try:
        return [r[0] for r in conn.execute("SELECT DISTINCT datum FROM consolidation ORDER BY datum").fetchall()]
    finally:
        conn.close()


def login_names():
    """login -> nazwisko z pliku loginów (do pokazania reachera, którego nie ma dziś na liście)."""
    conn = get_connection()
    try:
        result = {}
        for name, login in conn.execute("SELECT name, login FROM logins ORDER BY name").fetchall():
            result.setdefault(login, name)
        return result
    finally:
        conn.close()


def _sync_consolidation_zones(cursor):
    """Ustawia reacherom strefy Kantel / Consolidatie według otwartych RIT-ów (bez „V").

    - pierwszy otwarty RIT: zapamiętujemy dotychczasowe strefy i zamieniamy je na strefy RIT-u,
    - kolejne RIT-y: strefy konsolidacji się sumują, ręcznie dodane inne strefy zostają,
    - ostatni RIT zwieziony („V"): wracają zapamiętane strefy.
    Dotyczy tylko osób, które są teraz w dziale Reach. Godzin nie zmienia.
    """
    managed = {config.CONSOLIDATION_ZONE, *config.CONSOLIDATION_OLD_ZONES}
    since = (date.today() - timedelta(days=config.CONSOLIDATION_ACTIVE_DAYS)).isoformat()

    wanted = {}
    for reachers, amount, kantel in cursor.execute(
        "SELECT reachers, amount, kantel FROM consolidation WHERE v = 0 AND reachers != '' AND datum >= ?",
        (since,),
    ).fetchall():
        for token in split_positions(reachers):
            wanted.setdefault(token, set()).update(consolidation_zones(amount or 0, kantel or 0))

    prev = dict(cursor.execute("SELECT employee_id, positions FROM consolidation_prev").fetchall())
    order = config.SUB_POSITIONS.get(config.CONSOLIDATION_DEPARTMENT, [])

    def ordered(zones):
        return sorted(zones, key=lambda z: order.index(z) if z in order else len(order))

    changes = []
    for emp in _load_employees(cursor):
        emp_id = emp.employee_id
        if emp.active_department != config.CONSOLIDATION_DEPARTMENT or emp.status in ("sick", "home"):
            if emp_id in prev:
                cursor.execute("DELETE FROM consolidation_prev WHERE employee_id = ?", (emp_id,))
            continue

        want = set()
        for token in {f"id:{emp_id}", emp.login} - {""}:
            want |= wanted.get(token, set())

        if want:
            if emp_id not in prev:
                cursor.execute(
                    "INSERT INTO consolidation_prev (employee_id, positions) VALUES (?, ?)", (emp_id, emp.position or "")
                )
                base = []
            else:
                base = [p for p in emp.positions if p not in managed]
            new_positions = base + ordered(want)
        elif emp_id in prev:
            new_positions = [p for p in split_positions(prev[emp_id]) if p not in managed]
            cursor.execute("DELETE FROM consolidation_prev WHERE employee_id = ?", (emp_id,))
        else:
            continue

        new_value = join_positions(new_positions)
        if new_value != (emp.position or ""):
            cursor.execute("UPDATE employees SET position = ? WHERE id = ?", (new_value, emp_id))
            changes.append(f"{emp.lastname} {emp.firstname} -> {new_value.replace(';', ', ') or '-'}")

    if changes:
        _record(cursor, "Consolidation zones", "; ".join(changes[:10]))
    return changes


def sync_consolidation_zones():
    conn = get_connection()
    try:
        changes = _sync_consolidation_zones(conn.cursor())
        conn.commit()
        return changes
    finally:
        conn.close()


def _rit_label(cursor, cons_id):
    row = cursor.execute("SELECT rit, time FROM consolidation WHERE id = ?", (cons_id,)).fetchone()
    return f"RIT {row[0]} ({row[1]})" if row else f"RIT #{cons_id}"


def update_consolidation_in_db(cons_id, **fields):
    """Zmienia pola RIT-u (reachers jako lista, v / done jako bool, lane, comment...) i od razu
    przestawia strefy reacherów na Monitoringu. Zwraca listę zmian stref."""
    allowed = {"reachers", "v", "done", "lane", "comment", "busy", "time", "area", "amount", "kantel", "rit"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Unknown field(s): {', '.join(sorted(unknown))}")

    values = {}
    for key, value in fields.items():
        if key == "reachers":
            values[key] = join_positions(value)
        elif key in ("v", "done"):
            values[key] = 1 if value else 0
        elif key in ("amount", "kantel"):
            values[key] = int(value or 0)
        else:
            values[key] = str(value or "").strip()
    if "time" in values and values["time"] and not Validator.validate_time_format(values["time"]):
        raise ValueError("Invalid time format (HH:MM).")
    if values.get("reachers"):
        values["reacher_text"] = ""
    if not values:
        return []

    conn = get_connection()
    cursor = conn.cursor()
    try:
        label = _rit_label(cursor, cons_id)
        sets = ", ".join(f"{k} = ?" for k in values)
        cursor.execute(f"UPDATE consolidation SET {sets} WHERE id = ?", (*values.values(), cons_id))
        if cursor.rowcount == 0:
            raise ValueError("RIT not found.")
        shown = {k: v for k, v in values.items() if k != "reacher_text"}
        _record(cursor, "Consolidation", f"{label}: " + ", ".join(f"{k}={v}" for k, v in shown.items()))
        changes = _sync_consolidation_zones(cursor)
        conn.commit()
        return changes
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def add_consolidation_in_db(datum, rit, area="noord", time="", amount=0, kantel=0, comment=""):
    rit = str(rit).strip()
    if not rit:
        raise ValueError("RIT number is required.")
    if time and not Validator.validate_time_format(time):
        raise ValueError("Invalid time format (HH:MM).")

    conn = get_connection()
    cursor = conn.cursor()
    try:
        seq = cursor.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM consolidation WHERE datum = ? AND rit = ?", (datum, rit)
        ).fetchone()[0]
        cursor.execute("""
            INSERT INTO consolidation (datum, rit, seq, area, time, amount, kantel, comment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (datum, rit, seq, area, time, int(amount or 0), int(kantel or 0), comment))
        new_id = cursor.lastrowid
        _record(cursor, "Consolidation", f"Added RIT {rit} ({datum} {time})")
        conn.commit()
        return new_id
    finally:
        conn.close()


def delete_consolidation_in_db(cons_ids):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        labels = [_rit_label(cursor, i) for i in cons_ids]
        cursor.executemany("DELETE FROM consolidation WHERE id = ?", [(i,) for i in cons_ids])
        _record(cursor, "Consolidation", "Deleted " + ", ".join(labels[:10]))
        changes = _sync_consolidation_zones(cursor)
        conn.commit()
        return changes
    finally:
        conn.close()


def import_consolidation_from_excel(filepath):
    """Wczytuje listę konsolidacji od (dziś - CONSOLIDATION_IMPORT_DAYS).

    Nowe RIT-y są dodawane. Istniejące (ta sama data + RIT) dostają z pliku godzinę, strefę i liczby palet;
    reacher / lane / komentarz z pliku tylko wtedy, gdy w aplikacji są puste; V i Done – gdy są w pliku
    albo w aplikacji (raz zwiezione zostaje zwiezione).
    Zwraca (nowe, zaktualizowane, zmiany stref).
    """
    since = date.today() - timedelta(days=config.CONSOLIDATION_IMPORT_DAYS)
    rows = read_consolidation_excel(filepath, since=since)

    conn = get_connection()
    cursor = conn.cursor()
    added = updated = 0
    try:
        for r in rows:
            existing = cursor.execute(
                "SELECT id, reachers, lane, comment, busy, reacher_text FROM consolidation "
                "WHERE datum = ? AND rit = ? AND seq = ?",
                (r["datum"], r["rit"], r["seq"]),
            ).fetchone()
            reachers = join_positions(r["reachers"])
            if existing is None:
                cursor.execute("""
                    INSERT INTO consolidation (datum, rit, seq, area, time, amount, kantel, reachers, reacher_text,
                                               v, done, lane, comment, busy)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (r["datum"], r["rit"], r["seq"], r["area"], r["time"], r["amount"], r["kantel"], reachers,
                      r["reacher_text"], int(r["v"]), int(r["done"]), r["lane"], r["comment"], r["busy"]))
                added += 1
            else:
                cons_id, old_reachers, old_lane, old_comment, old_busy, old_text = existing
                cursor.execute("""
                    UPDATE consolidation SET
                        area = ?, time = ?, amount = ?, kantel = ?,
                        reachers = ?, reacher_text = ?, lane = ?, comment = ?, busy = ?,
                        v = MAX(v, ?), done = MAX(done, ?)
                    WHERE id = ?
                """, (r["area"], r["time"], r["amount"], r["kantel"],
                      old_reachers or reachers, old_text if old_reachers else r["reacher_text"],
                      old_lane or r["lane"], old_comment or r["comment"], old_busy or r["busy"],
                      int(r["v"]), int(r["done"]), cons_id))
                updated += 1

        _record(cursor, "Import consolidation",
                f"{os.path.basename(filepath)}: {added} new, {updated} updated (from {since.isoformat()})")
        changes = _sync_consolidation_zones(cursor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return added, updated, changes
