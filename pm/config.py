"""Stałe i ustawienia aplikacji."""
import os
import sys
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()

# Gdzie leży baza: plik settings.ini obok programu, sekcja [database], klucz folder
# (np. folder na dysku sieciowym wspólny dla wszystkich komputerów). Brak pliku = folder programu.
SETTINGS_PATH = os.path.join(BASE_DIR, "settings.ini")
DB_FILENAME = "planning_data.db"


def read_database_folder():
    import configparser
    parser = configparser.ConfigParser()
    try:
        parser.read(SETTINGS_PATH, encoding="utf-8")
        folder = parser.get("database", "folder", fallback="").strip()
    except Exception:
        folder = ""
    return folder or BASE_DIR


def write_database_folder(folder):
    import configparser
    parser = configparser.ConfigParser()
    parser.read(SETTINGS_PATH, encoding="utf-8")
    if not parser.has_section("database"):
        parser.add_section("database")
    parser.set("database", "folder", folder)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
        handle.write("; Planning Manager – folder ze wspólną bazą (np. dysk sieciowy)\n")
        parser.write(handle)


def use_database_folder(folder):
    """Ustawia ścieżki bazy, kopii i archiwum na podany folder."""
    global DB_FOLDER, DB_PATH, BACKUP_DIR, ARCHIVE_DIR
    DB_FOLDER = folder
    DB_PATH = os.path.join(folder, DB_FILENAME)
    BACKUP_DIR = os.path.join(folder, "backups")   # kopie robione przy starcie i co godzinę
    ARCHIVE_DIR = os.path.join(folder, "archive")  # kopie robione przed usunięciem zmiany


DB_FOLDER = DB_PATH = BACKUP_DIR = ARCHIVE_DIR = ""
use_database_folder(read_database_folder())
REFRESH_CHECK_MS = 3_000   # co tyle sprawdzamy, czy ktoś inny coś zmienił
SYNC_INTERVAL_MS = 10_000  # auto-odświeżanie tabeli

NAME_EXCEPTIONS = ["van", "vas", "dos", "al"]

TEAM_LIST = [
    "Accu", "Ass TL", "Buffer", "Consolidatie/Kantelen", "Controle", "Cycle Count", "Emballage", "Extra",
    "Fixing Pallets", "Helpdesk", "Inbound 1", "Inbound 2", "Inbound 3", "Inbound 4", "Inbound 5", "Klusje/Racking",
    "Laco", "Laden", "Logistiek coördinator", "Naar Huis", "Opleiding", "Orderpicker", "Pendel", "Project", "Reachtruck", "Reflex",
    "Retouren", "Shiftleader", "Schoonmaak", "Stock Control", "Sturing", "Teamleader", "VAL", "Ziek",
    # działy, które występują w planie z Excela
    "Inleren Orderpicker", "Inleren Reachtruck", "Stuwarooij/Omstapelen",
]
TEAM_LIST.sort(key=lambda x: x.lower())

SHIFT_LIST = ["Ochtend", "Middag", "Day8to17", "Custom"]
SHIFT_DEFAULT_HOURS = {"Ochtend": "06:00-15:00", "Middag": "15:00-00:00", "Day8to17": "08:00-17:00"}
# Godziny „od północy do północy" w planie: rezerwa albo błąd – po imporcie pytamy, co z nimi zrobić.
EMPTY_PLAN_HOURS = "00:00-00:00"

columns = (
    "marked", "lastname", "firstname", "work_hours", "computed_hours",
    "current_department", "time_dept1", "dept2", "time_dept2", "dept3", "time_dept3",
    "dept4", "time_dept4", "dept5", "time_dept5", "info"
)

col_names = [
    "Marked", "Last Name", "First Name", "Work Hours", "Total Work Time",
    "Department 1", "Work Time 1", "Department 2", "Work Time 2", "Department 3", "Work Time 3",
    "Department 4", "Work Time 4", "Department 5", "Work Time 5", "Info"
]

