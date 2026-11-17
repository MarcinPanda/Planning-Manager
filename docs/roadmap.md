# Plan zmian (stan: 17.11.2026)

## Cel

Jedna aplikacja zamiast czterech narzędzi:

- Excel z loginami (Inlognamen),
- Excel „monitoring",
- Excel z godzinami wypisywanymi ręcznie,
- kartki: wydrukowany plan i notatki z godzinami w ciągu dnia.

Przebieg zmiany:

1. Import planu z pliku.
2. Po starcie zmiany liderzy działów zgłaszają na helpdesku nieobecności i zmiany.
3. Helpdesk przeciąga osoby na tablicy, co trwa kilka chwil.
4. W ciągu dnia aplikacja jest „oczami steeringu".
5. Na końcu godziny trafiają do Excela, który idzie do księgowości. Dlatego godziny muszą być poprawne.

Zasady:

- Wszystko działa **offline**. Wspólna baza leży na **dysku sieciowym** i nic nie łączy się z internetem.
- Baza jest fundamentem także dla innych aplikacji, np. tej do wydawania materiałów, która czyta loginy.
  Musi być uporządkowana, odporna na błędy i opisowa.

## Etap 1 – tablica i poprawność godzin ✅ (zrobione 17.11 – do sprawdzenia w pracy)

- [x] **Błąd:** Naar Huis na zmianie popołudniowej daje 0 h. Powinny być godziny od 15:00 do godziny wyjścia.
- [x] Ziek i Naar Huis to prawdziwe miejsca. Osoba tam zostaje, a obok widać godzinę wyjścia jako tekst, nie tylko kolor.
- [x] Ziek ma dwa przypadki:
  - chorobowe od rana, czyli 0 h;
  - zachorował w trakcie zmiany, czyli godziny do momentu zgłoszenia.
- [x] Godzinę wyjścia (Naar Huis / Ziek) można wpisać i poprawić później. Liczy się godzina odbicia, a nie moment przeciągnięcia.
- [x] Masowe wysyłanie do domu: zaznaczam wiele osób, ustawiam jedną godzinę, a godziny przeliczają się od razu.
- [x] **Zmiany „od początku zmiany"**, gdy helpdesk dowiaduje się o nich z opóźnieniem. Propozycja:
  - wyraźny przełącznik „Od początku zmiany / Od teraz" z kolorowym paskiem, gdy jest włączony;
  - przełącznik sam się wyłącza 30 minut po starcie zmiany, żeby nikt o nim nie zapomniał;
  - przy przeciąganiu można też wpisać godzinę;
  - każdą godzinę działu można później poprawić.
- [x] Kilka stref i klientów naraz:
  - picking: od 1 do wszystkich autoryzacji;
  - reach: np. Na-Nomi + Replenish.
  - Prawy klik na karcie otwiera listę stref z ptaszkami. Karta pokazuje, że osoba ma więcej stref.
- [x] Strefy i ich kolejność:
  - Picking North: Choco, Pladis, Ferrero, Nutricia, Riverside, Alpro, Petfood, Essity, Pietercil, Tlant;
  - Picking South: Mars GUM, Mars ITR, Grenade, Jordan, Reflex;
  - Reach South: Zuid, Mars ITR, Grenade, Jordan, Reflex (bez Mars NL i Pietercil).
- [x] Karty z pełnym imieniem i nazwiskiem. Długie nazwy są skracane „…", a pełna nazwa jest w podpowiedzi.
- [x] Środek tablicy mieści się na szerokość bez przewijania, a panel po prawej jest węższy.
- [x] Instrukcje są pod małym „?" (okienko z opisem). Przycisk Sync Now znika.

## Etap 2 – nowy wygląd ✅ (podstawa zrobiona 17.11 – dalsze dopieszczanie wg uwag)

- [x] Własny, spójny motyw jasny i ciemny, niezależny od systemu, z czytelnym kontrastem (nie polegamy na samym kolorze).
- [x] Własne ikony. Robię listę promptów, użytkownik generuje arkusz w ChatGPT, a ja go tnę na pojedyncze ikony.
- [x] Pasek u góry z ikonkami i menu rozwijanymi (Import ▾, ⋯).
- Decyzja: zostajemy przy PySide6 (Qt). Wygląd zmieniamy stylem i ikonami.

## Etap 3 – wspólna baza na dysku sieciowym (fundament) ✅ (zrobione 17.11 – do testu na dysku sieciowym w pracy)

Cel: kilka komputerów naraz (helpdesk, steering) pracuje na tych samych danych, offline, bez przycisku „Sync".

1. **Gdzie leży baza.** W pliku ustawień obok exe (np. `settings.ini`) jest ścieżka do folderu na dysku
   sieciowym. Brak dostępu do dysku → wyraźny komunikat. Aplikacja nigdy nie tworzy po cichu pustej bazy lokalnie.
2. **Uporządkowany układ bazy (wersja 2):**
   - pracownicy, dni / zmiany, przydziały działów z godzinami, strefy, nieobecności;
   - tabela **dni** zamiast czyszczenia: kolejny dzień nie kasuje poprzedniego. Daje to historię tygodnia do Etapu 6;
   - **numer wersji bazy**: aplikacja sama i bezpiecznie przenosi stare dane (kopia przed przeniesieniem);
   - kto i kiedy zmienił każdy wpis (jest już dziennik zmian, będzie dokładniejszy).
