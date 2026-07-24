# SPEC — bot wyszukujący mieszkania w Trójmieście

Zbuduj system, który monitoruje portale z ogłoszeniami mieszkań na wynajem
w Trójmieście, filtruje i ocenia oferty, a najlepsze wysyła na Discord.

**Środowisko docelowe: GitHub Actions.** To narzuca konkretne ograniczenia —
przeczytaj sekcję "Ograniczenia techniczne" ZANIM zaczniesz projektować.

---

## KOLEJNOŚĆ PRACY — NIE BUDUJ WSZYSTKIEGO NARAZ

Pracuj etapami. Po każdym etapie zatrzymaj się i poczekaj, aż potwierdzę,
że działa. Nie przechodź dalej z własnej inicjatywy.

**Etap 1.** Szkielet + JEDEN portal (OLX) + webhook Discord.
Bez oceniania, bez filtrów. Cel: pierwsze ogłoszenie ląduje na Discordzie.

**Etap 2.** Deduplikacja i stan między uruchomieniami.
Cel: to samo ogłoszenie nie przychodzi dwa razy.

**Etap 3.** Filtry twarde + kalkulacja kosztu całkowitego.

**Etap 4.** System oceniania i progi wysyłki.

**Etap 5.** GitHub Actions — workflow, sekrety, commit stanu.

**Etap 6.** Kolejne portale, jeden po drugim.

Na etapie 1 kod uruchamiam lokalnie komendą `python main.py --once`.
Ta komenda musi działać do końca projektu — cały deploy na Actions ma
polegać wyłącznie na wywołaniu jej z crona.

---

## OGRANICZENIA TECHNICZNE (GitHub Actions)

To nie są sugestie, to są warunki brzegowe:

1. **Brak trwałego dysku.** Każde uruchomienie to czysta maszyna.
   Stan (widziane ogłoszenia) trzymaj w pliku JSON commitowanym z powrotem
   do repo. **Nie używaj SQLite** — plik binarny w gicie puchnie i powoduje
   konflikty. Nie polegaj na cache Actions, bywa usuwany.

2. **Stan musi być mały.** Zapisuj tylko to, co potrzebne do dedupu:
   `{id, fingerprint, cena, data_wyslania}`. Nie zapisuj opisów ani zdjęć.
   Usuwaj wpisy starsze niż 60 dni.

3. **Commit stanu musi być odporny na konflikty.** Użyj `git pull --rebase`
   przed pushem. Jeśli push się nie uda — spróbuj ponownie raz, potem
   zaloguj błąd i zakończ bez wywracania całego runu.

4. **Cron w Actions jest nieprecyzyjny.** Ustaw `*/15 * * * *`. Deklarowane
   minimum to 5 minut, ale zadania cykliczne bywają opóźniane lub pomijane.
   Kod musi zakładać nieregularne odstępy i radzić sobie z nadrobieniem
   zaległości (pobieraj wszystkie nowe od ostatniego znanego ID).

5. **Repo publiczne** (nielimitowane minuty). Dlatego:
   **żadnych sekretów w kodzie ani w stanie.** Webhook wyłącznie
   przez `secrets.DISCORD_WEBHOOK`. W commitowanym JSON-ie nie może
   znaleźć się nic wrażliwego.

6. **Runnery mają IP z zakresów Azure**, powszechnie blokowane przez
   systemy antybotowe. Zakładaj, że część portali odmówi współpracy.
   Jeśli portal zwraca 403/captcha — nie kombinuj z omijaniem zabezpieczeń,
   tylko zgłoś mi to i zaproponuj alternatywę.

7. **Timeout runa.** Cały przebieg ma się zmieścić w ~3 minutach.
   Jeśli portal nie odpowie w 20 s — pomiń go w tym cyklu i leć dalej.

8. **GitHub wyłącza zaplanowane workflow po ~60 dniach braku aktywności
   w repo.** Uwzględnij to w README.

---

## ARCHITEKTURA

Wymagam podziału, który pozwala dokładać portale bez ruszania reszty:

```
main.py              # orkiestracja, flaga --once, --debug-raw <portal>
config.yaml          # WSZYSTKIE filtry, progi i kwoty — zero magic numbers w kodzie
sources/
  base.py            # dataclass Offer + klasa bazowa Source
  olx.py             # pierwszy portal
core/
  scoring.py         # rubryka punktowa
  dedup.py           # fingerprint + porównanie ze stanem
  notify.py          # budowa embeda i wysyłka
  state.py           # odczyt/zapis JSON-a ze stanem
state/seen.json      # commitowany stan
.github/workflows/scan.yml
```

