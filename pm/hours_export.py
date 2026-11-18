"""Etap 6: godziny zmiany do pliku Uren_Lijst (tygodniowy plik dla księgowości).

Zasady bezpieczeństwa:
- oryginał jest tylko czytany; zapis idzie do kopii `<nazwa>_copy.xlsx`;
- zmieniane są wyłącznie komórki godzin (i uwag) wybranych osób w arkuszu wybranego dnia;
- reszta pliku jest przepisywana bez zmian (plik jest „udostępnionym skoroszytem" z historią zmian –
  biblioteki typu openpyxl zgubiłyby ją, dlatego zmieniamy sam XML arkusza);
- po zapisie kopia jest czytana z powrotem i porównywana z oryginałem; każda różnica poza zamierzonymi
  komórkami = kopia jest usuwana i zgłaszany jest błąd.

Moduł nie używa Qt.
"""
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from . import config
from .logic import Validator, compute_hours_with_breaks, interval_hours_with_breaks, name_key, round_to_quarter, to_minutes

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
WORKBOOK_PART = "xl/workbook.xml"

ROW_RE = re.compile(r'<row r="(\d+)"[^>]*?(?:/>|>.*?</row>)', re.S)
CELL_RE = re.compile(r'<c r="([A-Z]+)(\d+)"([^>]*?)(/>|>(.*?)</c>)', re.S)
CALC_PR_RE = re.compile(r"<calcPr\b[^>]*?/>")


class HoursFileError(Exception):
    """Plik godzin ma inny układ niż oczekiwany albo zapis / weryfikacja się nie udały."""


# ------------------------------------------------------------------ pomocnicze
def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def col_letter(index):
    letters = ""
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def _norm_header(text):
    return " ".join(str(text or "").split()).casefold()


def week_from_filename(path):
    match = re.search(r"week[\s_-]*(\d{1,2})", os.path.basename(path), re.I)
    return int(match.group(1)) if match else None


def day_sheet_name(day):
    return config.HOURS_DAY_SHEETS[day.weekday()]


def copy_path(path):
    stem, ext = os.path.splitext(path)
    return f"{stem}_copy{ext or '.xlsx'}"


def original_path(path):
    """Gdy ktoś wybrał samą kopię (…_copy.xlsx) – ścieżka oryginału."""
    stem, ext = os.path.splitext(path)
    return stem[: -len("_copy")] + ext if stem.lower().endswith("_copy") else path


def _fmt_number(value):
    value = round(float(value), 4)
    return str(int(value)) if value == int(value) else repr(value)


def _shared_strings(zf):
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(f"{NS}t")) for si in root.iter(f"{NS}si")]


def _sheet_parts(zf):
    """{nazwa arkusza: ścieżka części XML w pliku}."""
    workbook = ET.fromstring(zf.read(WORKBOOK_PART))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels.iter(f"{PKG_REL_NS}Relationship")}
    parts = {}
    for sheet in workbook.iter(f"{NS}sheet"):
        target = targets.get(sheet.get(f"{REL_NS}id"), "")
        target = target.lstrip("/")
        parts[sheet.get("name")] = target if target.startswith("xl/") else f"xl/{target}"
    return parts


def _cell_value(cell, strings):
    kind = cell.get("t", "n")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(f"{NS}t"))
    v = cell.find(f"{NS}v")
    if v is None or v.text is None:
        return None
    if kind == "s":
        return strings[int(v.text)]
    if kind in ("str", "e"):
        return v.text
    if kind == "b":
        return v.text == "1"
    try:
        number = float(v.text)
    except ValueError:
        return v.text
    return int(number) if number == int(number) else number


# ------------------------------------------------------------------ odczyt
@dataclass
class SheetRow:
    row: int
    name: str
    values: dict          # {litera kolumny: wartość} – istniejące godziny (C…AI)
    note: str = ""
    formulas: set = field(default_factory=set)   # kolumny z formułą (nie wolno w nie pisać)


