# PLAN — iteracja „Mieszkania na sprzedaż"

> Cel: bot szuka też mieszkań NA SPRZEDAŻ w tych samych dobrych okolicach co
> wynajem; fajne oferty lecą na OSOBNY kanał Discord. Czytać z `SPEC.md` i
> `HANDOFF.md`. Status: **plan gotowy, czeka na potwierdzenie decyzji (budżet!).**

## Research potwierdzony (2026-07-25) — parsery działają bez zmian

- **OLX sprzedaż** = to samo API, `category_id=14` (wynajem=15). `params` te same
  (price=cena całkowita, m, rooms, builttype…). Parser OLX działa — inna kategoria.
- **Trojmiasto sprzedaż** = `https://ogloszenia.trojmiasto.pl/nieruchomosci-sprzedam-rynek-wtorny/`
  (rynek wtórny). Ta sama struktura `.list__item` → parser Trojmiasto działa — inny URL.
- **Nieruchomosci-online sprzedaż** = `?3,mieszkanie,sprzedaz,,{city}`. Ta sama struktura
  `div.tile`; `.title-a` ma cenę + metraż + **zł/m²** gotowe. Parser działa — inny URL.

Wniosek: NIE piszemy nowych parserów. Dodajemy tryb (mode) + konfigurację źródeł sprzedaży.

## Kluczowe różnice wynajem vs sprzedaż

| | Wynajem (jest) | Sprzedaż (nowe) |
|---|---|---|
| Metryka | koszt/mies = najem+czynsz+media ≤ 3500 | cena zakupu (setki tys.) + zł/m² |
| core/cost.py | szacuje czynsz/media | NIE dotyczy — pomijamy |
| Filtry specyficzne | anty-student, ogrzewanie/media, wiek 7 dni | budżet zakupu, (opc.) max zł/m² |
| Filtry wspólne | lokalizacja (tiery), metraż, pokoje, typ, suterena | te same (reużyć) |
| Kanał | #mieszkania / #odrzucone | #sprzedaz (nowy webhook) |
| Embed | koszt+rozbicie, wiadomość do właściciela | cena + zł/m² + fakty + stacja SKM |

## DECYZJE DO POTWIERDZENIA (blokują wdrożenie)

1. **Budżet zakupu — max cena.** KRYTYCZNE, bez tego nie ma filtra. (np. 700k / 800k / 900k zł?)
2. **Max zł/m²** (opcjonalny sygnał „okazji", np. ≤ 15 000 zł/m²?). Bez median rynkowych to próg z configu.
3. **Metraż / pokoje** — te same co wynajem (≥35 m², ≥2 pok) czy inne (kupno bywa większe)?
4. **Lokalizacja** — te same tiery co wynajem (best/very_good/good/ok). Użytkownik: „te co na wynajem" → tak.
5. **Rynek** — wtórny (jak URL Trojmiasto) czy też pierwotny/deweloper? Propozycja: wtórny.
6. **#odrzucone dla sprzedaży** — osobny kanał prawie-trafień (cena lekko ponad budżet), czy tylko kanał trafień? Propozycja: opcjonalny drugi webhook, na start można pominąć.
7. **„Fajne oferty" v1** = cena ≤ budżet + dobra lokalizacja + metraż/pokoje. Detekcja „okazji" po medianie zł/m² → ODŁOŻYĆ (jak wykrywanie oszustw; wymaga uzbierania danych).

## Architektura — koncepcja `mode` (rent/sale)

- `Offer.mode` (rent/sale). Źródło ustawia z configu.
- Nowe wpisy `config.sources`: `olx_sale` (category_id=14, mode=sale), `trojmiasto_sale`
  (URL sprzedaż), `nieruchomosci_online_sale` (URL sprzedaż). **Reużywają istniejących klas**
  Source (parametryzowane URL/kategorią z configu).
- Nazwa źródła = klucz configu → osobny stan/dedup/novelty dla sprzedaży (`olx_sale` ≠ `olx`).
  Wymaga drobnego refaktoru: `source.name` z klucza configu (dziś twardo w klasie) — `build_source`
  ustawia instancji nazwę = klucz.
- Pipeline BEZ ZMIAN (jest per-źródłowy). `main` dobiera per-źródło evaluate_fn/send_fn wg mode:
  sale → `classify_sale` + kanał sprzedaży; rent → obecne funkcje.
- Dedup Poziom 2 MODE-AWARE: dwa ogłoszenia SPRZEDAŻY tego samego lokalu = dubel; sprzedaż vs
  wynajem tego samego lokalu = NIE dubel. → `cross_portal_match` ograniczyć do źródeł tego samego mode.
- Izolacja błędów per-źródło, novelty (ID/created), stan — działają automatycznie.

## Zmiany per moduł

- `sources/base.py`: `Offer.mode="rent"`; mechanizm nazwy źródła z klucza configu.
- `sources/*`: ustawiać `offer.mode` i `offer.source` = klucz configu; (OLX category_id, Troj/N-O URL — już z configu).
- `core/sale.py` (NOWY): `price_per_m2(offer)`, lekki odpowiednik cost.py (cena + zł/m², bez szacowania).
- `core/filters.py`: `classify_sale(offer, text, config, now)` → match/near_miss/reject wg budżetu,
  (opc.) zł/m², metraż, pokoje, `location_tier` (reużyć), typ, suterena. BEZ anty-student/ogrzewania/wieku.
- `core/notify.py`: `build_sale_embed` (cena + zł/m² + metraż/pokoje/piętro + lokalizacja + stacja SKM);
  `send_offer(..., mode="sale", webhook_env="DISCORD_WEBHOOK_SALE")`.
- `core/dedup.py`: `cross_portal_match` — dopasowanie tylko w obrębie tego samego mode.
- `main.py`: rejestr klas dla źródeł sale (reużycie), per-źródło mode → evaluate/send; kanał sprzedaży.
- `config.yaml`: sekcja `sale` (budget, max_price_per_m2?, min_area, min_rooms, reuse tiers);
  wpisy `sources.*_sale`.
- Sekret `DISCORD_WEBHOOK_SALE` (użytkownik: kanał #sprzedaz → webhook → secret + .env).

## Etapy (TDD, jak dotąd — po każdym stop + zielone testy)

1. Potwierdzić decyzje (zwł. budżet). Dopiąć research: OLX sale params na próbce (price=total, m, rooms).
2. `mode` w Offer + nazwa źródła z klucza configu (refaktor, istniejące testy zielone).
3. `core/sale.py` + `classify_sale` + testy.
4. `build_sale_embed` + testy.
5. `cross_portal_match` mode-aware + testy.
6. `main` wiring + config (sekcja sale + źródła *_sale).
7. Diagnostyka na żywo (match/near per portal sprzedaż), potem deploy.
8. Użytkownik: kanał #sprzedaz + `DISCORD_WEBHOOK_SALE`.

## Ryzyka / uwagi

- Bez budżetu zakupu (decyzja #1) nie zaczynamy.
- „Okazja" po zł/m² bez median rynkowych = zgrubny próg z configu; prawdziwa detekcja okazji
  wymaga uzbierania danych (odłożone, jak wykrywanie oszustw).
- Sprzedaż ma mniejszy dzienny napływ nowych ofert niż wynajem — to normalne.
- Cloudflare/antybot: te same domeny co przy wynajmie (działają), więc sprzedaż powinna też;
  zweryfikować po deployu (izolacja per-źródło chroni).
- Cross-portal MUSI być mode-aware (nie mylić wynajmu ze sprzedażą tego samego mieszkania).
