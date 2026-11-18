"""Etap 6: zapis godzin do kopii pliku Uren_Lijst – na małym, zmyślonym pliku o tym samym układzie."""
import zipfile
from datetime import date

import openpyxl
import pytest

from pm import hours_export as hx
from pm.logic import Employee

HEADERS = ["Teamleader", "Assistent Teamleader", "Reach ", "Orderpicking", "Consolidatie (muv kantel)", "Kantelen",
           "Laden", "Opleiding", "Lossen - inslag controle", "Controle / Formeren", "Accu", "Extern indirect"]
PEOPLE = [("Kowalski Jan", "Fulltimer"), ("Visser Anna", "Uitzendkracht"), ("De Vries Piet", "Fulltimer")]


@pytest.fixture
def week_file(tmp_path):
    """Plik jak Uren_Lijst: Namen + arkusze dni z formułami w A, sumą i wierszem sum."""
    wb = openpyxl.Workbook()
    namen = wb.active
    namen.title = "Namen"
    namen.append(["Naam", "Contractvorm", "Pers. Nr."])
    for i, (name, kind) in enumerate(PEOPLE):
        namen.append([name, kind, 1000 + i])
    last_hours = 2 + len(HEADERS)        # C… = godziny
    total_col = openpyxl.utils.get_column_letter(last_hours + 1)
    for day in ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]:
        ws = wb.create_sheet(day)
        ws.append(["Naam", "vast/flex", *HEADERS, "Totaal", "Opmerking"])
        for r in range(2, 7):
            ws[f"A{r}"] = f'=IF(Namen!A{r}="","",Namen!A{r})'
            ws[f"B{r}"] = f'=LEFT(IF(Namen!B{r}="","",Namen!B{r}),1)'
            ws[f"{total_col}{r}"] = f"=SUM(C{r}:{openpyxl.utils.get_column_letter(last_hours)}{r})"
        ws["A7"] = '=IF(Namen!A6="","",Namen!A6)'   # wiersz sum – odwołanie do innego wiersza
        ws["C7"] = "=SUM(C2:C6)"
    wb["Woensdag"]["D3"] = 8                         # Visser ma już godziny w środę
    wb["Woensdag"][f"{openpyxl.utils.get_column_letter(last_hours + 2)}2"] = "late"
    path = tmp_path / "Uren_Lijst_WEEK_47.xlsx"
    wb.save(path)
    # openpyxl nie zapisuje wartości formuł – wstawiamy je tak, jak zrobiłby to Excel (t="str" + <v>)
    _put_cached_names(path)
    return str(path)


def _put_cached_names(path):
    with zipfile.ZipFile(path) as zf:
        items = [(info, zf.read(info.filename)) for info in zf.infolist()]
    names = {r: name for r, (name, _) in enumerate(PEOPLE, start=2)}
    out = []
    for info, data in items:
        if info.filename.startswith("xl/worksheets/sheet") and info.filename != "xl/worksheets/sheet1.xml":
            text = data.decode("utf-8")
            for r, name in names.items():
                text = text.replace(f'<c r="A{r}"><f>IF(Namen!A{r}="","",Namen!A{r})</f><v /></c>',
                                    f'<c r="A{r}" t="str"><f>IF(Namen!A{r}="","",Namen!A{r})</f><v>{name}</v></c>')
            data = text.encode("utf-8")
        out.append((info, data))
    with zipfile.ZipFile(path, "w") as zf:
        for info, data in out:
            zf.writestr(info, data)


def employee(last, first, depts, hours="15:00-00:00", late=False):
    emp = Employee(1, last, first, depts[0][0], hours, "Middag", 0, False, "", late=late)
    emp.dept_times = depts
    emp.recalc_intervals_and_hours()
    return emp


def test_reads_day_sheet(week_file):
    sheet = hx.read_day_sheet(week_file, "Woensdag")
    assert sheet.week == 47
    assert [r.name for r in sheet.rows] == [p[0] for p in PEOPLE]   # wiersz sum pominięty
    assert sheet.letter_for("Reach") == "E"
    assert sheet.rows[1].values == {"D": 8}
    assert sheet.rows[0].note == "late"