@dataclass
class DaySheet:
    path: str
    sheet_name: str
    part: str
    columns: dict          # {nagłówek: litera} – kolumny godzin w kolejności
    note_column: str
    rows: list
    week: int = None

    def letter_for(self, header):
        wanted = _norm_header(header)
        for name, letter in self.columns.items():
            if _norm_header(name) == wanted:
                return letter
        return None


def read_day_sheet(path, sheet_name):
    """Czyta arkusz dnia (tylko do odczytu): kolumny godzin, osoby z wierszami i to, co już jest wpisane."""
    with zipfile.ZipFile(path) as zf:
        parts = _sheet_parts(zf)
        if sheet_name not in parts:
            raise HoursFileError(f"The file has no sheet '{sheet_name}'.")
        strings = _shared_strings(zf)
        root = ET.fromstring(zf.read(parts[sheet_name]))

    data = root.find(f"{NS}sheetData")
    cells = {}
    formulas = {}
    for row in data.iter(f"{NS}row"):
        r = int(row.get("r"))
        for cell in row.iter(f"{NS}c"):
            match = re.match(r"([A-Z]+)(\d+)$", cell.get("r", ""))
            if not match:
                continue
            letter = match.group(1)
            cells[(r, letter)] = _cell_value(cell, strings)
            f = cell.find(f"{NS}f")
            if f is not None:
                formulas[(r, letter)] = f.text or ""

    headers = {}
    letters_in_row1 = sorted((col_index(letter), letter) for (r, letter) in cells if r == 1)
    for _, letter in letters_in_row1:
        headers[letter] = str(cells[(1, letter)] or "").strip()
    total_letter = next((l for l, h in headers.items() if _norm_header(h) == "totaal"), None)
    note_letter = next((l for l, h in headers.items() if _norm_header(h) == "opmerking"), None)
    if not total_letter or not note_letter:
        raise HoursFileError(f"Sheet '{sheet_name}' has no 'Totaal' / 'Opmerking' header in row 1.")
    first, last = 3, col_index(total_letter) - 1
    columns = {}
    for idx in range(first, last + 1):
        letter = col_letter(idx)
        if headers.get(letter):
            columns[headers[letter]] = letter
    if len(columns) < 10:
        raise HoursFileError(f"Sheet '{sheet_name}' does not look like an hours sheet (too few columns).")

    rows = []
    max_row = max((r for r, _ in cells), default=1)
    for r in range(2, max_row + 1):
        formula = formulas.get((r, "A"), "")
        ref = re.search(r"Namen!\$?A\$?(\d+)", formula)
        name = cells.get((r, "A"))
        if not ref or int(ref.group(1)) != r or not name:
            continue   # wiersz sum, wiersz z limitem albo pusty wiersz
        values = {}
        row_formulas = set()
        for letter in columns.values():
            if (r, letter) in formulas:
                row_formulas.add(letter)
            value = cells.get((r, letter))
            if value not in (None, ""):
                values[letter] = value
        rows.append(SheetRow(r, str(name).strip(), values, str(cells.get((r, note_letter)) or ""), row_formulas))

    return DaySheet(path, sheet_name, parts[sheet_name], columns, note_letter, rows, week_from_filename(path))


# ------------------------------------------------------------------ propozycja
@dataclass
class HoursLine:
    employee_id: int
    person: str
    department: str
    column: str            # nagłówek kolumny w pliku ('' = do wybrania)
    hours: float
    row: int = None        # wiersz w arkuszu dnia (None = osoby nie ma w pliku)
    excel_name: str = ""
    note: str = ""         # tekst do dopisania w uwagach (tylko w pierwszej linii osoby)
    include: bool = True
    status: str = ""


def match_rows(sheet):
    """{klucz nazwiska: [wiersze]}"""
    index = {}
    for row in sheet.rows:
        index.setdefault(name_key(row.name), []).append(row)
    return index


