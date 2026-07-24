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
from datetime import datetime
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


def _max_created(offers: list[Offer]) -> str | None:
    times = [o.created_time for o in offers if o.created_time]
    return max(times) if times else None


def process_source(
    source: str,
    offers: list[Offer],
    st: dict,
    price_drop_threshold: int,
    now: datetime,
    *,
    evaluate_fn: EvaluateFn,
    send_fn: SendFn,
) -> dict:
    """Przetwórz oferty jednego portalu. Zwróć podsumowanie liczbowe."""
    summary = {
        "fetched": len(offers), "seeded": 0, "sent_main": 0, "sent_near": 0,
        "dropped": 0, "backfilled": 0, "skipped": 0,
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
        else:  # NEW -> bramka czasowa
            created = _created_dt(o)
            if created is not None and created > hwm:
                _consider(o, None)
            else:
                _record(o)  # stara oferta rotująca w okno -> zapamiętaj, nie wysyłaj
                summary["backfilled"] += 1

    newest = _max_created(offers)
    if newest and newest > state.get_high_water(st, source):
        state.set_high_water(st, source, newest)

    return summary