**Kontrakt między warstwami:** każdy portal implementuje `fetch() -> list[Offer]`.
Reszta systemu nie wie, z jakiego portalu pochodzi oferta.

**Zasada krytyczna:** `fetch()` przy błędzie sieci lub parsowania MUSI rzucić
wyjątek. Nigdy nie może po cichu zwrócić pustej listy — pusta lista znaczy
"sprawdziłem i naprawdę nic nowego nie ma". Mylenie tych dwóch stanów to
najczęstsza awaria takich systemów: scraper się psuje, a wygląda to
identycznie jak spokojny rynek.

**Podejście do pobierania:** preferuj wewnętrzne endpointy JSON i zawartość
`__NEXT_DATA__` zamiast parsowania HTML i selektorów CSS. Selektory psują się
przy każdej zmianie layoutu, struktury JSON są znacznie stabilniejsze.

Zanim napiszesz parser, uruchom `--debug-raw` i pokaż mi, co faktycznie wraca.
Nie zgaduj nazw pól.

---

## KOGO SZUKAMY

Dwoje studentów UG, para. Wspólne mieszkanie, **wspólna sypialnia**.

| | Wydział | Lokalizacja |
|---|---|---|
| On | Matematyki, Fizyki i Informatyki | ul. Wita Stwosza, Gdańsk Oliwa |
| Ona | Ekonomii | ul.Armii Krajowej 119, 81-824 Sopot |

Start najmu: od października. Akceptuj też wrzesień przy bardzo dobrej ofercie.
Okres: minimum rok akademicki.

---

## BUDŻET

```
KOSZT CAŁKOWITY = najem + czynsz administracyjny + media
```

Twarda granica: **3500 zł**. Powyżej — odrzut, bez wyjątków.
Idealnie do 3000 zł, dobrze do 3300 zł.

Gdy ogłoszenie nie podaje składników, szacuj konserwatywnie:

| Brak danych | Przyjmij |
|---|---|
| czynsz administracyjny (blok) | 550 zł |
| czynsz administracyjny (kamienica) | 400 zł |
| media, ogrzewanie miejskie/gazowe | 350 zł |
| media, **ogrzewanie elektryczne** | 700 zł |

Każde oszacowanie oznacz w embedzie znakiem ⚠ i wypisz, co dokładnie
zostało oszacowane.

Pokazuj też koszty jednorazowe: kaucja, prowizja pośrednika, suma na start.
Prowizja 100% czynszu = kara 10 pkt, do 50% = kara 5 pkt.

---

## FILTRY TWARDE (zastosuj PRZED ocenianiem, żeby nie marnować pracy)

- koszt całkowity > 3500 zł
- powierzchnia < 35 m²
- mniej niż 2 pokoje
- typ inny niż mieszkanie (pokój, kawalerka, współdzielenie, mikroapartament,
  hostel, lokal usługowy)
- w treści: "nie wynajmę studentom", "tylko dla pracujących", "tylko rodzina"
- ogrzewanie piecowe / kaflowe / węglowe
- suterena, brak łazienki w lokalu
- ogłoszenie starsze niż 7 dni w chwili pierwszego wykrycia
- lokalizacja poza Gdańskiem, Sopotem i Gdynią

---

## UKŁAD — WYMÓG KLUCZOWY

Potrzebna **pełnowymiarowa, zamykana sypialnia oddzielona od salonu
ścianą i drzwiami**. Sypialnia jest wspólna dla dwóch osób — musi pomieścić
łóżko 140 cm.

Akceptowalne:
- 2 pokoje + osobna kuchnia
- salon z aneksem + oddzielna sypialnia
- układ przechodni, gdy **sypialnia jest pokojem w głębi**

Odrzuć, jeżeli:
- sypialnia bez okna (alkowa, ścianka z płyty K-G)
- oddzielenie zasłoną, regałem, ścianką niepełnej wysokości
- do wyjścia z mieszkania trzeba przejść przez sypialnię
- faktycznie jeden pokój, mimo opisu "2 pokoje"

Układ weryfikuj po opisie i zdjęciach, nie po samym tytule.
Brak zdjęć sypialni: oznacz ⚠ i odejmij 10 pkt.

Przy filtrowaniu na portalu: ustaw liczbę pokoi na 2, ale przeszukuj też
kawalerki pod kątem słów "sypialnia" / "oddzielna sypialnia" — właściciele
często wrzucają mieszkania do złej kategorii.