def find_row(index, key):
    rows = index.get(key)
    if rows is None:
        words = set(key.split())
        candidates = [k for k in index if words and (words <= set(k.split()) or set(k.split()) <= words)]
        if len(candidates) != 1:
            return None, "not found in sheet 'Namen'" if not candidates else "several similar names in the file"
        rows = index[candidates[0]]
    if len(rows) > 1:
        return None, "name appears more than once in the file"
    return rows[0], ""


def leave_note(employee):
    parts = []
    if employee.late:
        parts.append("late")
    for dept, time in employee.dept_times:
        kind = dept.strip().lower()
        if kind == "naar huis":
            parts.append(f"went home {time}" if time else "absent")
        elif kind == "ziek":
            parts.append(f"sick {time}" if time else "sick")
    return " / ".join(parts)


def department_note(intervals, zone_hours=0.0):
    """Dopisek dla działów liczonych w innej kolumnie, np. „3h Buffer", i dla czasu w strefie Reflex."""
    totals = {}
    for dept, hours in intervals:
        label = config.HOURS_NOTE_DEPARTMENTS.get(dept)
        if label and hours:
            totals[label] = totals.get(label, 0.0) + hours
    if zone_hours:
        label = config.HOURS_NOTE_DEPARTMENTS.get("Reflex", "reflex")
        totals[label] = totals.get(label, 0.0) + zone_hours
    return " / ".join(f"{hours:g}h {label}" for label, hours in totals.items())


def zone_hours(employee, periods):
    """Godziny pracy (z przerwami) w okresach strefy, przycięte do godzin pracy osoby; co 0,25 h."""
    hours_text = employee.work_hours if isinstance(employee.work_hours, str) else ""
    if "-" not in hours_text or not periods:
        return 0.0
    start_s, end_s = (p.strip() for p in hours_text.split("-", 1))
    if not (Validator.validate_time_format(start_s) and Validator.validate_time_format(end_s)):
        return 0.0
    start, end = to_minutes(start_s), to_minutes(end_s)
    if end <= start:
        end += 24 * 60

    def rel(text, default):
        if not text or not Validator.validate_time_format(text):
            return default
        m = to_minutes(text)
        return m + 24 * 60 if m < start - 6 * 60 else m   # po północy na zmianie nocnej

    total = 0.0
    for time_from, time_to in periods:
        s, e = max(rel(time_from, start), start), min(rel(time_to, end), end)
        if e <= s:
            continue
        span = f"{s // 60 % 24:02d}:{s % 60:02d}-{e // 60 % 24:02d}:{e % 60:02d}"
        if employee.shift == "Custom":
            total += compute_hours_with_breaks(span, "Custom", employee.custom_breaks)
        else:
            total += interval_hours_with_breaks(s % (24 * 60), e % (24 * 60), employee.shift)
    return round_to_quarter(total)


def default_column(department, remembered=None):
    remembered = remembered or {}
    return remembered.get(department) or config.HOURS_COLUMN_MAP.get(department, "")


