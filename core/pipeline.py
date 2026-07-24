"""Orkiestracja jednego źródła: dedup + stan + decyzja o wysyłce.

Wydzielone z main.py, żeby dało się testować bez sieci — wysyłkę wstrzykujemy
przez `send_fn` (w produkcji: notify.send_offer; w testach: atrapa zbierająca
wywołania).

Model nowości (SPEC constraint 4: "pobieraj wszystkie nowe od ostatniego
znanego ID / nadrabianie zaległości"):

- Cold start: pierwszy przebieg portalu zapamiętuje wszystkie obecne oferty
  (bez wysyłki) i ustawia znacznik `high_water` = najnowszy `created_time`.
- Kolejne przebiegi wysyłają TYLKO oferty z `created_time` nowszym niż znacznik.
  OLX wpuszcza w okno wyników stare, promowane/bumpowane ogłoszenia — bez tej
  bramki czasowej byłyby wysyłane jako "nowe". Takie stare, niewidziane oferty
  zapamiętujemy po cichu (backfill), ale nie wysyłamy.
- Znana już oferta: pomijamy, chyba że cena spadła > próg (wtedy "OBNIŻKA").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from core import dedup, state
from sources.base import Offer


@dataclass
class Evaluation:
    """Wynik oceny oferty przez filtry twarde (+ policzony koszt do embeda)."""
    passed: bool
    reason: str | None
    cost: object  # core.cost.CostBreakdown | None


# send_fn(offer, price_drop, cost) — price_drop to None albo (stara_cena, nowa_cena)
SendFn = Callable[[Offer, "tuple[int, int] | None", object], None]
# filter_fn(offer) -> Evaluation
FilterFn = Callable[[Offer], Evaluation]


def _created_dt(offer: Offer) -> datetime | None:
    if not offer.created_time:
        return None
    try:
        return datetime.fromisoformat(offer.created_time)
    except ValueError:
        return None


def _max_created(offers: list[Offer]) -> str | None:
    times = [o.created_time for o in offers if o.created_time]
    return max(times) if times else None


def process_source(
    source: str,
    offers: list[Offer],
    st: dict,
    price_drop_threshold: int,
    now: datetime,
    send_fn: SendFn,
    filter_fn: FilterFn,
) -> dict:
    """Przetwórz oferty jednego portalu. Zwróć podsumowanie liczbowe.

    Filtry twarde (filter_fn) stosujemy PRZED wysyłką — oferta odrzucona jest
    zapamiętywana w stanie (żeby nie rozważać jej ponownie), ale nie wysyłana.
    """
    summary = {
        "fetched": len(offers),
        "seeded": 0,
        "sent_new": 0,
        "sent_drop": 0,
        "backfilled": 0,
        "filtered": 0,
        "skipped": 0,
    }

    def _record(o: Offer) -> None:
        state.record(st, dedup.key_for(o), dedup.fingerprint(o), o.price, now)

    # Cold start: zasiej po cichu i ustaw znacznik nowości.
    if state.get_high_water(st, source) is None:
        for o in offers:
            _record(o)
        summary["seeded"] = len(offers)
        newest = _max_created(offers)
        if newest:
            state.set_high_water(st, source, newest)
        return summary

    hwm = datetime.fromisoformat(state.get_high_water(st, source))

    for o in offers:
        result = dedup.classify(o, st, price_drop_threshold)

        if result.status is dedup.DedupStatus.PRICE_DROP:
            ev = filter_fn(o)
            if ev.passed:
                send_fn(o, (result.old_price, result.new_price), ev.cost)
                summary["sent_drop"] += 1
            else:
                summary["filtered"] += 1
            _record(o)  # tak czy tak aktualizuje zapisaną cenę

        elif result.status is dedup.DedupStatus.DUPLICATE:
            summary["skipped"] += 1

        else:  # NEW (niewidziana) -> najpierw bramka czasowa, potem filtry
            created = _created_dt(o)
            if created is not None and created > hwm:
                ev = filter_fn(o)
                if ev.passed:
                    send_fn(o, None, ev.cost)
                    summary["sent_new"] += 1
                else:
                    summary["filtered"] += 1
                _record(o)
            else:
                _record(o)  # stara oferta rotująca w okno -> zapamiętaj, nie wysyłaj
                summary["backfilled"] += 1

    # Przesuń znacznik do najnowszego widzianego created_time.
    newest = _max_created(offers)
    if newest and newest > state.get_high_water(st, source):
        state.set_high_water(st, source, newest)

    return summary
