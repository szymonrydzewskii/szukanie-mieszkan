"""Dopasowanie ofert: match / near_miss / reject.

Model (decyzja użytkownika: odejście od oceniania /100):
- offer PASUJE (match) -> kanał główny #mieszkania, jeśli spełnia WSZYSTKIE
  twarde kryteria: cena/koszt, metraż, ≥2 pokoje, DOBRA dzielnica, typ, brak
  wykluczeń najemcy, brak pieca/sutereny, świeże (<=7 dni).
- PRAWIE-TRAFIENIE (near_miss) -> #odrzucone, jeśli wpada tylko na JEDNYM
  łagodnym kryterium: koszt lekko ponad limit, albo kawalerka z opisaną
  oddzielną sypialnią (niepewny układ — warto zerknąć).
- ODRZUT (reject) -> tylko do stanu, nie wysyłamy.

Zasada: braki danych nie powodują odrzutu (nie zmyślamy). Wszystkie liczby/
słowa kluczowe pochodzą z config.yaml.
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
class Verdict:
    kind: str            # "match" | "near_miss" | "reject"
    reason: str | None = None


def offer_text(offer: Offer) -> str:
    """Tytuł + opis jako czysty, mały tekst (HTML usunięty)."""
    raw = f"{offer.title or ''} {offer.description or ''}"
    raw = _TAG_RE.sub(" ", raw)
    return html.unescape(raw).lower()


def _contains(text: str, keywords) -> str | None:
    for kw in keywords or []:
        if kw.lower() in text:
            return kw
    return None


def location_tier(city: str | None, district: str | None, loc_cfg: dict) -> str:
    """Kategoria lokalizacji wg tabeli dzielnic. Dopasowanie po mieście I dzielnicy
    (Sopot ma district='Centrum', ale miasto 'Sopot'). Brak dopasowania -> 'other'."""
    d = f"{city or ''} {district or ''}".lower()
    tiers = loc_cfg["tier_districts"]
    for tier in ("best", "very_good", "good", "ok"):
        if any(kw.lower() in d for kw in tiers.get(tier, [])):
            return tier
    return "other"


def classify(offer: Offer, text: str, cost: CostBreakdown, config: dict, now: datetime) -> Verdict:
    f = config["filters"]

    # --- Twarde odrzuty (nigdy nie są prawie-trafieniem) ---
    if offer.city and offer.city not in f["allowed_cities"]:
        return Verdict("reject", f"lokalizacja poza Trójmiastem: {offer.city}")

    if offer.area_m2 is not None and offer.area_m2 < f["min_area_m2"]:
        return Verdict("reject", f"powierzchnia {offer.area_m2:g} m² < {f['min_area_m2']} m²")

    kw = _contains(text, f.get("type_reject_keywords"))
    if kw:
        return Verdict("reject", f"typ inny niż mieszkanie: '{kw}'")

    kw = _contains(text, f.get("reject_phrases"))
    if kw:
        return Verdict("reject", f"wykluczenie najemcy: '{kw}'")

    if cost.heating == "stove":
        return Verdict("reject", "ogrzewanie piecowe/kaflowe/węglowe")

    kw = _contains(text, f.get("souterrain_keywords"))
    if kw:
        return Verdict("reject", f"suterena ('{kw}')")

    kw = _contains(text, f.get("no_bathroom_keywords"))
    if kw:
        return Verdict("reject", f"brak łazienki w lokalu ('{kw}')")

    if offer.created_time:
        try:
            created = datetime.fromisoformat(offer.created_time)
            if created < now - timedelta(days=f["max_age_days"]):
                return Verdict("reject", f"ogłoszenie starsze niż {f['max_age_days']} dni")
        except ValueError:
            pass

    tier = location_tier(offer.city, offer.district, config["location"])
    if tier not in f["location_accept_tiers"]:
        return Verdict("reject", f"lokalizacja poza dobrymi dzielnicami ({offer.district or offer.city})")

    # --- Prawie-trafienia (jedno łagodne kryterium) ---
    near: list[str] = []

    if offer.rooms is not None and offer.rooms < f["min_rooms"]:
        if _contains(text, f.get("studio_bedroom_keywords")):
            near.append("kawalerka z opisaną oddzielną sypialnią — sprawdź układ")
        else:
            return Verdict("reject", f"mniej niż {f['min_rooms']} pokoje ({offer.rooms})")

    limit = config["budget"]["hard_limit"]
    if cost.total is not None and cost.total > limit:
        if cost.total <= f["near_miss_cost_max"]:
            near.append(f"koszt {cost.total} zł — ponad limit {limit} zł")
        else:
            return Verdict("reject", f"koszt {cost.total} zł > {f['near_miss_cost_max']} zł")

    if near:
        return Verdict("near_miss", "; ".join(near))
    return Verdict("match")