def propose(employees, sheet, remembered=None, zones=None):
    """Linie „osoba – dział – kolumna – godziny" do podglądu. Nic nie zapisuje.

    zones = {employee_id: [(od, do)]} – okresy w strefie Reflex (dopisek „Xh reflex")."""
    zones = zones or {}
    index = match_rows(sheet)
    lines = []
    known = {_norm_header(h) for h in sheet.columns}
    for emp in sorted(employees, key=lambda e: (e.lastname.lower(), e.firstname.lower())):
        person = f"{emp.lastname} {emp.firstname}".strip()
        row, problem = find_row(index, name_key(emp.firstname, emp.lastname))
        intervals = [(d, round_to_quarter(h)) for d, h in emp.dept_intervals if round_to_quarter(h) > 0]
        reflex = zone_hours(emp, zones.get(emp.employee_id, []))
        note = " / ".join(filter(None, [department_note(intervals, reflex), leave_note(emp)]))
        if not intervals:
            dept = emp.active_department or emp.current_department
            intervals = [(dept, 0.0)]
        for i, (dept, hours) in enumerate(intervals):
            column = default_column(dept, remembered) if hours else ""
            if column and _norm_header(column) not in known:
                column = ""
            line = HoursLine(emp.employee_id, person, dept, column, hours,
                             row.row if row else None, row.name if row else "", note if i == 0 else "")
            if row is None:
                line.include, line.status = False, problem
            elif row.values:
                filled = ", ".join(f"{_header_of(sheet, l)} {v}" for l, v in row.values.items())
                line.include, line.status = False, f"already filled: {filled}"
            elif hours == 0:
                line.include = bool(line.note)
                line.status = "0 h – only the note" if line.note else "0 h"
            elif not column:
                line.status = "choose a column"
            lines.append(line)
    return lines


def _header_of(sheet, letter):
    return next((h for h, l in sheet.columns.items() if l == letter), letter)


def build_changes(lines, sheet):
    """Z zaznaczonych linii: ({(wiersz, litera): godziny}, {wiersz: nowe uwagi}, [błędy])."""
    values, notes, errors = {}, {}, []
    rows = {r.row: r for r in sheet.rows}
    for line in lines:
        if not line.include:
            continue
        if line.row not in rows:
            errors.append(f"{line.person}: not in the file.")
            continue
        if line.hours < 0 or line.hours > config.HOURS_MAX_PER_PERSON:
            errors.append(f"{line.person}: {line.hours} h is not possible.")
            continue
        if line.hours:
            letter = sheet.letter_for(line.column) if line.column else None
            if not letter:
                errors.append(f"{line.person} ({line.department}): choose a column.")
                continue
            if letter in rows[line.row].formulas:
                errors.append(f"{line.person}: column {line.column} contains a formula.")
                continue
            key = (line.row, letter)
            values[key] = round(values.get(key, 0.0) + line.hours, 2)
        if line.note:
            existing = notes.get(line.row, rows[line.row].note).strip()
            if line.note.casefold() not in existing.casefold():
                notes[line.row] = f"{existing} / {line.note}" if existing else line.note
    for row_number in {r for r, _ in values}:
        total = sum(v for (r, _), v in values.items() if r == row_number)
        total += sum(v for l, v in rows[row_number].values.items()
                     if isinstance(v, (int, float)) and (row_number, l) not in values)
        if total > config.HOURS_MAX_PER_PERSON:
            errors.append(f"{rows[row_number].name}: {total} h in one day.")
    return values, notes, errors


# ------------------------------------------------------------------ zapis
def _col_styles(sheet_xml):
    """{numer kolumny: styl} z sekcji <cols> – styl dla komórek, których jeszcze nie ma."""
    styles = {}
    for match in re.finditer(r"<col\b([^>]*)/>", sheet_xml):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', match.group(1)))
        if "style" in attrs:
            for i in range(int(attrs["min"]), int(attrs["max"]) + 1):
                styles[i] = attrs["style"]
    return styles


def _cell_xml(ref, attrs, value):
    attrs = re.sub(r'\s+t="[^"]*"', "", attrs)
    if isinstance(value, str):
        text = escape(value)
        return f'<c r="{ref}"{attrs} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'
    return f'<c r="{ref}"{attrs}><v>{_fmt_number(value)}</v></c>'