OCHTEND_BREAKS = [(8 * 60 + 15, 8 * 60 + 30), (10 * 60 + 30, 10 * 60 + 45), (12 * 60 + 30, 13 * 60)]
MIDDAG_BREAKS = [(17 * 60 + 15, 17 * 60 + 30), (19 * 60 + 30, 20 * 60), (22 * 60, 22 * 60 + 15)]
DAY8TO17_BREAKS = [(10 * 60 + 30, 10 * 60 + 45), (12 * 60 + 30, 13 * 60), (15 * 60, 15 * 60 + 15)]

SPECIAL_FUNCTIONS = ["Ass TL", "Help Desk", "Teamleider", "Transport coördinator", "Shiftleader", "Sturing"]

# Wyjątki dla konkretnych osób (wcześniej rozsiane po kodzie jako "if nazwisko == ...").
# Klucze małymi literami.
LASTNAME_CORRECTIONS = {
    "azevedo carvalho": "Carvalho Azevedo",
    "juliao": "Ramos Juliao",
    "wlodarczyk": "Wlodarkiewicz",
}
DEPARTMENT_OVERRIDES = [
    {
        "lastname": "buczkowski",
        "firstname": "rafal",
        "from": ["laco", "transport coördinator"],
        "to": "Logistiek coördinator",
    },
]

# Działy liczone jako 0 h
ZERO_HOUR_DEPARTMENTS = ["ziek", "naar huis"]

BACKUP_KEEP = 10   # ile ostatnich kopii startowych trzymamy
HOURLY_BACKUP_KEEP = 24   # kopie co godzinę (ostatnia doba)
UNDO_DEPTH = 30    # ile ostatnich operacji da się cofnąć
LOG_KEEP = 5000    # ile wpisów dziennika trzymamy

# Kolory wierszy (tło)
ROW_COLOR_SICK = "#F8C9C9"
ROW_COLOR_HOME = "#D9D9D9"
ROW_COLOR_LATE = "#FFE2A8"

# Monitoring: pozycje wewnątrz działu (klient / strefa). Dla godzin liczy się tylko dział.
SUB_POSITIONS = {
    "Reachtruck": [
        "Noord", "Replenish", "Na-Nomi", "Kantel/Consolidatie", "Extra",   # North
        "Zuid", "Mars ITR", "Grenade", "Jordan", "Reflex",                 # South
    ],
    "Orderpicker": [
        "Choco (12)", "Pladis (22)", "Ferrero (27+28)", "Nutricia (10)", "Riverside (21)",  # North
        "Alpro (23)", "Petfood (13)", "Essity (14)", "Pietercil (15)", "Tlant (25)",
        "Mars GUM", "Mars ITR (18 20)", "Grenade", "Jordan", "Reflex",                       # South
    ],
}
SUB_POSITION_TITLES = {
    "Reachtruck": "Reach",
    "Orderpicker": "Picking",
}

# Hale magazynu na tablicy Monitoring. Strefy / klienci z listy SOUTH są w hali South,
# wszystkie inne strefy Reach i Picking w North. Pozostałe działy są wspólne dla obu hal.
HALLS = ("North", "South")
SOUTH_POSITIONS = {
    "Reachtruck": {"Zuid", "Mars ITR", "Grenade", "Jordan", "Reflex"},
    "Orderpicker": {"Mars GUM", "Mars ITR (18 20)", "Grenade", "Jordan", "Reflex"},
}
INBOUND_PREFIX = "Inbound"   # działy „Inbound 1..5" -> kolumna INBOUND


def hall_of(department, position):
    return "South" if position in SOUTH_POSITIONS.get(department, ()) else "North"


# Stare nazwy stref zapisane w bazie -> nowe (zamieniane przy starcie)
POSITION_RENAMES = {
    "Kantel": "Kantel/Consolidatie",
    "Consolidatie": "Kantel/Consolidatie",
    "ITR (18 20)": "Mars ITR (18 20)",
    "Mars GAM": "Mars GUM",
}

# Tryb „od początku zmiany" wyłącza się sam po tylu minutach od startu zmiany
FROM_START_WINDOW_MIN = 30