def test_propose_maps_departments_and_flags_problems(week_file):
    sheet = hx.read_day_sheet(week_file, "Woensdag")
    emps = [
        employee("Kowalski", "Jan", [("Reachtruck", ""), ("Orderpicker", "19:00")]),
        employee("Visser", "Anna", [("Laden", "")]),
        employee("Nowak", "Ewa", [("Laden", "")]),
        employee("de Vries", "Piet", [("Buffer", ""), ("Naar Huis", "20:30")]),
    ]
    lines = hx.propose(emps, sheet)
    by_person = {}
    for line in lines:
        by_person.setdefault(line.person, []).append(line)
    jan = by_person["Kowalski Jan"]
    assert [(l.column, l.hours) for l in jan] == [("Reach", 3.75), ("Orderpicking", 4.25)]
    assert all(l.include for l in jan)
    assert by_person["Visser Anna"][0].include is False and "already filled" in by_person["Visser Anna"][0].status
    assert by_person["Nowak Ewa"][0].row is None
    piet = by_person["Vries Piet de"] if "Vries Piet de" in by_person else by_person["de Vries Piet"]
    assert piet[0].column == "" and piet[0].note == "went home 20:30"


def test_write_copy_changes_only_chosen_cells(week_file):
    sheet = hx.read_day_sheet(week_file, "Woensdag")
    emps = [employee("Kowalski", "Jan", [("Reachtruck", ""), ("Orderpicker", "19:00")], late=True),
            employee("de Vries", "Piet", [("Buffer", ""), ("Naar Huis", "20:30")])]
    lines = hx.propose(emps, sheet)
    for line in lines:
        if line.department == "Buffer":
            line.column = "Extern indirect"
    values, notes, errors = hx.build_changes(lines, sheet)
    assert errors == []
    dst = hx.write_copy(week_file, sheet, values, notes)
    assert dst.endswith("Uren_Lijst_WEEK_47_copy.xlsx")

    with zipfile.ZipFile(week_file) as a, zipfile.ZipFile(dst) as b:
        changed = [n for n in a.namelist() if a.read(n) != b.read(n)]
    assert sheet.part in changed and set(changed) <= {sheet.part, "xl/workbook.xml"}

    wb = openpyxl.load_workbook(dst)
    ws = wb["Woensdag"]
    assert ws["E2"].value == 3.75 and ws["F2"].value == 4.25
    assert ws["P2"].value == "late"          # „late" już było – bez dublowania
    assert ws["D3"].value == 8               # cudze godziny nietknięte
    assert ws["N4"].value == 4.75            # Buffer → wybrana kolumna (15:00–20:30 minus przerwy)
    assert ws["P4"].value == "went home 20:30"
    assert ws["A2"].value.startswith("=IF(Namen!A2")   # formuły zostają
    assert openpyxl.load_workbook(week_file)["Woensdag"]["E2"].value is None   # oryginał bez zmian


def test_verify_detects_unexpected_change(week_file, tmp_path):
    sheet = hx.read_day_sheet(week_file, "Woensdag")
    dst = hx.write_copy(week_file, sheet, {(2, "E"): 8.0}, {})
    assert hx.verify_copy(week_file, dst, sheet, {(2, "E"): 8.0}) == []
    assert hx.verify_copy(week_file, dst, sheet, {(2, "E"): 7.0})          # inna wartość = błąd
    assert hx.verify_copy(week_file, dst, sheet, {(2, "F"): 8.0})          # inna komórka = błąd


def test_refuses_formula_cells_and_overwriting_original(week_file):
    sheet = hx.read_day_sheet(week_file, "Woensdag")
    total = sheet.columns and hx.col_letter(hx.col_index(list(sheet.columns.values())[-1]) + 1)
    with pytest.raises(hx.HoursFileError):
        hx.write_copy(week_file, sheet, {(2, total): 1.0}, {})
    with pytest.raises(hx.HoursFileError):
        hx.write_copy(week_file, sheet, {(2, "E"): 1.0}, {}, dst=week_file)
    hx.write_copy(week_file, sheet, {(2, "E"): 1.0}, {})
    with pytest.raises(hx.HoursFileError):
        hx.write_copy(week_file, sheet, {(2, "E"): 1.0}, {})               # kopia istnieje
    hx.write_copy(week_file, sheet, {(2, "E"): 2.0}, {}, overwrite=True)


def test_build_changes_rejects_too_many_hours(week_file):
    sheet = hx.read_day_sheet(week_file, "Woensdag")
    lines = [hx.HoursLine(1, "Kowalski Jan", "Reachtruck", "Reach", 10, 2),
             hx.HoursLine(1, "Kowalski Jan", "Laden", "Laden", 8, 2)]
    _, _, errors = hx.build_changes(lines, sheet)
    assert errors


def test_week_check_and_day_sheet():
    assert hx.day_sheet_name(date(2026, 11, 18)) == "Woensdag"
    sheet = hx.DaySheet("x", "Woensdag", "p", {}, "O", [], 47)
    assert hx.check_week(sheet, date(2026, 11, 18)) == ""
    assert "week 46" in hx.check_week(hx.DaySheet("x", "W", "p", {}, "O", [], 46), date(2026, 11, 18))