def _patch_row(row_xml, row_number, updates, styles):
    """Podmienia / dodaje komórki w jednym wierszu (updates = {litera: wartość})."""
    if row_xml.endswith("/>"):
        raise HoursFileError(f"Row {row_number} has no cells – unexpected layout.")
    open_end = row_xml.index(">") + 1
    head, body, tail = row_xml[:open_end], row_xml[open_end:-len("</row>")], "</row>"
    pending = dict(updates)
    out, pos = [], 0
    for match in CELL_RE.finditer(body):
        letter, r = match.group(1), int(match.group(2))
        if r != row_number:
            raise HoursFileError(f"Unexpected cell {letter}{r} in row {row_number}.")
        index = col_index(letter)
        out.append(body[pos:match.start()])
        for new_letter in sorted((l for l in pending if col_index(l) < index), key=col_index):
            style = styles.get(col_index(new_letter))
            out.append(_cell_xml(f"{new_letter}{row_number}", f' s="{style}"' if style else "", pending.pop(new_letter)))
        if letter in pending:
            if "<f>" in (match.group(5) or "") or "<f " in (match.group(5) or ""):
                raise HoursFileError(f"Cell {letter}{row_number} contains a formula – not overwritten.")
            out.append(_cell_xml(f"{letter}{row_number}", match.group(3), pending.pop(letter)))
        else:
            out.append(match.group(0))
        pos = match.end()
    out.append(body[pos:])
    for new_letter in sorted(pending, key=col_index):
        style = styles.get(col_index(new_letter))
        out.append(_cell_xml(f"{new_letter}{row_number}", f' s="{style}"' if style else "", pending[new_letter]))
    return head + "".join(out) + tail


def patch_sheet_xml(sheet_xml, cell_updates):
    """cell_updates = {(wiersz, litera): wartość}. Zwraca nowy XML arkusza; zmienia tylko te komórki."""
    by_row = {}
    for (r, letter), value in cell_updates.items():
        by_row.setdefault(r, {})[letter] = value
    styles = _col_styles(sheet_xml)
    seen = set()

    def repl(match):
        r = int(match.group(1))
        if r not in by_row:
            return match.group(0)
        seen.add(r)
        return _patch_row(match.group(0), r, by_row[r], styles)

    start = sheet_xml.index("<sheetData")
    end = sheet_xml.index("</sheetData>")
    patched = sheet_xml[:start] + ROW_RE.sub(repl, sheet_xml[start:end]) + sheet_xml[end:]
    missing = set(by_row) - seen
    if missing:
        raise HoursFileError(f"Rows not found in the sheet: {sorted(missing)}")
    return patched


def patch_workbook_xml(workbook_xml):
    """Excel ma przeliczyć sumy (AJ, wiersz sum, Namen, Overview) przy otwarciu kopii."""
    match = CALC_PR_RE.search(workbook_xml)
    if match:
        tag = match.group(0)
        if "fullCalcOnLoad" in tag:
            return workbook_xml
        return workbook_xml.replace(tag, tag[:-2].rstrip() + ' fullCalcOnLoad="1"/>', 1)
    return workbook_xml.replace("</workbook>", '<calcPr fullCalcOnLoad="1"/></workbook>', 1)


def _cell_map(sheet_xml):
    start = sheet_xml.index("<sheetData")
    end = sheet_xml.index("</sheetData>")
    data = sheet_xml[start:end]
    cells = {f"{m.group(1)}{m.group(2)}": m.group(0) for m in CELL_RE.finditer(data)}
    rows = [re.match(r"<row\b[^>]*>", m.group(0)).group(0) for m in ROW_RE.finditer(data)]
    return sheet_xml[:start], sheet_xml[end:], rows, cells


