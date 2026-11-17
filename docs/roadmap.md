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

## Etap 1 – tablica i poprawność godzin (start)

- [ ] **Błąd:** Naar Huis na zmianie popołudniowej daje 0 h. Powinny być godziny od 15:00 do godziny wyjścia.
- [ ] Ziek i Naar Huis to prawdziwe miejsca. Osoba tam zostaje, a obok widać godzinę wyjścia jako tekst, nie tylko kolor.
- [ ] Ziek ma dwa przypadki:
  - chorobowe od rana, czyli 0 h;
  - zachorował w trakcie zmiany, czyli godziny do momentu zgłoszenia.
- [ ] Godzinę wyjścia (Naar Huis / Ziek) można wpisać i poprawić później. Liczy się godzina odbicia, a nie moment przeciągnięcia.
- [ ] Masowe wysyłanie do domu: zaznaczam wiele osób, ustawiam jedną godzinę, a godziny przeliczają się od razu.
- [ ] **Zmiany „od początku zmiany"**, gdy helpdesk dowiaduje się o nich z opóźnieniem. Propozycja:
  - wyraźny przełącznik „Od początku zmiany / Od teraz" z kolorowym paskiem, gdy jest włączony;
  - przełącznik sam się wyłącza po ustalonym czasie od startu zmiany (np. 1 h), żeby nikt o nim nie zapomniał;
  - przy przeciąganiu można też wpisać godzinę;
  - każdą godzinę działu można później poprawić.
- [ ] Kilka stref i klientów naraz:
  - picking: od 1 do wszystkich autoryzacji;
  - reach: np. Na-Nomi + Replenish.
  - Prawy klik na karcie otwiera listę stref z ptaszkami. Karta pokazuje, że osoba ma więcej stref.
- [ ] Strefy i ich kolejność:
  - Picking North: Choco, Pladis, Ferrero, Nutricia, Riverside, Alpro, Petfood, Essity, **SET**, Pietercil, Tlant;
  - Picking South: Mars GUM, Mars ITR, Grenade, Jordan, Reflex;
  - Reach South: Zuid, Mars ITR, Grenade, Jordan, Reflex (bez Mars NL i Pietercil).
- [ ] Karty z pełnym imieniem i nazwiskiem. Długie nazwy są skracane „…", a pełna nazwa jest w podpowiedzi.
- [ ] Środek tablicy mieści się na szerokość bez przewijania, a panel po prawej jest węższy.
- [ ] Instrukcje są pod małym „?" (okienko z opisem). Przycisk Sync Now znika.

## Etap 2 – nowy wygląd

- [ ] Własny, spójny motyw jasny i ciemny, niezależny od systemu, z czytelnym kontrastem (nie polegamy na samym kolorze).
- [ ] Własne ikony. Robię listę promptów, użytkownik generuje arkusz w ChatGPT, a ja go tnę na pojedyncze ikony.
- [ ] Pasek u góry z ikonkami i menu rozwijanymi (Import ▾, ⋯).
- Decyzja: zostajemy przy PySide6 (Qt). Wygląd zmieniamy stylem i ikonami.

## Etap 3 – fundament: wspólna baza na dysku sieciowym

- [ ] Uporządkowany układ bazy, czyli sprzątanie zbędnych pól i starych błędów. Przenosimy dane z obecnej bazy bez ich utraty.
- [ ] Bezpieczna praca kilku osób naraz na pliku na dysku sieciowym:
  - krótkie zapisy;
  - ponawianie, gdy plik jest zajęty;
  - wykrycie, że ktoś inny zmienił to samo.
- [ ] Automatyczne odświeżanie u wszystkich, bez przycisków.
- [ ] Opis bazy dla innych aplikacji (wydawanie materiałów).

## Etap 4 – zakładka Loginy

- [ ] Czwarty widok z loginami jak w Inlognamen Oosterhout, ale tylko N…P i R…R, bez Z…P i zdublowanych numerów.
- [ ] Statusy loginu: wolny / przypisany / uszkodzony / zablokowany.
- [ ] Na Monitoringu: prawy klik na osobie → „Dodaj login" → lista wolnych loginów.
- [ ] Jednorazowy import z obecnego pliku Inlognamen. Aplikacja do materiałów czyta potem loginy z bazy.

## Etap 5 – tablica do ułożenia po swojemu

- [ ] Edycja stref i klientów (dodaj, usuń, zmień nazwę, hala), schowana w ustawieniach.
- [ ] Każdy klocek z pracownikami da się przeciągnąć w siatce, reszta się przesuwa, a ułożenie jest zapamiętane.

## Etap 6 – godziny do Excela (dla księgowości)

- [ ] Analiza pliku z godzinami: arkusze, formuły, makra, dane z systemu zegarowego. Plik będzie jutro z pracy.
- [ ] Zapis godzin wybranego dnia do kopii `<nazwa>_copy.xlsx`:
  - oryginał nigdy nie jest zmieniany;
  - inne dni w kopii zostają nietknięte.
- [ ] Do rozważenia: historia całego tygodnia w aplikacji.
- [ ] Testy na kopiach prawdziwego pliku. Wymóg: pewność, że nic się nie zepsuje.
- Mark Mode zostaje, dopóki to nie działa.

## Otwarte pytania

- Plik z godzinami: będzie jutro.
- Jak długo po starcie zmiany helpdesk zwykle wprowadza zmiany „od początku" (do automatycznego wyłączenia przełącznika)?