# Działy z planu, które w aplikacji są strefą innego działu: nazwa (małe litery) -> (dział, strefa).
# Godziny liczą się dla działu (Na-Nomi = Reach).
DEPARTMENT_AS_POSITION = {
    "nanomi reachtruck": ("Reachtruck", "Na-Nomi"),
    "na-nomi reachtruck": ("Reachtruck", "Na-Nomi"),
    "nanomi": ("Reachtruck", "Na-Nomi"),
    "na-nomi": ("Reachtruck", "Na-Nomi"),
}
MONITORING_GRID_COLUMNS = 8

# Nazwy działów z planu w Excelu -> nazwy w aplikacji (klucze małymi literami)
# Lista konsolidacji: reacher przypisany do RIT-u dostaje w dziale Reach strefę Kantel/Consolidatie,
# dopóki RIT nie ma „V" (zwiezione). Potem wracają jego poprzednie strefy.
CONSOLIDATION_DEPARTMENT = "Reachtruck"
CONSOLIDATION_ZONE = "Kantel/Consolidatie"
CONSOLIDATION_OLD_ZONES = ("Kantel", "Consolidatie")  # dawne osobne strefy (patrz POSITION_RENAMES)
CONSOLIDATION_WORK_DEPARTMENT = "Consolidatie/Kantelen"  # kto robi konsolidację – lista w „Who was busy"
CONSOLIDATION_IMPORT_DAYS = 2   # import z Excela: wiersze od (dziś - N dni)
CONSOLIDATION_ACTIVE_DAYS = 1   # otwarte RIT-y starsze niż (dziś - N dni) nie zmieniają już stref

DEPARTMENT_ALIASES = {
    "consolidatie": "Consolidatie/Kantelen",
    "transport coördinator": "Laco",
    "transport coordinator": "Laco",
    "bufferzone": "Buffer",
    "stock controle": "Stock Control",
    "overig": "Extra",
    "rangeren": "Pendel",
    "inleren orderpick": "Inleren Orderpicker",
    "inleren picking": "Inleren Orderpicker",
}

# Etap 6 – godziny do pliku Uren_Lijst (arkusz dnia): dział z planu → nagłówek kolumny w pliku.
# Działy, których tu nie ma (Extra, Reflex), wybiera się w podglądzie; wybór jest zapamiętany.
HOURS_COLUMN_MAP = {
    "Teamleader": "Teamleader",
    "Ass TL": "Assistent Teamleader",
    "Shiftleader": "Shiftleader",
    "Logistiek coördinator": "Logistiek Coordinator",
    "Sturing": "Warehouse Sturing",
    "Helpdesk": "Helpdesk",
    "Stock Control": "Stock Control",
    "Laco": "Laco",
    "Inbound 1": "Lossen - inslag controle",
    "Inbound 2": "Lossen - inslag controle",
    "Inbound 3": "Lossen - inslag controle",
    "Inbound 4": "Lossen - inslag controle",
    "Inbound 5": "Lossen - inslag controle",
    "Retouren": "Retouren",
    "Reachtruck": "Reach",
    "Orderpicker": "Orderpicking",
    "Consolidatie/Kantelen": "Kantelen",
    "Controle": "Controle / Formeren",
    "Laden": "Laden",
    "VAL": "Herstelplein (VAL)",
    "Cycle Count": "Cycle count",
    "Schoonmaak": "Schoonmaak",
    "Opleiding": "Opleiding",
    "Inleren Orderpicker": "Opleiding",
    "Inleren Reachtruck": "Opleiding",
    "Emballage": "Emballage",
    "Accu": "Accu",
    "Pendel": "Pendel Chauffeur",
    "Klusje/Racking": "Klusjes / racking",
    "Project": "Projecten",
    "Buffer": "Orderpicking",            # bufferzone = picking + dopisek w uwagach
    "Fixing Pallets": "Herstelplein (VAL)",
}
# Działy, których godziny dostają dopisek w uwagach, np. „3h Buffer" (Reflex = inny system; kolumnę wybiera się
# w podglądzie: Picking / Reach / Consolidatie / Kantelen).
HOURS_NOTE_DEPARTMENTS = {"Buffer": "Buffer", "Reflex": "reflex"}
HOURS_DAY_SHEETS = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]
HOURS_MAX_PER_PERSON = 16.0   # więcej godzin jednej osoby w jednym dniu = na pewno błąd
