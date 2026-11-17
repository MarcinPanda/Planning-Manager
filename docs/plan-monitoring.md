# Widok Monitoring – wstępne założenia (do dyskusji, nic nie jest wdrożone)

## Co jest w prototypie (`Planning + Monitoring.py`)

- Przełącznik Planning / Monitoring u góry okna (dwa widoki w jednym oknie).
- Monitoring ma trzy sekcje:
  1. **Piking** – tabela osób z działu Orderpicker; kolumny to klienci
     (Choco, Pladis, Grenade, Pieterciel, Nutricia, Essity, Alpro, Petfood, ITR) + Info.
  2. **Reach Outbound** – tabela osób z działu Reachtruck; kolumny to strefy
     (Noord, Zuid, Replenish, Consolidatie, Kantel, Extra) + Info.
  3. **Pozostałe działy** – siatka małych tabelek, po jednej na dział, 4 w rzędzie.

## Czego prototypowi brakuje

- Przeciąganie działa tylko w obrębie jednej tabelki (zmiana kolejności wierszy).
  Nie da się przenieść osoby do innego działu.
- Nic się nie zapisuje – po odświeżeniu układ wraca do stanu z bazy.
- Osoba jest pokazywana w dziale **początkowym**, a nie w tym, w którym jest teraz.
- Kolumny klientów i stref są zawsze puste – nie ma gdzie ich zapisać.
- Wiersze to sam tekst z nazwiskiem (bez identyfikatora), stała liczba 15 wierszy.
- Używa starych nazw działów (Bufferzone, Porto, Projekt...), innych niż w głównej aplikacji.

Wniosek: z prototypu bierzemy **układ i pomysł**, a mechanikę piszemy od nowa na obecnej bazie.

## Proponowane założenia

1. **Kostka = pracownik.** Na kostce: imię i nazwisko, godziny pracy, od której jest w tym dziale.
   Kolor jak w tabeli (chory, do domu, spóźniony).
2. **Kafel = dział.** Osoba leży w kaflu działu, w którym jest **teraz** (ostatni wpis w jej historii działów).
3. **Przeciągnięcie kostki na inny kafel = „Add Department".** Wywołuje dokładnie tę samą
   operację co menu w tabeli, więc od razu działają: przeliczenie godzin, walidacja godzin,
   historia zmian, Cofnij i odświeżenie widoku Planning.
4. **Godzina zmiany:** domyślnie aktualna; przed zapisem małe okienko z godziną do poprawienia
   (Enter = zatwierdź).
5. **Przed początkiem zmiany** przeciągnięcie zmienia dział początkowy („Edit Department"),
   a nie dodaje nowego wpisu – tak układa się obsadę przed startem.
6. **Zaznaczenie kilku kostek** i przeniesienie ich razem.
7. **Ziek i Naar Huis** jako osobne kafle; upuszczenie na Naar Huis pyta o potwierdzenie
   (skraca godziny), a osoby, które poszły do domu, nie dają się już przeciągać.
8. **Jedna wspólna lista działów** w `pm/config.py` dla obu widoków.
9. **Oba widoki czytają te same dane** i odświeżają się razem (co 10 s i po każdej zmianie).

## Etapy

- **M1 – podgląd:** przełącznik widoków, kafle działów z kostkami, liczniki osób, bez przeciągania.
- **M2 – przenoszenie:** przeciąganie między działami z zapisem (punkty 3–7).
- **M3 – pozycje wewnątrz działu:** klienci w Pikingu, strefy w Reach Outbound.
- **M4 – wygoda:** wyszukiwarka na tablicy, obsada docelowa na dział, podświetlenie braków.

## Decyzje potrzebne od Ciebie

1. **Limit 5 działów na osobę.** Tabela ma 5 par kolumn i baza odrzuca szósty różny dział.
   Przy przeciąganiu łatwiej go przekroczyć. Podnieść limit, czy zostawić i pokazywać komunikat?
2. **Klienci i strefy (Piking, Reach):** czy to tylko etykieta „gdzie stoi", czy godziny mają się
   liczyć osobno na klienta/strefę? Od tego zależy, czy potrzebna jest zmiana w bazie.
3. **Godzina przy upuszczeniu:** okienko z godziną za każdym razem, czy od razu „teraz"
   (z możliwością Cofnij)?
4. **Układ tablicy:** wszystkie 34 działy jak w prototypie, czy tylko te, w których ktoś jest,
   plus lista pustych do rozwinięcia?
5. **Kto przeciąga:** jedna osoba sterująca, czy kilka komputerów naraz? To decyduje,
   czy trzeba najpierw zrobić Etap 4 (praca wielu osób jednocześnie).