---

## POWIERZCHNIA

Preferowana 38–50 m². Minimum 35 m².
Powyżej 55 m² tylko, jeśli koszt całkowity mieści się w 3300 zł.

---

## LOKALIZACJA — ZASADA OSI SKM

Oba wydziały leżą na jednej linii SKM:

```
Gdańsk Przymorze-Uniwersytet  →  UG Matematyka   (~7 min pieszo)
Sopot                          →  UG Ekonomia     (~10 min pieszo)
```

Stacje na osi: Sopot Kamienny Potok, Sopot Wyścigi, Sopot,
Gdańsk Żabianka-AWFiS, Gdańsk Oliwa, Gdańsk Przymorze-Uniwersytet.

Mieszkanie przy którejkolwiek z nich obsługuje oba wydziały bez przesiadki.
To scenariusz idealny.

**Nie licz dokładnych czasów przejazdu — będziesz zmyślał.** Podaj tylko
szacowany czas dojścia do najbliższej stacji (odległość w linii prostej
× 1,3) i liczbę przystanków. To wystarczy.

| Kategoria | Dzielnice |
|---|---|
| Najlepsze | Oliwa, Żabianka, Przymorze, Sopot (Dolny/Górny/Wyścigi/Kamienny Potok), Jelitkowo |
| Bardzo dobre | Wrzeszcz, Zaspa, Strzyża, Brzeźno |
| Dobre | Brętowo, Niedźwiednik (PKM), Morena, Piecki-Migowo |
| Akceptowalne | Suchanino, Aniołki, Śródmieście, Chełm |
| Tylko przy świetnej cenie | reszta z dobrym połączeniem SKM |

---

## OCENA — RUBRYKA SUMUJĄCA SIĘ DO 100

Nie oceniaj "na wyczucie" — wypełnij każdą pozycję osobno i zsumuj.
Zapisuj rozbicie punktów, żebym mógł zweryfikować ocenę.

| Kategoria | Max | Punktacja |
|---|---|---|
| Cena | 30 | 30 pkt ≤2800 zł · 25 ≤3000 · 18 ≤3300 · 10 ≤3500 |
| Lokalizacja | 25 | 25 pkt: stacja na osi SKM ≤10 min pieszo · 18: ≤15 min lub PKM/tramwaj · 10: 15–25 min · 3: powyżej |
| Układ i metraż | 20 | 20 pkt: 2 osobne pokoje, sypialnia z oknem, 40–50 m² · 14: aneks + sypialnia · 8: przechodni · 0: nie spełnia |
| Standard | 15 | 15 pkt: po remoncie · 10: zadbane · 5: przeciętne · 0: zaniedbane |
| Wyposażenie | 10 | po 2 pkt: pralka, lodówka, piekarnik, biurko, internet w cenie |

**Kary:** brak zdjęć sypialni −10 · prowizja 100% −10 · prowizja ≤50% −5 ·
ogrzewanie elektryczne −8 · brak danych o czynszu −5 · ogłoszenie 4–7 dni −5

### Progi

| Wynik | Działanie |
|---|---|
| 88–100 | `#mieszkania` + `@here` |
| 78–87 | `#mieszkania`, bez pinga, max 6 dziennie |
| 60–77 | `#odrzucone`, jedna linijka z powodem |
| < 60 | tylko do stanu, nie wysyłaj |

Limit dzienny na kanale głównym: 8. Po przekroczeniu podnieś próg do 88
na 24 h.

**Kanał `#odrzucone` jest obowiązkowy.** Bez niego nie odróżnię
"rynek pusty" od "próg za wysoki" od "scraper padł".

---

## BRAKUJĄCE DANE — NIGDY NIE ZMYŚLAJ

- Nie odrzucaj oferty tylko dlatego, że czegoś brakuje.
- Szacuj konserwatywnie, na niekorzyść oferty.
- Oznacz pole ⚠ i zastosuj karę punktową.
- W embedzie dodaj sekcję "Do zapytania" z konkretnymi pytaniami do właściciela.
- Jeśli nie wiesz — wpisz "brak danych". Nigdy nie wstawiaj liczby wziętej z powietrza.

---

## DEDUPLIKACJA — DWA POZIOMY

**Poziom 1:** URL + ID ogłoszenia w obrębie portalu.

**Poziom 2 (międzyportalowy):** fingerprint z
`cena ±100 zł` + `metraż ±2 m²` + `liczba pokoi` + `dzielnica` +
`hash percepcyjny pierwszego zdjęcia`.

