# HANDOFF — stan projektu i plan kontynuacji

> Dokument roboczy do wznowienia pracy w nowej sesji. Czytaj razem z `SPEC.md`.
> **Aktualny stan: Etapy 1–5 ukończone (1–4 logika, 5 = GitHub Actions).
> Repo zielone (97 testów), wdrożone i działające w chmurze:
> https://github.com/szymonrydzewskii/szukanie-mieszkan (bot leci co 15 min).
> Następny etap: Etap 6 (kolejne portale + dedup Poziom 2 / hash zdjęć) oraz
> monitoring #alerty (SPEC). Wykrywanie oszustw też odłożone na Etap 6.**
>
> **Etap 4 (ZROBIONE):** rubryka /100 (`core/scoring.py`), dystans SKM
> (`core/geo.py`, ocena lokalizacji po tabeli dzielnic — dopasowanie city+district),
> pełny embed z oceną/kolorem/plusami/minusami/„Do zapytania"/wiadomością do
> właściciela (`core/notify.py`), routing na kanały + limity dzienne
> (`scoring.decide_route` + `state.*daily`). Decyzje użytkownika: układ z opisu
> (bez kary −10 na ślepo, tylko flaga w „Do zapytania"); oszustwa → Etap 6;
> #odrzucone przez `DISCORD_WEBHOOK_REJECTED`. Współrzędne stacji w config są
> PRZYBLIŻONE (tylko do wyświetlania szac. minut) — do ewentualnej korekty.

## Jak wznowić (dla nowej sesji Claude)

1. Przeczytaj `SPEC.md` (pełna specyfikacja) i ten plik.
2. Sprawdź, że testy przechodzą: `python -m pytest tests/ -q` (powinno być 62 passed).
3. Rusz z Etapem 4 wg planu na dole. **Trzymaj się stylu pracy użytkownika** (patrz niżej).

## Styl pracy użytkownika (WAŻNE — dotrzymywane przez cały projekt)

- **Pracuj etapami, ZATRZYMAJ SIĘ po każdym** i czekaj na potwierdzenie. Nie wchodź w kolejny etap z własnej inicjatywy.
- **Zanim napiszesz parser/nową integrację — pokaż realne dane** (`--debug-raw`, próbki API). Nie zgaduj nazw pól.
- **TDD**: test przed kodem, obejrzyj RED, potem GREEN. Cała logika w `core/` jest testowana.
- **Przy realnych rozwidleniach projektowych pytaj** (AskUserQuestion) z rekomendacją — nie zakładaj po cichu.
- **Zero magic numbers w kodzie** — wszystkie kwoty/progi/frazy/słowa kluczowe w `config.yaml`.
- Język: użytkownik pisze po polsku, odpowiadaj po polsku. Konsola Windows to cp1250 — do druku UTF-8 używaj `PYTHONIOENCODING=utf-8`.

## Komendy

```bash
python main.py --once            # jeden przebieg (pobierz -> filtruj -> wyślij), jedyny punkt wejścia na produkcji
python main.py --debug-raw olx   # surowa odpowiedź OLX, zapis do debug_raw_olx.json (gitignored)
python -m pytest tests/ -q       # testy
```

Sekrety w `.env` (gitignored): `DISCORD_WEBHOOK` (główny) — już ustawiony i działa.
Etap 4 będzie potrzebował dodatkowo `DISCORD_WEBHOOK_REJECTED` (i później `DISCORD_WEBHOOK_ALERTS`).

## Architektura (stan po Etapie 3)

```
main.py                # orkiestracja, --once / --debug-raw, ładowanie .env i config
config.yaml            # WSZYSTKIE kwoty/progi/frazy (http, notify, state, dedup, budget, filters, heating)
sources/
  base.py              # dataclass Offer + Source(ABC) + SourceError
  olx.py               # portal OLX: fetch_raw() (debug) + fetch() (parser) — API /api/v1/offers/
core/
  state.py             # seen.json: load/save (sort_keys), record, prune >60d, high_water per portal
  dedup.py             # Poziom 1 (portal:id), fingerprint (bez hasha zdjęcia), wykrywanie spadku ceny
  cost.py              # koszt całkowity + konserwatywne szacowanie + detect_heating
  filters.py           # filtry twarde + offer_text (HTML->tekst)
  pipeline.py          # process_source: cold start / nowość / filtr / OBNIŻKA / backfill
  notify.py            # build_embed (koszt + ⚠) + send_offer (webhook z .env)
state/seen.json        # commitowany stan (mały, 4 pola + high_water)
tests/                 # test_state, test_dedup, test_cost, test_filters, test_notify, test_pipeline, test_olx
```

Kontrakt: każdy portal → `fetch() -> list[Offer]`. Błąd sieci/parsowania = wyjątek `SourceError`, NIGDY ciche `[]`.

## Kluczowe decyzje (potwierdzone z użytkownikiem)

- **Dedup Poziom 1 only** (portal:id). Poziom 2 (międzyportalowy fingerprint + percepcyjny hash zdjęcia) → **Etap 6**, gdy dojdzie drugi portal. Fingerprint składniki nieobrazowe (`cena|metraż|pokoje|dzielnica`) już liczone i zapisywane.
- **Cold start = zasiew po cichu**: pierwszy przebieg portalu zapamiętuje wszystko bez wysyłki i ustawia `high_water`.
- **Nowość po `created_time` (high-water-mark)**, NIE po obecności w oknie wyników. Powód: OLX wpuszcza w top-okno stare, promowane/bumpowane ogłoszenia (`pushup`/`top_ad`) — bez bramki czasowej byłyby wysyłane jako „nowe" (był to realny błąd, naprawiony w Etapie 2). Stare rotujące → backfill (zapamiętane, nie wysłane).
- **Kawalerki (rooms<2)**: odrzucane, CHYBA że opis zawiera rdzeń „sypialni" → przepuszczamy do oceny (Etap 4 zweryfikuje układ).
- **Media (nie ma w danych OLX)**: domyślnie 350 zł (⚠), 700 zł tylko gdy w opisie wykryte ogrzewanie elektryczne.
- **Śmieciowy czynsz < 50 zł** (np. „1 zł") traktowany jak brak → szacowanie (`budget.min_plausible_rent`).
- **Polska odmiana**: słowa kluczowe filtrów jako RDZENIE (np. „suteren", „sypialni").

## OLX — techniczne (zweryfikowane na żywo)

- Endpoint JSON: `https://www.olx.pl/api/v1/offers/?offset=0&limit=40&category_id=15&city_id=<id>&sort_by=created_at:desc`
- Pojedyncza oferta po id: `https://www.olx.pl/api/v1/offers/<id>/`
- `category_id=15` = Mieszkania → Wynajem. `city_id`: Gdańsk **5659**, Sopot **15983**, Gdynia **5849** (region Pomorskie).
- Dane w `params[]` (lista `{key,name,type,value}`): `price`(value.value, PLN), `rent`(value.key, str), `m`(value.key, str, bywa „47.5"), `rooms`(value.key enum: one/two/three/four), `builttype`(blok/kamienica/apartamentowiec/wolnostojacy/szeregowiec), `floor_select`, `furniture`, `winda`, `parking`, `pets`.
- Poza params: `location.city.name`/`.district.name`, **`map.lat`/`map.lon`** (są współrzędne! do dystansu SKM w Etapie 4), `photos[].link` (szablon `...s={width}x{height}`), `contact.phone`(bool), `contact.name`, `created_time`, `description`(HTML).
- **Ogrzewanie NIE jest polem** — tylko z opisu. Kaucja/prowizja/typ też tylko z opisu.
- Środowisko lokalne (nie-Azure IP) dostaje HTTP 200 bez problemu. Na GitHub Actions (IP Azure) może być gorzej — patrz SPEC pkt 6.

---

# PLAN ETAPU 4 — ocenianie + progi + kanały

Cel: rubryka /100, kary, progi wysyłki na kanały (`#mieszkania` / `#odrzucone`), limit dzienny, pełny embed.
Rób modułami przez TDD, tak jak Etapy 2–3. **Zapytaj użytkownika o rozwidlenia oznaczone [DECYZJA].**

## 0. Wstępne pytania do użytkownika (przed kodem)
- **[DECYZJA] Ocena układu i „brak zdjęć sypialni −10"**: nie mamy wizji (nie analizujemy zdjęć). Propozycja: układ oceniać z `rooms`+`area`+słów w opisie; karę „brak zdjęć sypialni −10" zastąpić flagą ⚠ „układ do potwierdzenia" LUB stosować ostrożnie z opisu. Zapytać, którą drogę.
- **[DECYZJA] Wykrywanie oszustw** (sekcja SPEC „WYKRYWANIE OSZUSTW”): robić w Etapie 4 czy osobno później? (część sygnałów wymaga mediany cen/dzielnica i hasha zdjęcia = Etap 6).
- Poprosić o `DISCORD_WEBHOOK_REJECTED` w `.env` (kanał `#odrzucone`).

## 1. Dane: współrzędne do Offer
- Dodać `lat: float|None`, `lon: float|None` do `Offer` (`sources/base.py`) i parsera (`olx.py`, z `o["map"]["lat"/"lon"]`). Test w `tests/test_olx.py`.

## 2. core/geo.py — dystans do SKM (TDD)
- Stałe stacji SKM/PKM z współrzędnymi w `config.yaml` (sekcja `geo.stations` z lat/lon i flagą osi). Oś SKM (SPEC): Sopot Kamienny Potok, Sopot Wyścigi, Sopot, Gdańsk Żabianka-AWFiS, Gdańsk Oliwa, Gdańsk Przymorze-Uniwersytet.
- `nearest_station(lat, lon, stations) -> (station, dist_m)` (haversine).
- `walk_minutes(dist_m) -> int` = odległość w linii prostej × 1.3 / ~83 m/min (SPEC: nie licz czasów przejazdu, tylko dojście + liczba przystanków).
- NIE zmyślać czasów przejazdu.

## 3. core/scoring.py — rubryka /100 (TDD)
Wejście: `Offer` + `CostBreakdown` + wynik geo + tekst opisu + config. Wyjście: `Score(total, breakdown: dict, penalties: list, plusy, minusy, do_zapytania)`.
Rubryka (wszystkie progi z configu, sekcja `scoring`):
- **Cena /30**: 30 ≤2800 · 25 ≤3000 · 18 ≤3300 · 10 ≤3500 (na `cost.total`).
- **Lokalizacja /25**: 25 = stacja na osi SKM ≤10 min pieszo · 18 = ≤15 min lub PKM/tramwaj · 10 = 15–25 min · 3 = powyżej.
- **Układ i metraż /20**: 20 = 2 osobne pokoje + sypialnia z oknem + 40–50 m² · 14 = aneks + sypialnia · 8 = przechodni · 0 = nie spełnia. (Z opisu+rooms+area — patrz [DECYZJA].)
- **Standard /15**: 15 po remoncie/nowy/wysoki standard · 10 zadbane · 5 przeciętne · 0 zaniedbane (słowa kluczowe w opisie → config).
- **Wyposażenie /10**: po 2 pkt: pralka, lodówka, piekarnik, biurko, internet w cenie (słowa kluczowe + param `furniture`).
Kary (odejmij od sumy): brak zdjęć sypialni −10 (patrz decyzja) · prowizja 100% −10 · prowizja ≤50% −5 · ogrzewanie elektryczne −8 (`cost.heating=="electric"`) · brak danych o czynszu −5 (`cost.czynsz_estimated`) · ogłoszenie 4–7 dni −5 (wiek z `created_time`).
Prowizję wykrywać z opisu (config: frazy „prowizja", „100% czynszu", „wynagrodzenie pośrednika", „bez prowizji"→0).

## 4. Progi i routing (config `scoring.thresholds`)
- 88–100 → `#mieszkania` + `@here`.
- 78–87 → `#mieszkania`, bez pinga, **max 6 dziennie**.
- 60–77 → `#odrzucone`, jedna linijka z powodem.
- <60 → tylko do stanu, nie wysyłaj.
- **Limit dzienny kanału głównego: 8.** Po przekroczeniu podnieś próg do 88 na 24 h.
- Licznik dzienny trzymać w stanie (`state.py`, np. `daily: {"YYYY-MM-DD": {sent_main: n, sent_78_87: n}}`, sprzątać stare dni). TDD.

## 5. notify.py — pełny embed (TDD build_embed)
Dodać: ocena /100 + rozbicie punktów, kolor paska (zielony 88+, żółty 78–87, czerwony scam), plusy, minusy, „Do zapytania", koszty jednorazowe (kaucja/prowizja z opisu → „suma na start"), 📞 przy telefonie, **gotowa wiadomość do właściciela** (2–3 zdania do skopiowania). Osobna, krótsza forma dla `#odrzucone` (jedna linijka z powodem/oceną).
Dodać `send_offer(..., webhook_env="DISCORD_WEBHOOK"|"DISCORD_WEBHOOK_REJECTED")` — wybór kanału.

## 6. pipeline.py — integracja oceniania
- Po przejściu filtrów: policz score → wybierz kanał/akcję wg progów i limitu dziennego. Odrzuty twarde (Etap 3) też mogą iść na `#odrzucone` z powodem (decyzja: SPEC chce `#odrzucone` = „odróżnić pusty rynek od za wysokiego progu od padniętego scrapera”). Zaktualizować `Evaluation`/summary o pola oceny i kanał.
- Zachować regułę: wszystko widziane → do stanu (nawet <60 i odrzucone).

## 7. main.py
- Zbudować `score_fn`/rozszerzyć `filter_fn`, przekazać webhooki obu kanałów, dołożyć podsumowanie (ile na główny, ile na odrzucone, najwyższa ocena).

## Uwaga na później (Etap 5/6, nie teraz)
- Etap 5: `.github/workflows/scan.yml`, sekrety, commit stanu z `git pull --rebase` + retry (SPEC pkt 3), README z ostrzeżeniem o wyłączaniu crona po ~60 dniach (SPEC pkt 8), cron `*/15 * * * *`.
- Etap 6: kolejne portale + dedup Poziom 2 (percepcyjny hash zdjęcia). Monitoring `#alerty`: licznik pustych runów w stanie, 3 puste runy → alert; dzienne podsumowanie.
- `has_source()` w state.py jest obecnie nieużywane w produkcji (zostało po Etapie 2) — można usunąć przy sprzątaniu.
