"""Orkiestracja jednego źródła: dedup + nowość + filtr + ocena + routing.

Wydzielone z main.py, żeby dało się testować bez sieci — wstrzykujemy:
- filter_fn(offer) -> Evaluation(passed, reason, cost)   (filtry twarde + koszt)
- score_fn(offer, cost) -> Score                          (rubryka /100)
- send_fn(offer, score, cost, channel, reason, price_drop)(wysyłka na Discord)

Model nowości (SPEC pkt 4): high-water-mark na created_time. OLX wpuszcza w
okno stare, promowane ogłoszenia — bez bramki czasowej byłyby wysyłane jako
"nowe". Cold start zasiewa po cichu.

Routing wg progów i limitów dziennych (scoring.decide_route). Wszystko
widziane trafia do stanu (nawet <60 i odrzucone), żeby nie rozważać ponownie.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from core import dedup, scoring, state
from sources.base import Offer


@dataclass
class Evaluation:
    """Wynik filtrów twardych + policzony koszt (do oceny i embeda)."""
    passed: bool
    reason: str | None
    cost: object  # core.cost.CostBreakdown


FilterFn = Callable[[Offer], Evaluation]
ScoreFn = Callable[[Offer, object], "scoring.Score"]
SendFn = Callable[..., None]  # (offer, score, cost, channel, reason, price_drop)


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
    filter_fn: FilterFn,
    score_fn: ScoreFn,
    send_fn: SendFn,
    routing_cfg: dict,
) -> dict:
    """Przetwórz oferty jednego portalu. Zwróć podsumowanie liczbowe."""
    summary = {
        "fetched": len(offers), "seeded": 0, "sent_main": 0, "sent_rejected": 0,
        "below": 0, "filtered": 0, "backfilled": 0, "skipped": 0, "max_score": None,
    }
    day = now.date().isoformat()

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
        """Oferta-kandydat (nowa po czasie albo z obniżką): filtr -> ocena -> routing."""
        ev = filter_fn(o)
        if not ev.passed:
            summary["filtered"] += 1
            _record(o)
            return
        score = score_fn(o, ev.cost)
        if summary["max_score"] is None or score.total > summary["max_score"]:
            summary["max_score"] = score.total
        route = scoring.decide_route(
            score.total, state.get_daily(st, day, "main"),
            state.get_daily(st, day, "band"), routing_cfg,
        )
        if route.channel == "main":
            send_fn(o, score, ev.cost, "main", route.reason, price_drop)
            state.bump_daily(st, day, "main")
            if score.total < routing_cfg["thresholds"]["top"]:
                state.bump_daily(st, day, "band")
            summary["sent_main"] += 1
        elif route.channel == "rejected":
            send_fn(o, score, ev.cost, "rejected", route.reason, price_drop)
            summary["sent_rejected"] += 1
        else:
            summary["below"] += 1
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
