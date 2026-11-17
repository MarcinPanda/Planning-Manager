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
