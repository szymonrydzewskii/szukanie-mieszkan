"""Orkiestracja jednego źródła: dedup + nowość + dopasowanie + routing.

Wstrzykujemy (testowalne bez sieci):
- evaluate_fn(offer) -> Decision(kind, reason, cost)   (filtry: match/near_miss/reject)
- send_fn(offer, cost, channel, reason, price_drop)     (wysyłka na Discord)

Model (bez oceniania /100): match -> #mieszkania, near_miss -> #odrzucone,
reject -> tylko stan. Nowość po high-water-mark na created_time (OLX wpuszcza
w okno stare, promowane oferty). Cold start zasiewa po cichu. Wszystko
widziane trafia do stanu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from core import dedup, state
from sources.base import Offer


@dataclass
class Decision:
    kind: str            # "match" | "near_miss" | "reject"
    reason: str | None
    cost: object         # core.cost.CostBreakdown


EvaluateFn = Callable[[Offer], Decision]
SendFn = Callable[..., None]  # (offer, cost, channel, reason, price_drop)


def _created_dt(offer: Offer) -> datetime | None:
    if not offer.created_time:
        return None
    try:
        return datetime.fromisoformat(offer.created_time)
    except ValueError:
        return None


def _novelty(offer: Offer) -> str | None:
    """Wartość porównywalna leksykalnie do znacznika nowości. Domyślnie created_time
    (OLX: wiarygodna data), ale źródło może podać novelty_key (Trojmiasto: ID)."""
    return offer.novelty_key or offer.created_time


def _max_novelty(offers: list[Offer]) -> str | None:
    vals = [nv for nv in (_novelty(o) for o in offers) if nv]
    return max(vals) if vals else None


def _is_fresh(offer: Offer, hwm: str, now: datetime, window_hours: float) -> bool:
    """Czy ofertę traktujemy jako nową (godną wysyłki)?

    Dwa przypadki, bo portale dają różne dane:

    1. Źródła z ID jako znacznikiem nowości (Trojmiasto, Nieruchomosci-online —
       data na liście to często data BUMPU): porównanie z high-water-markiem ID.
    2. Źródła z wiarygodną datą utworzenia (OLX): OKNO ŚWIEŻOŚCI zamiast znacznika.
       Znacznik zawodził, gdy oferta trafiała do feedu z opóźnieniem (moderacja):
       powstawała np. o 14:24, ale pojawiała się, gdy znacznik stał już na 14:56 —
       i wypadała jako "stara rotująca", choć była nowa i nigdy niewysłana.
       Przed powtórkami chroni Poziom 1 dedupu (po ID), więc okno jest bezpieczne.
    """
    if offer.novelty_key is not None:
        return offer.novelty_key > hwm
    created = _created_dt(offer)
    if created is None:
        return False  # brak daty i brak ID -> nie zgadujemy, tylko zapamiętujemy
    return created >= now - timedelta(hours=window_hours)


def process_source(
    source: str,
    offers: list[Offer],
    st: dict,
    price_drop_threshold: int,
    now: datetime,
    *,
    evaluate_fn: EvaluateFn,
    send_fn: SendFn,
    cross_price_tol: int | None = None,
    cross_area_tol: float | None = None,
    novelty_window_hours: float = 48,
) -> dict:
    """Przetwórz oferty jednego portalu. Zwróć podsumowanie liczbowe."""
    summary = {
        "fetched": len(offers), "seeded": 0, "sent_main": 0, "sent_near": 0,
        "dropped": 0, "backfilled": 0, "cross_dup": 0, "skipped": 0,
    }
    check_cross = cross_price_tol is not None and cross_area_tol is not None

    def _record(o: Offer) -> None:
        state.record(st, dedup.key_for(o), dedup.fingerprint(o), o.price, now)

    # Cold start: zasiej po cichu i ustaw znacznik nowości.
    if state.get_high_water(st, source) is None:
        for o in offers:
            _record(o)
        summary["seeded"] = len(offers)
        newest = _max_novelty(offers)
        if newest:
            state.set_high_water(st, source, newest)
        return summary

    hwm = state.get_high_water(st, source)  # porównanie leksykalne (ISO lub wyściełane ID)

    def _consider(o: Offer, price_drop) -> None:
        dec = evaluate_fn(o)
        if dec.kind == "match":
            send_fn(o, dec.cost, "main", None, price_drop)
            summary["sent_main"] += 1
        elif dec.kind == "near_miss":
            send_fn(o, dec.cost, "rejected", dec.reason, price_drop)
            summary["sent_near"] += 1
        else:
            summary["dropped"] += 1
        _record(o)

    for o in offers:
        result = dedup.classify(o, st, price_drop_threshold)
        if result.status is dedup.DedupStatus.PRICE_DROP:
            _consider(o, (result.old_price, result.new_price))
        elif result.status is dedup.DedupStatus.DUPLICATE:
            summary["skipped"] += 1
        else:  # NEW -> bramka nowości
            if _is_fresh(o, hwm, now, novelty_window_hours):
                if check_cross and dedup.cross_portal_match(o, st, cross_price_tol, cross_area_tol):
                    _record(o)  # ten sam lokal z innego portalu -> nie wysyłaj ponownie
                    summary["cross_dup"] += 1
                else:
                    _consider(o, None)
            else:
                _record(o)  # stara oferta rotująca/bumpnięta w okno -> zapamiętaj, nie wysyłaj
                summary["backfilled"] += 1

    newest = _max_novelty(offers)
    if newest and newest > state.get_high_water(st, source):
        state.set_high_water(st, source, newest)

    return summary
