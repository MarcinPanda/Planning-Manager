"""Odczyt planu z plików Excel i eksport tabeli do Excela."""
import re

from .config import DEPARTMENT_ALIASES, DEPARTMENT_AS_POSITION, DEPARTMENT_OVERRIDES, SPECIAL_FUNCTIONS, TEAM_LIST, col_names
from .logic import (
    adjust_work_hours,
    compute_hours_with_breaks,
    format_name,
    move_lastname_prefix_to_firstname,
)


def _pd():
    """pandas jest ciężki – ładujemy go dopiero, gdy naprawdę jest potrzebny (szybszy start)."""
    import pandas
    return pandas


def warm_up():
    """Doczytuje pandas w tle po starcie, żeby pierwszy import planu nie czekał."""
    try:
        _pd()
    except Exception:
        pass


def parse_section_header(text):
    """' / Warehouse 1 / Ochtend / Stuwarooij/Omstapelen/ Week47' -> ('Ochtend', 'Stuwarooij/Omstapelen').
    Dział to wszystko między zmianą a końcowym 'WeekNN' (może zawierać '/')."""
    parts = [p.strip() for p in text.split("/") if p.strip()]
    if parts and parts[-1].lower().startswith("week"):
        parts = parts[:-1]

    shift = parts[1] if len(parts) >= 2 and parts[1] in ("Ochtend", "Middag", "Day8to17") else None
    department = "/".join(parts[2:]) if len(parts) >= 3 else None
    return shift, department


def _loose_key(text):
    """Klucz do DEPARTMENT_AS_POSITION: małe litery, pojedyncze spacje."""
    return " ".join(str(text).casefold().split())


def _loose(text):
    """Porównanie „na luzie": bez wielkości liter, spacji i znaków interpunkcyjnych."""
    return "".join(ch for ch in str(text).casefold() if ch.isalnum())


def normalize_department(name):
    """Ujednolica nazwę działu z Excela z listą działów aplikacji.

    Kolejność: alias -> dokładna nazwa z listy -> nazwa bez spacji/znaków ->
    dla nazw z '/' (np. 'Orderpicker/Picking') pierwsza część, która pasuje.
    Gdy nic nie pasuje, zwraca nazwę z Excela (osoba trafi na tablicy do 'Other').
    """
    name = " ".join(str(name).split())
    loose_aliases = {_loose(k): v for k, v in DEPARTMENT_ALIASES.items()}
    loose_teams = {_loose(t): t for t in TEAM_LIST}

    alias = DEPARTMENT_ALIASES.get(name.lower()) or loose_aliases.get(_loose(name))
    if alias:
        return alias
    if _loose(name) in loose_teams:
        return loose_teams[_loose(name)]

    if "/" in name:
        for part in name.split("/"):
            part = part.strip()
            match = DEPARTMENT_ALIASES.get(part.lower()) or loose_aliases.get(_loose(part)) \
                or loose_teams.get(_loose(part))
            if match:
                return match
    return name


def normalize_hours(value):
    """'06:00-15:00 ' / '6:00 - 15:00' -> '06:00-15:00'; inne wartości bez zmian."""
    if not isinstance(value, str) or "-" not in value:
        return value
    start, end = (p.strip() for p in value.split("-", 1))

    def fix(t):
        if ":" in t:
            hh, mm = t.split(":", 1)
            if hh.isdigit() and mm.isdigit():
                return f"{int(hh):02d}:{int(mm):02d}"
        return t

    return f"{fix(start)}-{fix(end)}"