To samo mieszkanie leci równolegle na OLX, Otodomie i Gratce — bez
fingerprintu dostanę trzy powiadomienia i przestanę je czytać.

Przy trafieniu duplikatu: nie wysyłaj, ale dopisz link do istniejącego wpisu.
Jeśli **cena spadła o ponad 100 zł** — wyślij ponownie z adnotacją "OBNIŻKA".

---

## WYKRYWANIE OSZUSTW

Oznacz ⚠ SCAM i wyślij tylko na `#odrzucone`, gdy:

- cena całkowita poniżej ~60% mediany dla metrażu i dzielnicy
- brak zdjęć lub zdjęcia wyglądające na wygenerowane przez AI
- to samo zdjęcie w innych ogłoszeniach pod inną ceną
- prośba o zaliczkę lub opłatę rezerwacyjną przed obejrzeniem
- właściciel "za granicą", klucze kurierem
- brak numeru telefonu i nacisk na kontakt tylko mailem/WhatsAppem

---

## DISCORD

Trzy webhooki, każdy jako osobny sekret:
`DISCORD_WEBHOOK` (główny), `DISCORD_WEBHOOK_REJECTED`, `DISCORD_WEBHOOK_ALERTS`.

Embed składaj **w kodzie na podstawie struktury danych**, nigdy nie generuj
go jako tekst — inaczej co dziesiąte ogłoszenie rozwali format.

Zawartość: tytuł z linkiem → ocena /100 → koszt całkowity z rozbiciem →
metraż, pokoje, piętro → dzielnica + stacja SKM + minuty pieszo → plusy →
minusy → do zapytania → koszt na start → data dodania → miniatura.

Kolor paska: zielony 88+, żółty 78–87, czerwony scam.

**Zawsze dołącz gotową wiadomość do właściciela** — 2–3 zdania do
skopiowania jednym kliknięciem. Dobre oferty znikają w 20 minut, wygrywa ten,
kto napisał pierwszy. Oferty z numerem telefonu oznacz 📞 — telefon daje
przewagę godzin nad czatem OLX.

---

## MONITORING

Na `#alerty`:

- Jeśli którekolwiek źródło rzuci wyjątek albo zwróci zero ogłoszeń
  (nawet już widzianych) w trzech kolejnych runach → alert z nazwą źródła
  i treścią błędu.
- Raz dziennie podsumowanie: ile sprawdzonych per źródło, ile wysłanych,
  ile odrzuconych, najwyższa ocena dnia.

Licznik kolejnych pustych runów trzymaj w stanie.

---

## PORTALE — KOLEJNOŚĆ WDRAŻANIA

1. **OLX** — największy wolumen ofert prywatnych, najprostszy technicznie
2. **Trojmiasto.pl**, **Nieruchomosci-online.pl** — mocne lokalnie, łagodne
3. **Gratka**, **Morizon** — uzupełnienie
4. **Otodom** — najlepsze oferty, ale ochrona antybotowa;
   z IP GitHub Actions prawdopodobnie odpadnie. Spróbuj, a jeśli nie wyjdzie,
   powiedz mi wprost zamiast kombinować.

Facebook pomijamy — wymaga cookies zalogowanego konta, czego nie da się
bezpiecznie trzymać w publicznym repo.

**Częstotliwość i kultura pobierania:** jedno zapytanie na portal na cykl,
losowy jitter, backoff wykładniczy przy 429/403, uczciwy User-Agent.
Nie omijaj captchy ani zabezpieczeń.

---

## CZEGO NIE ROBIĆ

- Nie pisz monolitu w jednym pliku.
- Nie zaszywaj kwot ani progów w kodzie — wszystko do `config.yaml`.
- Nie łap wyjątków po cichu (`except: pass` jest zakazane).
- Nie generuj embeda jako sklejonego stringa.
- Nie dodawaj portali, dopóki poprzedni nie chodzi stabilnie.
- Nie zakładaj, że masz jakikolwiek dostęp lub klucz — jeśli czegoś
  potrzebujesz, zatrzymaj się i napisz mi krok po kroku, jak to zdobyć
  i gdzie wkleić.

---

## CEL

Nie chcę dużo ofert. Chcę **jedno naprawdę dobre mieszkanie**.

Lepiej, żeby system przez dwa dni nie wysłał nic, niż żeby wysłał dziesięć
przeciętnych ofert, przez które przestanę czytać powiadomienia.
