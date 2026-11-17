"""Odczyt planu z plików Excel i eksport tabeli do Excela."""

from .config import DEPARTMENT_OVERRIDES, SPECIAL_FUNCTIONS, col_names
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
                parts = [p.strip() for p in val_b.split("/") if p.strip()]

                if len(parts) >= 2:
                    shift_candidate = parts[1]
                    current_shift = shift_candidate if shift_candidate in ["Ochtend", "Middag", "Day8to17"] else None

                if len(parts) >= 3:
                    current_department = parts[2]
                else:
                    current_department = None

                continue

            val_d = row[lastname_col] if len(row) > lastname_col else None
            val_e = row[firstname_col] if len(row) > firstname_col else None

            if isinstance(val_d, str) and "Achternaam" in val_d:
                continue
            if isinstance(val_e, str) and "Voornaam" in val_e:
                continue

            if isinstance(val_d, str) and val_d.strip() and isinstance(val_e, str) and val_e.strip():
                val_hours = row[work_hours_col] if len(row) > work_hours_col else None
                dept = current_department if current_department else "Unknown"

                if dept.strip().lower() == "consolidatie":
                    dept = "Consolidatie/Kantelen"
                elif dept.strip().lower() == "transport coördinator":
                    dept = "Laco"

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


def read_logins_excel(filepath):
    """Czyta spis loginów: szuka nagłówków 'Login:' i 'Name:' (najpierw w arkuszu 'Logins').
    Zwraca listę (nazwisko, login)."""
    sheets = _pd().read_excel(filepath, sheet_name=None, header=None, dtype=str)
    names = sorted(sheets, key=lambda n: 0 if n.strip().lower() == "logins" else 1)

    for sheet_name in names:
        data = sheets[sheet_name]
        for r in range(min(len(data), 30)):
            cells = [str(v).strip().lower().rstrip(":") if isinstance(v, str) else "" for v in data.iloc[r]]
            if "login" in cells and "name" in cells:
                login_col, name_col = cells.index("login"), cells.index("name")
                result = []
                for i in range(r + 1, len(data)):
                    login, name = data.iat[i, login_col], data.iat[i, name_col]
                    if not isinstance(login, str) or not isinstance(name, str):
                        continue
                    login, name = login.strip(), name.strip()
                    if login.endswith(".0"):
                        login = login[:-2]
                    login = login.lstrip("0") or "0"
                    if name and name != "0" and login != "0":
                        result.append((name, login))
                return result

    raise ValueError("No 'Login:' / 'Name:' columns found in this file.")
