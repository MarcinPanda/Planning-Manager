"""Stałe i ustawienia aplikacji."""
import os
import sys
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
DB_PATH = os.path.join(BASE_DIR, "planning_data.db")
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

BACKUP_DIR = os.path.join(BASE_DIR, "backups")   # kopie robione przy starcie
ARCHIVE_DIR = os.path.join(BASE_DIR, "archive")  # kopie robione przed "Clear Data"
BACKUP_KEEP = 10   # ile ostatnich kopii startowych trzymamy
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