def read_planning_excel(filepaths):
    """Czyta pliki planu i zwraca DataFrame: lastname, firstname, current_department,
    work_hours, shift, computed_hours. Nie dotyka bazy."""
    employees_list = []

    for filepath in filepaths:
        data = _pd().read_excel(filepath, header=None)

        if data.shape[1] < 6:
            raise ValueError(f"The file {filepath} does not contain enough columns (min. 6).")

        lastname_col = 3
        firstname_col = 4
        work_hours_col = data.shape[1] - 1
        current_department = None
        current_shift = None

        for i in range(len(data)):
            row = data.iloc[i, :]

            val_b = row[1] if len(row) > 1 else None
            if isinstance(val_b, str) and "Warehouse" in val_b and "Week" in val_b:
                current_shift, current_department = parse_section_header(val_b)
                continue

            val_d = row[lastname_col] if len(row) > lastname_col else None
            val_e = row[firstname_col] if len(row) > firstname_col else None

            if isinstance(val_d, str) and "Achternaam" in val_d:
                continue
            if isinstance(val_e, str) and "Voornaam" in val_e:
                continue

            if isinstance(val_d, str) and val_d.strip() and isinstance(val_e, str) and val_e.strip():
                val_hours = normalize_hours(row[work_hours_col] if len(row) > work_hours_col else None)
                dept = normalize_department(current_department) if current_department else "Unknown"
                position = ""
                as_position = DEPARTMENT_AS_POSITION.get(_loose_key(dept))
                if as_position:
                    dept, position = as_position

                shift = current_shift if current_shift else ""

                if dept in SPECIAL_FUNCTIONS or dept == "Logistiek coördinator":
                    val_hours = adjust_work_hours(val_hours, dept)

                if not shift and isinstance(val_hours, str) and "08:00-17:00" in val_hours:
                    shift = "Day8to17"

                lastname, firstname = move_lastname_prefix_to_firstname(val_d, val_e)

                for rule in DEPARTMENT_OVERRIDES:
                    if (
                        lastname.lower() == rule["lastname"]
                        and firstname.lower() == rule["firstname"]
                        and dept.lower() in rule["from"]
                    ):
                        dept = rule["to"]
                        val_hours = adjust_work_hours(val_hours, dept)

                employees_list.append([lastname, firstname, dept, val_hours, shift, position])

    employees_df = _pd().DataFrame(
        employees_list,
        columns=["lastname", "firstname", "current_department", "work_hours", "shift", "position"]
    )
    employees_df = employees_df.dropna(subset=["lastname", "firstname"])

    words_to_exclude = "Achternaam|Voornaam|Badge"
    mask = ~(
        employees_df["lastname"].str.contains(words_to_exclude, na=False, case=False) |
        employees_df["firstname"].str.contains(words_to_exclude, na=False, case=False) |
        employees_df["current_department"].str.contains(words_to_exclude, na=False, case=False) |
        employees_df["work_hours"].fillna("").str.contains(words_to_exclude, na=False, case=False)
    )

    employees_df = employees_df[mask]
    employees_df["lastname"] = employees_df["lastname"].apply(format_name)
    employees_df["firstname"] = employees_df["firstname"].apply(format_name)
    employees_df["computed_hours"] = employees_df.apply(
        lambda row_: compute_hours_with_breaks(row_["work_hours"], row_["shift"]),
        axis=1
    )

    return employees_df


def export_rows_to_excel(rows, filepath):
    """rows: lista list wartości w kolejności kolumn tabeli (bez kolumny Marked)."""
    df = _pd().DataFrame(rows, columns=col_names[1:])
    df.to_excel(filepath, index=False, sheet_name="Planning")


LOGIN_CODE = re.compile(r"^[A-Za-z]{1,2}(\d{1,4})[A-Za-z]{1,2}$")  # N012P, Z012P, R012R


