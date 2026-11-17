"""Odczyt planu z plików Excel i eksport tabeli do Excela."""
import re

from .config import DEPARTMENT_ALIASES, DEPARTMENT_OVERRIDES, SPECIAL_FUNCTIONS, TEAM_LIST, col_names
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


def parse_section_header(text):
    """' / Warehouse 1 / Ochtend / Stuwarooij/Omstapelen/ Week47' -> ('Ochtend', 'Stuwarooij/Omstapelen').
    Dział to wszystko między zmianą a końcowym 'WeekNN' (może zawierać '/')."""
    parts = [p.strip() for p in text.split("/") if p.strip()]
    if parts and parts[-1].lower().startswith("week"):
        parts = parts[:-1]

    shift = parts[1] if len(parts) >= 2 and parts[1] in ("Ochtend", "Middag", "Day8to17") else None
    department = "/".join(parts[2:]) if len(parts) >= 3 else None
    return shift, department


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

                employees_list.append([lastname, firstname, dept, val_hours, shift])

    employees_df = _pd().DataFrame(
        employees_list,
        columns=["lastname", "firstname", "current_department", "work_hours", "shift"]
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
    sheets = _pd().read_excel(filepath, sheet_name=None, header=None, dtype=str)
    names = sorted(sheets, key=lambda n: 0 if n.strip().lower() in ("logins", "inlognamen") else 1)

    for sheet_name in names:
        data = sheets[sheet_name]
        for r in range(min(len(data), 30)):
            cells = [str(v).strip().lower().rstrip(":") if isinstance(v, str) else "" for v in data.iloc[r]]
            name_col = next((i for i, c in enumerate(cells) if c in ("name", "naam")), None)
            if name_col is None:
                continue

            code_cols = [i for i, c in enumerate(cells) if c in ("noord", "zuid", "reach")]
            login_cols = [i for i, c in enumerate(cells) if c in ("login", "nummer", "nummer-1", "nr")]
            if not code_cols and not login_cols:
                continue

            result = []
            for i in range(r + 1, len(data)):
                name = data.iat[i, name_col]
                if not isinstance(name, str) or not name.strip() or name.strip() == "0":
                    continue
                login = ""
                for col in code_cols + login_cols:
                    login = normalize_login(data.iat[i, col])
                    if login:
                        break
                if login:
                    result.append((" ".join(name.split()), login))
            if result:
                return result

    raise ValueError("No login list found (expected a 'Naam' / 'Name' column with login codes or numbers).")
