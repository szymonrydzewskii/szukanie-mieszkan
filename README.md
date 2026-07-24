# Bot mieszkaniowy — Trójmiasto

Monitoruje ogłoszenia mieszkań na wynajem w Trójmieście (na razie OLX), filtruje
i liczy koszt całkowity, a nowe oferty wysyła na Discorda. Działa w GitHub Actions
(cron co ~15 min) — **nie wymaga włączonego komputera**.

> Etap projektu: 1–3 (szkielet, OLX, filtry, koszt) + 5 (Actions) gotowe.
> Ocenianie i segregacja na kanały (Etap 4) oraz kolejne portale (Etap 6) — w toku.
> Plan i decyzje: [`HANDOFF.md`](HANDOFF.md). Pełna specyfikacja: [`SPEC.md`](SPEC.md).

## Jak to działa

- `python main.py --once` — jeden przebieg: pobierz oferty → odfiltruj (koszt >3500,
  metraż <35, <2 pokoje, wykluczenie najemcy, ogrzewanie piecowe itd.) → wyślij nowe
  na Discord. To jedyny punkt wejścia; Actions po prostu odpala tę komendę z crona.
- Stan widzianych ofert trzymany w [`state/seen.json`](state/seen.json) i commitowany
  z powrotem do repo (żeby ta sama oferta nie przyszła dwa razy). Bez bazy danych.
- Nowość rozpoznawana po dacie dodania (`created_time`), nie po pozycji w wynikach —
  stare, promowane ogłoszenia rotujące w górę listy NIE są wysyłane ponownie.

## Wdrożenie na GitHub Actions (krok po kroku)

1. **Utwórz repozytorium na GitHub jako PUBLICZNE.**
   Dlaczego publiczne: publiczne repo ma nielimitowane minuty Actions. Prywatne ma
   tylko ~2000 min/mies., a cron co 15 min to za dużo. **W repo nie ma żadnych
   sekretów** — webhook idzie wyłącznie przez Actions Secrets (patrz punkt 3),
   a `.env` jest w `.gitignore`.

2. **Wypchnij kod** (patrz komendy niżej).

3. **Dodaj sekret z webhookiem:**
   `Settings → Secrets and variables → Actions → New repository secret`
   - Name: `DISCORD_WEBHOOK`
   - Secret: pełny URL webhooka Discorda (ten sam, co masz lokalnie w `.env`).

4. **Włącz Actions:** zakładka `Actions` → jeśli poprosi, potwierdź włączenie.

5. **Przetestuj od razu:** zakładka `Actions` → workflow „Skan mieszkań” →
   `Run workflow` (to ręczne uruchomienie, `workflow_dispatch`). Podejrzyj logi
   i sprawdź Discorda. Potem cron będzie odpalał go sam co ~15 min.

### Komendy do pierwszego pushu

```bash
git init
git add .
git commit -m "Bot mieszkaniowy: Etapy 1-3 + Actions (Etap 5)"
git branch -M main
git remote add origin https://github.com/<twoja-nazwa>/<repo>.git
git push -u origin main
```

## Ważne ograniczenia (przeczytaj)

- **GitHub wyłącza zaplanowane workflow po ~60 dniach braku aktywności w repo.**
  Nasze przebiegi commitują stan przy każdej nowej ofercie, co utrzymuje repo
  „aktywne". Ale jeśli rynek będzie martwy przez wiele tygodni (zero commitów),
  cron może zostać uśpiony — wtedy wejdź w `Actions` i włącz go ponownie
  (lub zrób jakikolwiek commit).
- **Runnery GitHub mają adresy IP z zakresów Azure**, często blokowane przez
  systemy antybotowe. Jeśli OLX zacznie zwracać 403/captcha z chmury, przebieg
  w `Actions` zaświeci się na czerwono z błędem. Nie obchodzimy zabezpieczeń —
  wtedy trzeba to zgłosić i rozważyć alternatywę (patrz SPEC pkt 6). Lokalnie
  (Twoje IP) OLX odpowiada normalnie.
- Przebieg ma się zmieścić w ~3 min; portal bez odpowiedzi w 20 s jest pomijany.

## Uruchomienie lokalne

```bash
pip install -r requirements.txt
# utwórz plik .env z jedną linią:  DISCORD_WEBHOOK=<url-webhooka>
python main.py --once            # jeden skan
python main.py --debug-raw olx   # surowa odpowiedź OLX (do diagnostyki)
```

Testy:

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```
