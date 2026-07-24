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