def verify_copy(src, dst, sheet, cell_updates):
    """Kopia = oryginał z wyjątkiem zamierzonych komórek. Zwraca listę różnic (pusta = OK)."""
    problems = []
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(dst) as b:
        if b.testzip() is not None:
            return ["The copy is damaged (zip check failed)."]
        if a.namelist() != b.namelist():
            return ["The copy has different parts than the original."]
        for name in a.namelist():
            if name in (sheet.part, WORKBOOK_PART):
                continue
            if a.read(name) != b.read(name):
                problems.append(f"Part {name} differs.")
        if patch_workbook_xml(a.read(WORKBOOK_PART).decode("utf-8")) != b.read(WORKBOOK_PART).decode("utf-8"):
            problems.append("Workbook settings differ more than expected.")
        orig_xml = a.read(sheet.part).decode("utf-8")
        copy_xml = b.read(sheet.part).decode("utf-8")
        strings = _shared_strings(b)

    try:
        ET.fromstring(copy_xml.encode("utf-8"))
    except ET.ParseError as exc:
        return problems + [f"The changed sheet is not valid XML: {exc}"]

    head_a, tail_a, rows_a, cells_a = _cell_map(orig_xml)
    head_b, tail_b, rows_b, cells_b = _cell_map(copy_xml)
    if head_a != head_b or tail_a != tail_b or rows_a != rows_b:
        problems.append("Sheet layout (outside the hours cells) differs.")
    expected = {f"{letter}{r}": value for (r, letter), value in cell_updates.items()}
    for ref in set(cells_a) | set(cells_b):
        if ref in expected:
            continue
        if cells_a.get(ref) != cells_b.get(ref):
            problems.append(f"Cell {ref} changed unexpectedly.")
    for ref, value in expected.items():
        xml = cells_b.get(ref)
        if xml is None:
            problems.append(f"Cell {ref} was not written.")
            continue
        got = _cell_value(ET.fromstring(xml.replace("<c ", f'<c xmlns="{NS[1:-1]}" ', 1)), strings)
        if isinstance(value, str):
            ok = got == value
        else:
            ok = isinstance(got, (int, float)) and abs(float(got) - float(value)) < 1e-9
        if not ok:
            problems.append(f"Cell {ref}: expected {value!r}, found {got!r}.")
    return problems


def write_copy(src, sheet, values, notes, dst=None, overwrite=False, original=None):
    """Zapisuje kopię z godzinami i ją weryfikuje. Zwraca ścieżkę kopii.

    src = plik bazowy: oryginał albo istniejąca kopia (dopisywanie kolejnej zmiany do tej samej kopii –
    wtedy `original` = ścieżka oryginału, który nigdy nie jest nadpisywany).
    values = {(wiersz, litera): godziny}, notes = {wiersz: pełny tekst uwag}.
    """
    original = original or src
    dst = dst or copy_path(original)
    if os.path.normcase(os.path.abspath(dst)) == os.path.normcase(os.path.abspath(original)):
        raise HoursFileError("The copy cannot be the original file.")
    if os.path.exists(dst) and not overwrite:
        raise HoursFileError(f"{os.path.basename(dst)} already exists.")
    updates = dict(values)
    for row, text in notes.items():
        updates[(row, sheet.note_column)] = text
    if not updates:
        raise HoursFileError("Nothing to write.")

    tmp = dst + ".tmp"
    try:
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w") as zout:
            for info in zin.infolist():
                data = zin.read(info.filename)
                if info.filename == sheet.part:
                    data = patch_sheet_xml(data.decode("utf-8"), updates).encode("utf-8")
                elif info.filename == WORKBOOK_PART:
                    data = patch_workbook_xml(data.decode("utf-8")).encode("utf-8")
                zout.writestr(info, data, compress_type=info.compress_type)
        problems = verify_copy(src, tmp, sheet, updates)
        if problems:
            raise HoursFileError("Check after writing failed – the copy was removed:\n" + "\n".join(problems[:10]))
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return dst


def check_week(sheet, day):
    """Ostrzeżenie, gdy numer tygodnia w nazwie pliku nie pasuje do daty zmiany ('' = OK)."""
    week = day.isocalendar()[1]
    if sheet.week is None:
        return f"The file name has no week number (shift is in week {week})."
    if sheet.week != week:
        return f"The file is for week {sheet.week}, but the shift ({day:%d-%m-%Y}) is in week {week}."
    return ""


def parse_date(text):
    return date.fromisoformat(text)
