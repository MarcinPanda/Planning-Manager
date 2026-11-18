# Baza danych Planning Manager (wersja układu 2)

Plik SQLite `planning_data.db` w folderze z `settings.ini`:

```ini
[database]
folder = \\serwer\udzial\PlanningManager
```

Plik `settings.ini` leży obok programu. Bez niego baza jest w folderze programu.
Obok bazy są `backups/` (kopie: przy starcie, co godzinę, przed zmianą układu) i `archive/` (przed usunięciem zmiany).

Wersja układu: `PRAGMA user_version` (obecnie 2). Program sam przenosi starsze bazy, a przedtem robi kopię
`backups/before_schema_v2_*.db`.

## Zasady dla innych aplikacji (np. wydawanie materiałów)

- **Tylko odczyt.** Zapisuje wyłącznie Planning Manager.
- Krótkie połączenia: otwórz, przeczytaj, zamknij. Ustaw `timeout` / `busy_timeout` około 30 s, bo baza leży na
  dysku sieciowym, a inny komputer może akurat zapisywać.
- Nie włączaj trybu WAL (nie działa przez udział sieciowy).
- Żeby wykryć zmiany, czytaj `meta.value` dla `key = 'changes'`. Licznik rośnie przy każdej zmianie danych.

## Tabele

| Tabela | Co zawiera | Najważniejsze kolumny |
| --- | --- | --- |
| `shifts` | zmiany: dzień + nazwa | `id`, `date` (YYYY-MM-DD), `name` (Ochtend / Middag), `created`, `created_by` |
| `employees` | osoba na danej zmianie | `id`, `shift_id` → shifts, `lastname`, `firstname`, `current_department` (dział z planu), `work_hours` (np. 15:00-00:00, skrócone przez Naar Huis), `planned_hours` (z planu), `shift`, `computed_hours`, `position` (strefy / klienci rozdzieleni `;`), `late`, `info`, `marked` |
| `departments` | przebieg działów osoby w ciągu zmiany | `employee_id`, `department`, `time_assigned` (pusty = od początku zmiany), kolejność wg `id` |
| `logins` | spis loginów (z Inlognamen) | `name_key` (znormalizowane imię i nazwisko), `name`, `login` (np. `012` = N012P / R012R) |
| `consolidation` | lista RIT-ów | `datum`, `rit`, `seq`, `area`, `time`, `amount`, `kantel`, `reachers` (loginy lub `id:N`, `;`), `v`, `done`, `lane`, `comment`, `busy` |
| `consolidation_prev` | strefy reachera sprzed RIT-u | `employee_id`, `positions` |
| `change_log` | dziennik zmian (kto, kiedy, co) + dane do Cofnij | `ts`, `user`, `action`, `details`, `undo_data`, `undone` |
| `zone_periods` | kiedy osoba weszła do strefy Reflex i z niej wyszła (zapisują to wyzwalacze przy każdej zmianie `employees.position`) | `employee_id`, `zone`, `time_from` (HH:MM, pusty = od początku zmiany), `time_to` (NULL = nadal w strefie) |
| `meta` | licznik zmian | `key = 'changes'`, `value` |

## Przykład: kto jest teraz w pracy i na jakim dziale

```sql
-- najnowsza zmiana
SELECT id FROM shifts ORDER BY date DESC, CASE name WHEN 'Middag' THEN 2 ELSE 0 END DESC LIMIT 1;

-- osoby tej zmiany z bieżącym działem (ostatni wpis w departments)
SELECT e.firstname, e.lastname, d.department, d.time_assigned, e.position
FROM employees e
JOIN departments d ON d.id = (SELECT MAX(id) FROM departments WHERE employee_id = e.id)
WHERE e.shift_id = :shift_id;
```

Login osoby: `logins.login`, gdy `logins.name_key` = znormalizowane imię i nazwisko (małe litery, bez polskich
znaków, słowa posortowane). Od Etapu 5 login będzie przypisany bezpośrednio do osoby.
