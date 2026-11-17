# Plan zmian (stan: 17.11.2026)

Lista zebrana z dyktowania. Numery w nawiasach = numery zadań z rozmowy.

## Etap 1 – poprawki tablicy i Ziek / Naar Huis (najpierw)

- [ ] **Błąd:** Naar Huis na zmianie popołudniowej daje 0 h (powinno: od 15:00 do godziny wyjścia). (4)
- [ ] Ziek i Naar Huis to prawdziwe miejsca: osoba tam zostaje, widać ją wyraźnie razem z godziną
      wyjścia – nie tylko kolor. (3)
- [ ] Ziek – dwa przypadki: chorobowe od rana (0 h) oraz zachorował w trakcie (godziny do momentu
      zgłoszenia). (7, 8)
- [ ] Godzina wyjścia (Naar Huis / Ziek) do wpisania i poprawienia później – liczy się godzina
      odbicia, nie moment przeciągnięcia. (5)
- [ ] Masowe wysyłanie do domu: zaznaczam wiele osób, jedna godzina, godziny przeliczone od razu. (6)
- [ ] Strefy: Picking North = Choco, Pladis, Ferrero, Nutricia, Riverside, Alpro, Petfood, Essity,
      SCT (?), Pietercil, Tlant; Picking South = Mars GUM, Mars ITR, Grenade, Jordan, Reflex;
      Reach South = Zuid, Mars ITR, Grenade, Jordan, Reflex (bez Mars NL i Pietercil). (10–12)
- [ ] Kilka stref / klientów naraz (picking: 1–wszystkie autoryzacje; reach: np. Na-Nomi + Replenish).
      Baza to już obsługuje (Ctrl + przeciągnięcie), ale trzeba prostszego sposobu: prawy klik na
      karcie → lista stref z ptaszkami do zaznaczenia; karta widoczna w każdej zaznaczonej strefie
      z oznaczeniem, że osoba ma więcej stref. (24)
- [ ] Karty: pełniejsze imię i nazwisko zamiast inicjału; długie nazwiska skracane „…" na końcu,
      pełne w podpowiedzi. (20)
- [ ] Środek tablicy mieści się na szerokość bez przewijania; węższy panel po prawej. (2)
- [ ] Instrukcje pod małym „?" (okienko z opisem) zamiast stałego szarego tekstu. (15)
- [ ] Usunąć przycisk Sync Now. (16)

## Etap 2 – nowy wygląd całej aplikacji

- [ ] Własny, spójny motyw (jasny i ciemny), niezależny od kolorów systemu; czytelne kontrasty
      (nie polegać na samym kolorze). (9)
- [ ] Pasek u góry: ikonki, rzadkie opcje w menu rozwijanych (Import ▾, ⋯). (14)
- Decyzja: zostajemy przy PySide6 (Qt) – wygląd zmieniamy stylem i ikonami, bez przepisywania.

## Etap 3 – tablica do ułożenia po swojemu

- [ ] Edycja stref / klientów (dodaj, usuń, zmień nazwę, hala) – schowana w ustawieniach. (1)
- [ ] Każdy klocek z pracownikami da się przeciągnąć w siatce; reszta się przesuwa; ułożenie
      zapamiętane. (13)

## Etap 4 – zakładka Loginy

- [ ] Czwarty widok: lista loginów jak w Inlognamen Oosterhout, ale tylko N…P i R…R
      (bez Z…P i zdublowanych numerów). (21)
- [ ] Status loginu: wolny / przypisany / uszkodzony / zablokowany. (22)
- [ ] Na Monitoringu: prawy klik na osobie → „Dodaj login" → lista wolnych loginów. (23)
- [ ] Jednorazowy import z obecnego pliku Inlognamen.

## Etap 5 – praca wielu osób naraz

- [ ] Wspólna baza, automatyczne odświeżanie i zapis bez przycisków; bezpieczne przy dwóch
      zmianach naraz. (17)
- [ ] Druga aplikacja (wydawanie materiałów) czyta loginy z tej bazy zamiast z Excela.
- Potrzebna decyzja: gdzie leży baza (dysk sieciowy czy serwer) – do ustalenia z IT.

## Etap 6 – godziny do Excela

- [ ] Zapis godzin wybranego dnia do kopii pliku `<nazwa>_copy.xlsx`; oryginał nigdy nie jest
      zmieniany; inne dni w kopii nietknięte. (19)
- [ ] Potrzebny plik z godzinami (z pracy) – najpierw analiza budowy, arkuszy z systemu zegarowego,
      formuł i makr. Wymóg: pewność, że nic się nie zepsuje.
- Mark Mode zostaje, dopóki to nie działa. (18)

## Otwarte pytania

- Co to jest „SCT" na pikingu w North?
- Plik z godzinami – wrzucić z pracy.
- Ikony: własne piktogramy czy gotowy darmowy zestaw.
- Gdzie ma leżeć wspólna baza.
