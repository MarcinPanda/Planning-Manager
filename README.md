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
- Menu widoków po lewej: Planning, Monitoring, Consolidatie (skróty Ctrl+1 / Ctrl+2 / Ctrl+3).
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

## Widok Monitoring

Aplikacja to jeden program z trzema widokami (Planning, Monitoring, Consolidatie) na jednej bazie.
Monitoring to „oczy steeringu": kto gdzie teraz jest i co robi.

- U góry liczniki: na zmianie, Reach, Picking, Inbound, Other, Unassigned, Ziek, Naar Huis.
- Hale **North** i **South** (nagłówek zwija halę): kolumny REACH i PICKING, w nich strefy / klienci.
  Który klient / strefa jest w South – `SOUTH_POSITIONS` w `pm/config.py`; reszta to North.
- **Both halls**: INBOUND (Inbound 1–5) i OTHER (pozostałe działy).
- Panel po prawej: **Unassigned** (Reach bez strefy, Picking bez klienta), Ziek, Naar Huis.
- Pracownik to karta „login – Imię Nazwisko"; `[+2]` = pracuje jeszcze w 2 innych strefach.
- Przeciągnięcie karty = zmiana działu lub strefy od teraz; **Ctrl + przeciągnięcie** = dołożenie
  drugiej strefy; prawy klik → *Zones / clients…* = kilka stref / klientów naraz (ptaszki);
  prawy klik → *Remove from …* = zdjęcie ze strefy; **Ctrl+Z** cofa. Dla godzin liczy się tylko dział.
- **Naar Huis / Ziek**: upuszczenie (albo prawy klik) otwiera okienko: godzina odbicia albo „cały dzień"
  (nie przyszedł / chorobowe od rana = 0 h). Godziny liczą się do tej godziny. Karta zostaje w panelu
  z godziną; prawy klik → *Change time…* / *Back to work*. *Send a group home…* = wiele osób, jedna godzina.
  Godziny z planu są zapamiętane (`planned_hours`), więc zmiana godziny i powrót przywracają je poprawnie.
- **⏮ From start of shift**: dla zmian zgłoszonych z opóźnieniem – przeciągnięcie zmienia dział od
  początku zmiany. Pomarańczowy pasek, gdy włączony; wyłącza się sam 30 min po starcie zmiany.
- Instrukcje pod przyciskiem **?**.
- „Nanomi Reachtruck" z planu to Reach ze strefą Na-Nomi.
- „Import Logins" wczytuje spis loginów z Excela (plik Inlognamen z kodami N012P / R012R albo kolumny `Login:` i `Name:`); loginy są
  dopasowywane po nazwisku i zostają w bazie na kolejne dni.

### Widok Consolidatie (lista RIT-ów)

- Pozycja **Consolidatie** w menu po lewej przełącza na listę RIT-ów; **Import Consolidatie** wczytuje plik `Consolidatie_2026.xlsx` (zakładka Consolidatie, wiersze z ostatnich 2 dni i kolejnych). Ponowny import dodaje nowe RIT-y i nie nadpisuje tego, co wpisano w aplikacji.
- Kliknięcie w kolumnę **Reacher** = przypisanie reachera (lista osób z działu Reach albo login, np. `R052R`).
- Przypisany reacher, dopóki RIT nie ma **V** (zwiezione), dostaje na Monitoringu strefę **Kantel/Consolidatie**. Po V wracają jego poprzednie strefy. Godziny nadal liczą się dla Reach.
- Kliknięcie w **Who was busy** = rozwijana lista osób, które są teraz na dziale Consolidatie/Kantelen (można zaznaczyć kilka albo wpisać kogoś innego).
- **Done** (X) = konsolidacja zrobiona (bez wpływu na strefy); takie RIT-y są domyślnie ukryte ("Hide done"). Lane, Comment, Time i liczby palet edytuje się dwuklikiem.
- Plik Excel nie jest zmieniany przez aplikację.