def normalize_login(value):
    """'12', '012', 12.0 lub kod 'N012P' / 'R012R' -> '012'. Pusty tekst, gdy to nie login."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    match = LOGIN_CODE.match(text)
    if match:
        text = match.group(1)
    if not text.isdigit() or int(text) == 0:
        return ""
    return f"{int(text):03d}"


def read_logins_excel(filepath):
    """Czyta spis loginów i zwraca listę (nazwisko, login '012').

    Obsługuje oba układy:
    - plik z kodami (kolumny Naam / Noord 'N012P' / Zuid 'Z012P' / Reach 'R012R'),
    - plik z kolumnami 'Login:' i 'Name:' (np. zakładka Logins).
    """
    # Bez pandas: openpyxl w trybie tylko do odczytu jest wielokrotnie szybszy przy pierwszym użyciu.
    import openpyxl

    workbook = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    try:
        sheets = {ws.title: [list(row) for row in ws.iter_rows(values_only=True)] for ws in workbook.worksheets}
    finally:
        workbook.close()
    names = sorted(sheets, key=lambda n: 0 if n.strip().lower() in ("logins", "inlognamen") else 1)

    def cell(rows, r, c):
        row = rows[r]
        return row[c] if c < len(row) else None

    for sheet_name in names:
        data = sheets[sheet_name]
        for r in range(min(len(data), 30)):
            cells = [str(v).strip().lower().rstrip(":") if isinstance(v, str) else "" for v in data[r]]
            name_col = next((i for i, c in enumerate(cells) if c in ("name", "naam")), None)
            if name_col is None:
                continue

            code_cols = [i for i, c in enumerate(cells) if c in ("noord", "zuid", "reach")]
            login_cols = [i for i, c in enumerate(cells) if c in ("login", "nummer", "nummer-1", "nr")]
            if not code_cols and not login_cols:
                continue

            result = []
            for i in range(r + 1, len(data)):
                name = cell(data, i, name_col)
                if not isinstance(name, str) or not name.strip() or name.strip() == "0":
                    continue
                login = ""
                for col in code_cols + login_cols:
                    login = normalize_login(cell(data, i, col))
                    if login:
                        break
                if login:
                    result.append((" ".join(name.split()), login))
            if result:
                return result

    raise ValueError("No login list found (expected a 'Naam' / 'Name' column with login codes or numbers).")


def parse_reachers(value):
    """'R003R/R091R', 'R052R / R105R', 'r118r' -> ['003', '091'] (loginy reacherów)."""
    if value is None:
        return []
    result = []
    for part in re.split(r"[/,;+&\s]+", str(value)):
        login = normalize_login(part)
        if login and login not in result:
            result.append(login)
    return result


def _as_date(value):
    from datetime import date, datetime

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                pass
    return None


def _as_time(value):
    from datetime import datetime, time

    if isinstance(value, datetime):
        value = value.time()
    if isinstance(value, time):
        return f"{value.hour:02d}:{value.minute:02d}"
    if isinstance(value, (int, float)) and 0 <= value < 1:  # ułamek doby z Excela
        minutes = round(value * 24 * 60)
        return f"{minutes // 60:02d}:{minutes % 60:02d}"
    if isinstance(value, str):
        return normalize_hours(value.strip()) if ":" in value else value.strip()
    return ""


def _as_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _flag(value):
    """'v' / 'V' / 'x' / 'X' / ' v' -> True."""
    return isinstance(value, str) and value.strip() != "" or value is True


def read_consolidation_excel(filepath, since=None):
    """Czyta listę konsolidacji (zakładka Consolidatie) i zwraca listę słowników:
    datum, rit, seq, area, time, amount, kantel, reachers, reacher_text, v, done, lane, comment, busy.

    since: data (datetime.date) – starsze wiersze są pomijane.
    seq numeruje powtórzenia tego samego RIT-u w jednym dniu (w pliku zdarzają się dwa wiersze).
    """
    import openpyxl

    workbook = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    try:
        sheets = sorted(workbook.worksheets, key=lambda ws: 0 if ws.title.strip().lower() == "consolidatie" else 1)
        for ws in sheets:
            rows = ws.iter_rows(values_only=True)
            header = None
            for _ in range(30):
                row = next(rows, None)
                if row is None:
                    break
                cells = [str(v).strip().lower() if isinstance(v, str) else "" for v in row]
                if "rit" in cells and "datum" in cells:
                    header = cells
                    break
            if header is None:
                continue

            def find(*names):
                return next((i for i, c in enumerate(header) if any(c.startswith(n) for n in names)), None)

            col = {
                "datum": find("datum"),
                "rit": find("rit"),
                "time": find("time", "tijd"),
                "amount": find("amount", "aantal"),
                "kantel": find("kantel"),
                "reacher": find("reacher"),
                "v": header.index("v") if "v" in header else None,
                "done": find("done"),
                "lane": find("lane"),
                "busy": find("who"),
            }
            if col["rit"] is None or col["datum"] is None:
                continue
            col["area"] = col["rit"] + 1
            col["comment"] = col["lane"] + 1 if col["lane"] is not None else None

            def get(row, name):
                index = col.get(name)
                return row[index] if index is not None and index < len(row) else None

            result = []
            seen = {}
            for row in rows:
                rit = get(row, "rit")
                datum = _as_date(get(row, "datum"))
                if rit is None or str(rit).strip() == "" or datum is None:
                    continue
                if since is not None and datum < since:
                    continue
                rit = str(rit).strip()
                if rit.endswith(".0"):
                    rit = rit[:-2]
                key = (datum, rit)
                seen[key] = seen.get(key, 0) + 1

                reacher_raw = get(row, "reacher")
                reachers = parse_reachers(reacher_raw)
                area = get(row, "area")
                text = lambda v: " ".join(str(v).split()) if v is not None else ""  # noqa: E731
                result.append({
                    "datum": datum.isoformat(),
                    "rit": rit,
                    "seq": seen[key],
                    "area": text(area).lower() if isinstance(area, str) else "",
                    "time": _as_time(get(row, "time")),
                    "amount": _as_int(get(row, "amount")),
                    "kantel": _as_int(get(row, "kantel")),
                    "reachers": reachers,
                    "reacher_text": "" if reachers else text(reacher_raw),
                    "v": _flag(get(row, "v")),
                    "done": _flag(get(row, "done")),
                    "lane": text(get(row, "lane")),
                    "comment": text(get(row, "comment")),
                    "busy": text(get(row, "busy")),
                })
            return result
    finally:
        workbook.close()

    raise ValueError("No consolidation list found (expected a sheet with 'Datum' and 'RIT' columns).")
