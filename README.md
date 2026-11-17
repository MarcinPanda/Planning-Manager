# Planning Manager

Aplikacja okienkowa (PySide6) do planowania pracy na zmianie: lista pracowników,
przypisania do działów w ciągu dnia, przerwy i automatycznie liczone godziny.

## Uruchomienie

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python planning_manager.py
```

## Budowanie exe

```bash
.venv\Scripts\python -m PyInstaller Planning_Manager.spec --noconfirm --distpath dist --workpath build
```

Wynik: `dist\PlanningManager.exe` (jeden plik, bez instalacji).

## Testy

```bash
.venv\Scripts\python -m pytest tests -q
```

## Gdzie są dane

Wszystko leży w folderze, w którym jest exe (albo z którego uruchomiono skrypt):

| Co | Gdzie |
| --- | --- |
| Baza danych | `planning_data.db` |
| Kopie robione przy każdym starcie (10 ostatnich) | `backups\` |
| Kopie robione przed „Clear Data" | `archive\` |

Nową wersję exe wystarczy wgrać do tego samego folderu – baza zostaje.
Stare bazy są uzupełniane automatycznie przy starcie.

Baza, kopie i pliki Excel zawierają dane pracowników i **nie trafiają do repozytorium**
(patrz `.gitignore`).

## Funkcje

- Import planu z Excela (duplikaty są pomijane, import jest „wszystko albo nic").
- Dodawanie, edycja i usuwanie działów z godziną zmiany; godziny liczone z przerwami,
  zaokrąglane do 0,25 h.
- „Ziek" i „Naar Huis" liczą się jako 0 h; „Naar Huis" skraca godziny pracy (celowo).
- Oznaczanie spóźnienia („Late").
- Kolory wierszy: chory, poszedł do domu, spóźniony.
- Wyszukiwarka (Ctrl+F): nazwisko, dział, godziny, info.
- Cofnij (Ctrl+Z) – 30 ostatnich operacji.
- Historia zmian: kto, kiedy, co.
- Eksport widocznej tabeli do Excela i wydruk z podglądem.
- Auto-odświeżanie co 10 s.

## Układ kodu

| Plik | Zawartość |
| --- | --- |
| `planning_manager.py` | punkt startowy |
| `pm/config.py` | stałe: działy, zmiany, przerwy, kolory, wyjątki dla nazwisk |
| `pm/logic.py` | liczenie godzin, przerwy, nazwiska, klasa `Employee` (bez Qt i bez bazy) |
| `pm/db.py` | baza SQLite, dziennik zmian, cofanie, kopie zapasowe |
| `pm/excel_io.py` | odczyt planu z Excela, eksport |
| `pm/table_model.py` | model tabeli (filtr, sortowanie, kolory) |
| `pm/dialogs.py` | okna dialogowe |
| `pm/widgets.py` | przełącznik, wątki robocze, delegat pola Info |
| `pm/main_window.py` | główne okno |
| `tests/` | testy automatyczne |
| `Planning + Monitoring.py` | projekt poboczny (prototyp widoku Monitoring) – nie jest częścią aplikacji |

## Wersja z Monitoringiem (`planning_monitoring.py`)

Ta sama aplikacja i baza, dodatkowo przełącznik Planning / Monitoring.

- Tablica wszystkich działów; pracownik to kostka z nazwiskiem, loginem i godziną zmiany.
- Przeciągnięcie na inny dział zapisuje zmianę działu z aktualną godziną.
- Piking i Reach Outbound mają pozycje (klienci, strefy). Dla godzin liczy się tylko dział.
- Działy ze strefami (Reach, Orderpick) to tabele jak w Excelu: kliknięcie komórki
  włącza / wyłącza strefę, jedna osoba może mieć kilka stref naraz. „Nanomi Reachtruck" z planu
  to Reach ze strefą Na-Nomi.
- „Import Logins" wczytuje spis loginów z Excela (plik Inlognamen z kodami N012P / R012R albo kolumny `Login:` i `Name:`); loginy są
  dopasowywane po nazwisku i zostają w bazie na kolejne dni.

Budowanie: `.venv\Scripts\python -m PyInstaller Planning_Monitoring.spec --noconfirm --distpath dist --workpath build`

### Widok Consolidatie (lista RIT-ów)

- Przycisk **Consolidatie** u góry przełącza na listę RIT-ów; **Import Consolidatie** wczytuje plik `Consolidatie_2026.xlsx` (zakładka Consolidatie, wiersze z ostatnich 2 dni i kolejnych). Ponowny import dodaje nowe RIT-y i nie nadpisuje tego, co wpisano w aplikacji.
- Kliknięcie w kolumnę **Reacher** = przypisanie reachera (lista osób z działu Reach albo login, np. `R052R`).
- Przypisany reacher, dopóki RIT nie ma **V** (zwiezione), dostaje na Monitoringu strefę **Kantel** (gdy RIT ma palety do kantelowania) i/lub **Consolidatie** (pozostałe palety). Po V wracają jego poprzednie strefy. Godziny nadal liczą się dla Reach.
- **Done** = konsolidacja zrobiona (bez wpływu na strefy). Lane, Comment, Time i liczby palet edytuje się dwuklikiem.
- Plik Excel nie jest zmieniany przez aplikację.
