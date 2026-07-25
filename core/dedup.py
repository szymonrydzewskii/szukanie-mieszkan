"""Deduplikacja ofert.

SPEC opisuje dwa poziomy:
- Poziom 1: URL + ID ogłoszenia w obrębie portalu.  <-- zaimplementowane
- Poziom 2 (międzyportalowy): fingerprint (cena ±100 / metraż ±2 / pokoje /
  dzielnica / percepcyjny hash pierwszego zdjęcia).  <-- ODŁOŻONE do Etapu 6,
  gdy pojawi się drugi portal (z jednym portalem nie ma czego porównywać).

Fingerprint liczymy już teraz (bez hasha zdjęcia) i zapisujemy do stanu,
żeby na Etapie 6 wystarczyło dołożyć składnik obrazu i logikę dopasowania
z tolerancją.

Dodatkowo obsługujemy spadek ceny: jeśli cena spadła o więcej niż próg,
ofertę wysyłamy ponownie z adnotacją "OBNIŻKA".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sources.base import Offer
from core import state


class DedupStatus(Enum):
    NEW = "new"                # niewidziana wcześniej -> wyślij
    DUPLICATE = "duplicate"    # już widziana, bez istotnej zmiany -> pomiń
    PRICE_DROP = "price_drop"  # już widziana, cena spadła > próg -> wyślij "OBNIŻKA"


@dataclass
class DedupResult:
    status: DedupStatus
    old_price: int | None = None
    new_price: int | None = None


def key_for(offer: Offer) -> str:
    """Klucz Poziomu 1: unikalny w obrębie portalu."""
    return f"{offer.source}:{offer.source_id}"


def fingerprint(offer: Offer) -> str:
    """Fingerprint bez hasha zdjęcia (składniki nieobrazowe Poziomu 2).

    Percepcyjny hash pierwszego zdjęcia dojdzie na Etapie 6.
    """
    price = "?" if offer.price is None else str(offer.price)
    area = "?" if offer.area_m2 is None else f"{offer.area_m2:g}"
    rooms = "?" if offer.rooms is None else str(offer.rooms)
    district = (offer.district or "").strip().lower()
    return f"{price}|{area}|{rooms}|{district}"


def _parse_fingerprint(fp: str) -> tuple[int | None, float | None, int | None, str]:
    """Rozbij fingerprint 'cena|metraż|pokoje|dzielnica' na składniki."""
    parts = fp.split("|")
    if len(parts) != 4:
        return None, None, None, ""
    price_s, area_s, rooms_s, district = parts

    def _num(s, cast):
        try:
            return cast(s)
        except (TypeError, ValueError):
            return None

    return _num(price_s, int), _num(area_s, float), _num(rooms_s, int), district


def _districts_compatible(d1: str, d2: str) -> bool:
    """Dzielnice bywają nazwane różnie na różnych portalach (Wrzeszcz / Wrzeszcz Dolny).
    Zgodne, gdy dzielą pierwszy człon albo jedna zawiera drugą; brak danych nie blokuje."""
    if not d1 or not d2:
        return True
    return d1.split()[0] == d2.split()[0] or d1 in d2 or d2 in d1


def cross_portal_match(offer: Offer, st: dict, price_tol: int, area_tol: float) -> str | None:
    """Poziom 2: czy ta oferta to ten sam lokal, co widziany już na INNYM portalu?

    Dopasowanie po cena±price_tol + metraż±area_tol + pokoje (dokładnie) + dzielnica
    (luźno). Bez hasha zdjęć (decyzja użytkownika). Zwraca klucz dopasowanego wpisu
    albo None. Wymaga kompletu składników po naszej stronie (inaczej nie zgadujemy).
    """
    if offer.price is None or offer.area_m2 is None or offer.rooms is None or not offer.district:
        return None
    my_district = offer.district.strip().lower()
    prefix = f"{offer.source}:"

    for key, entry in st["seen"].items():
        if key.startswith(prefix):
            continue  # ten sam portal -> Poziom 1 (po ID)
        p, a, r, d = _parse_fingerprint(entry.get("fingerprint", ""))
        if p is None or a is None or r is None:
            continue
        if (r == offer.rooms and abs(p - offer.price) <= price_tol
                and abs(a - offer.area_m2) <= area_tol
                and _districts_compatible(my_district, d)):
            return key
    return None


def classify(offer: Offer, st: dict, price_drop_threshold: int) -> DedupResult:
    """Zdecyduj, czy ofertę wysłać (NEW / PRICE_DROP) czy pominąć (DUPLICATE)."""
    entry = state.get_entry(st, key_for(offer))
    if entry is None:
        return DedupResult(DedupStatus.NEW)

    old_price = entry.get("cena")
    if (
        old_price is not None
        and offer.price is not None
        and (old_price - offer.price) > price_drop_threshold
    ):
        return DedupResult(DedupStatus.PRICE_DROP, old_price=old_price, new_price=offer.price)

    return DedupResult(DedupStatus.DUPLICATE)
