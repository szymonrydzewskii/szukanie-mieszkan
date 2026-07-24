"""Filtry twarde — stosowane PRZED ocenianiem (SPEC), żeby nie marnować pracy.

Zwracamy pierwszy powód odrzutu (albo passed=True). Zasada: nie odrzucamy
oferty tylko dlatego, że czegoś brakuje — braki (nieznany metraż/koszt/data)
nie powodują odrzutu, bo tym zajmie się ocenianie i sekcja "Do zapytania".

Wszystkie liczby, słowa kluczowe i frazy pochodzą z config.yaml (zero magic
numbers w kodzie).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.cost import CostBreakdown
from sources.base import Offer

_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class FilterResult:
    passed: bool
    reason: str | None = None


def offer_text(offer: Offer) -> str:
    """Tytuł + opis jako czysty, mały tekst (HTML usunięty) do wyszukiwania fraz."""
    raw = f"{offer.title or ''} {offer.description or ''}"
    raw = _TAG_RE.sub(" ", raw)
    return html.unescape(raw).lower()


def _contains(text: str, keywords) -> str | None:
    for kw in keywords or []:
        if kw.lower() in text:
            return kw
    return None


def evaluate(
    offer: Offer,
    text: str,
    cost: CostBreakdown,
    config: dict,
    now: datetime,
) -> FilterResult:
    f = config["filters"]

    # Lokalizacja poza Trójmiastem.
    if offer.city and offer.city not in f["allowed_cities"]:
        return FilterResult(False, f"lokalizacja poza Trójmiastem: {offer.city}")

    # Powierzchnia.
    if offer.area_m2 is not None and offer.area_m2 < f["min_area_m2"]:
        return FilterResult(False, f"powierzchnia {offer.area_m2:g} m² < {f['min_area_m2']} m²")

    # Liczba pokoi — z wyjątkiem kawalerki z opisaną oddzielną sypialnią.
    if offer.rooms is not None and offer.rooms < f["min_rooms"]:
        if _contains(text, f.get("studio_bedroom_keywords")) is None:
            return FilterResult(False, f"mniej niż {f['min_rooms']} pokoje ({offer.rooms})")

    # Typ inny niż mieszkanie (pokój/współdzielenie/...).
    kw = _contains(text, f.get("type_reject_keywords"))
    if kw:
        return FilterResult(False, f"typ inny niż mieszkanie: '{kw}'")

    # Wykluczenie najemcy (nie studentom / tylko pracujący / tylko rodzina).
    kw = _contains(text, f.get("reject_phrases"))
    if kw:
        return FilterResult(False, f"wykluczenie najemcy: '{kw}'")

    # Ogrzewanie piecowe/kaflowe/węglowe.
    if cost.heating == "stove":
        return FilterResult(False, "ogrzewanie piecowe/kaflowe/węglowe")

    # Suterena.
    kw = _contains(text, f.get("souterrain_keywords"))
    if kw:
        return FilterResult(False, f"suterena ('{kw}')")

    # Brak łazienki w lokalu.
    kw = _contains(text, f.get("no_bathroom_keywords"))
    if kw:
        return FilterResult(False, f"brak łazienki w lokalu ('{kw}')")

    # Ogłoszenie starsze niż N dni w chwili pierwszego wykrycia.
    if offer.created_time:
        try:
            created = datetime.fromisoformat(offer.created_time)
            if created < now - timedelta(days=f["max_age_days"]):
                return FilterResult(False, f"ogłoszenie starsze niż {f['max_age_days']} dni")
        except ValueError:
            pass  # nieparsowalna data -> nie odrzucamy za brak danych

    # Koszt całkowity ponad twardą granicę (tylko gdy znany).
    limit = config["budget"]["hard_limit"]
    if cost.total is not None and cost.total > limit:
        return FilterResult(False, f"koszt całkowity {cost.total} zł > {limit} zł")

    return FilterResult(True)