3. **Kilka osób naraz:**
   - krótkie zapisy i ponawianie, gdy plik jest chwilowo zajęty;
   - wykrycie, że ktoś zmienił tę samą osobę sekundę wcześniej. Wtedy komunikat zamiast nadpisania;
   - Ctrl+Z cofa tylko **moje** zmiany.
4. **Odświeżanie u wszystkich:** aplikacja co kilka sekund sprawdza, czy coś się zmieniło, i odświeża tylko wtedy.
   W pasku widać „ostatnia zmiana: 14:32, Marcin".
5. **Kopie zapasowe** bazy na dysku sieciowym (co godzinę + przy starcie) oraz przywracanie z menu ⚙.
6. **Opis bazy** (`docs/database.md`) dla innych aplikacji, np. do wydawania materiałów: które tabele i pola czytać.
   Inne aplikacje tylko czytają.
7. **Test na dwóch komputerach** (dwa okna na jednym PC + test na dysku sieciowym w pracy).

Do ustalenia: ścieżka folderu na dysku sieciowym; kto ma prawo zapisu (uprawnienia folderu – IT).

## Etap 4 – tablica do ułożenia po swojemu

1. **Edycja stref i klientów** (⚙ → „Edit zones…", schowane):
   - dodaj, usuń, zmień nazwę, wybierz halę (North / South) i dział (Reach / Picking);
   - kolejność przeciąganiem na liście;
   - strefa z ludźmi nie da się usunąć (najpierw trzeba ich przenieść);
   - strefy są **wspólne dla wszystkich** (zapisane w bazie), bo to obraz magazynu.
2. **Przestawianie klocków na tablicy:**
   - tryb „Arrange board" (ikona ✥ przy tablicy). W trybie układania klocki da się złapać za nagłówek i przeciągnąć
     w siatce, a reszta się przesuwa. Bez tego trybu nic nie ucieka przypadkiem przy przeciąganiu ludzi;
   - działa w każdej kolumnie: strefy Reach / Picking, Inbound, Other;
   - **ułożenie zapamiętane dla każdego użytkownika osobno** + przycisk „Reset to default".
3. Opcjonalnie: ukrywanie pustych klocków (np. „pokaż tylko działy z ludźmi") – przełącznik.

## Etap 5 – zakładka Loginy

1. **Widok Loginy** (4. pozycja w menu): tabela loginów N…P / R…R (bez Z…P i zdublowanych numerów):
   numer, kody (N012P, R012R), osoba, status, uwagi, data zmiany.
2. **Statusy:** wolny / przypisany / uszkodzony / zablokowany (z powodem). Filtr i licznik wolnych.
3. **Nadawanie loginu:**
   - na Monitoringu: prawy klik na osobie bez loginu → „Add login…" → lista wolnych → OK;
   - w zakładce Loginy: zwolnienie loginu, zmiana statusu.
   Zmiany są w historii.
4. **Jednorazowy import** z Inlognamen Oosterhout: tylko numery i osoby; podgląd przed zapisem.
5. Loginy przypisane **do osoby**, a nie do napisu z imieniem. Koniec problemów typu „Ahmad Khalaf" ≠
   „AHMAD-NICOLAE KHALAF".
6. Aplikacja do materiałów czyta loginy z bazy (opis z Etapu 3).

Do ustalenia: zakres numerów loginów (np. 001–299?); czy loginy Z…P są w ogóle potrzebne.

## Etap 6 – godziny do Excela (dla księgowości)

1. **Analiza pliku z godzinami** (będzie jutro): arkusze, kolumny, formuły, makra, dane z systemu zegarowego, który
   arkusz wypełnia helpdesk.
2. **Projekt zapisu** do akceptacji, zanim cokolwiek zapiszemy:
   - oryginał nigdy nie jest otwierany do zapisu;
   - zapis do kopii `<nazwa>_copy.xlsx`;
   - tylko komórki wybranego dnia, inne dni nietknięte.
3. **Podgląd przed zapisem:** tabela „co wpiszę gdzie" + ostrzeżenia (np. osoba z planu, której nie ma w pliku).
4. **Weryfikacja po zapisie:** aplikacja czyta kopię z powrotem i porównuje komórka po komórce.
   Wszystko poza wybranym dniem musi być identyczne z oryginałem, inaczej kopia jest usuwana i pojawia się komunikat.
5. **Testy na kopiach prawdziwego pliku** (kilka dni, różne zmiany) zanim użyjemy tego w pracy.
6. Mark Mode zostaje, dopóki to nie działa.

## Kolejność i zależności

- Etap 3 → Etap 4 (strefy zapisane we wspólnej bazie) → Etap 5 (loginy we wspólnej bazie).
- Etap 6 można zacząć równolegle od analizy pliku (punkt 1–2), gdy tylko będzie plik.

## Otwarte pytania

- Plik z godzinami: będzie jutro.
- Ścieżka folderu na dysku sieciowym i uprawnienia (Etap 3).
- Zakres numerów loginów (Etap 5).
