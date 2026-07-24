"""Rubryka oceny /100 + kary (SPEC: ocena sumująca się do 100).

Nie oceniamy 'na wyczucie' — każda kategoria osobno, zapisujemy rozbicie,
żeby dało się zweryfikować ocenę. Wszystkie progi/punkty/słowa z config.yaml.

Ocena LOKALIZACJI idzie po tabeli dzielnic z SPEC (dane pewne), a nie po
liczeniu minut z przybliżonych współrzędnych. Minuty do stacji SKM liczymy
osobno (core.geo) tylko do wyświetlenia w embedzie.

Ocena UKŁADU idzie z opisu (nie mamy analizy zdjęć). Kary 'brak zdjęć
sypialni −10' NIE stosujemy na ślepo (decyzja użytkownika) — zamiast tego
dodajemy pozycję do 'Do zapytania'.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from core.cost import CostBreakdown
from sources.base import Offer


@dataclass
class Route:
    channel: str | None   # "main" / "rejected" / None (tylko do stanu)
    ping: bool
    reason: str


def decide_route(total: int, daily_main: int, daily_band: int, cfg: dict) -> Route:
    """Wybierz kanał wg progów i limitów dziennych (SPEC: progi + limit 8/dzień).

    - >= top: kanał główny + @here (najlepsze zawsze przechodzą).
    - >= main (78–87): główny bez pinga, o ile nie przekroczono limitów;
      po przekroczeniu -> #odrzucone (SPEC: podnieś próg do 88).
    - >= rejected (60–77): #odrzucone z jednolinijkowym powodem.
    - < rejected: tylko do stanu, nie wysyłaj.
    """
    th, lim = cfg["thresholds"], cfg["limits"]
    if total >= th["top"]:
        return Route("main", True, f"ocena {total}")
    if total >= th["main"]:
        if daily_main < lim["daily_main"] and daily_band < lim["daily_78_87"]:
            return Route("main", False, f"ocena {total}")
        return Route("rejected", False, f"ocena {total} — limit dzienny głównego kanału")
    if total >= th["rejected"]:
        return Route("rejected", False, f"ocena {total} — poniżej progu wysyłki")
    return Route(None, False, f"ocena {total} — za nisko, tylko do stanu")


@dataclass
class Score:
    total: int
    breakdown: dict[str, int]
    penalties: list[tuple[str, int]] = field(default_factory=list)
    plusy: list[str] = field(default_factory=list)
    minusy: list[str] = field(default_factory=list)
    do_zapytania: list[str] = field(default_factory=list)


def _has(text: str, keywords) -> bool:
    return any(kw.lower() in text for kw in (keywords or []))


def score_price(total: int | None, bands: list) -> int:
    if total is None:
        return 0
    for threshold, pts in bands:  # rosnąco po progu
        if total <= threshold:
            return pts
    return 0


def score_location(city: str | None, district: str | None, loc_cfg: dict) -> tuple[int, str]:
    """Ocena lokalizacji po tabeli dzielnic (SPEC). Dopasowanie po mieście I dzielnicy
    — oferty z Sopotu mają district='Centrum'/'Dolny', ale miasto 'Sopot'."""
    pts = loc_cfg["tier_points"]
    d = f"{city or ''} {district or ''}".lower()
    for tier in ("best", "very_good", "good", "ok"):
        if any(kw.lower() in d for kw in loc_cfg["tier_districts"].get(tier, [])):
            return pts[tier], tier
    return pts["other"], "other"


def score_layout(offer: Offer, text: str, lay: dict) -> int:
    text = text.lower()
    rooms = offer.rooms or 0
    area = offer.area_m2
    lo, hi = lay["ideal_area"]
    ideal = area is not None and lo <= area <= hi
    bedroom = _has(text, lay["bedroom_keywords"])
    aneks = _has(text, lay["alcove_keywords"])
    walk = _has(text, lay["walkthrough_keywords"])

    if rooms >= 2 and bedroom and ideal:
        return lay["full_pts"]
    if (rooms >= 2 and bedroom) or (aneks and bedroom):
        return lay["alcove_pts"]
    if walk or rooms >= 2:
        return lay["walkthrough_pts"]
    return 0


def score_standard(text: str, std: dict) -> int:
    text = text.lower()
    if _has(text, std["renovated_keywords"]):
        return std["renovated_pts"]
    if _has(text, std["neglected_keywords"]):
        return std["neglected_pts"]
    if _has(text, std["good_keywords"]):
        return std["good_pts"]
    if _has(text, std["average_keywords"]):
        return std["average_pts"]
    return std["default"]


def score_equipment(text: str, eq: dict) -> tuple[int, list[str]]:
    text = text.lower()
    found = [name for name, kws in eq["items"].items() if _has(text, kws)]
    return min(len(found) * eq["per_item"], 10), found


def compute_penalties(offer: Offer, cost: CostBreakdown, text: str,
                      now: datetime, pen: dict) -> list[tuple[str, int]]:
    text = text.lower()
    out: list[tuple[str, int]] = []

    # Prowizja pośrednika.
    if not _has(text, pen["no_commission_keywords"]):
        if _has(text, pen["commission_full_keywords"]):
            out.append(("prowizja 100%", pen["commission_full"]))
        elif _has(text, pen["commission_any_keywords"]):
            out.append(("prowizja pośrednika", pen["commission_partial"]))

    if cost.heating == "electric":
        out.append(("ogrzewanie elektryczne", pen["electric_heating"]))

    if cost.czynsz_estimated:
        out.append(("brak danych o czynszu", pen["rent_unknown"]))

    if offer.created_time:
        try:
            days = (now - datetime.fromisoformat(offer.created_time)).total_seconds() / 86400
            if 4 <= days <= 7:
                out.append(("ogłoszenie 4–7 dni", pen["listing_4_7_days"]))
        except ValueError:
            pass

    return out


def score_offer(offer: Offer, cost: CostBreakdown, text: str,
                now: datetime, config: dict) -> Score:
    sc = config["scoring"]
    t = text.lower()

    loc_pts, loc_tier = score_location(offer.city, offer.district, sc["location"])
    eq_pts, eq_found = score_equipment(t, sc["equipment"])
    std_pts = score_standard(t, sc["standard"])

    breakdown = {
        "Cena": score_price(cost.total, sc["price"]),
        "Lokalizacja": loc_pts,
        "Układ i metraż": score_layout(offer, t, sc["layout"]),
        "Standard": std_pts,
        "Wyposażenie": eq_pts,
    }
    penalties = compute_penalties(offer, cost, t, now, sc["penalties"])
    raw = sum(breakdown.values()) + sum(d for _, d in penalties)
    total = max(0, min(100, raw))

    plusy, minusy, do_zapytania = [], [], []

    if breakdown["Cena"] >= 25 and cost.total is not None:
        plusy.append(f"koszt całkowity w budżecie ({cost.total} zł)")
    if loc_tier in ("best", "very_good"):
        plusy.append(f"dobra lokalizacja ({offer.district})")
    if eq_found:
        plusy.append("w cenie: " + ", ".join(eq_found))
    if std_pts >= sc["standard"]["renovated_pts"]:
        plusy.append("po remoncie / wysoki standard")
    if offer.has_phone:
        plusy.append("telefon w ogłoszeniu")

    for label, _ in penalties:
        minusy.append(label)
    if loc_pts <= sc["location"]["tier_points"]["other"]:
        minusy.append("lokalizacja poza głównymi dzielnicami")

    # SPEC/decyzja: układ oceniany z opisu -> zawsze poproś o potwierdzenie na zdjęciach.
    do_zapytania.append("układ/sypialnia — poproś o zdjęcia i potwierdź rozkład")
    do_zapytania.append("koszt na start — dopytaj o kaucję i ewentualną prowizję")
    if cost.media_estimated:
        do_zapytania.append("media/ogrzewanie — dopytaj (kwota oszacowana)")
    if cost.czynsz_estimated:
        do_zapytania.append("czynsz administracyjny — dopytaj (oszacowany)")
    if not offer.has_phone:
        do_zapytania.append("brak telefonu — poproś o numer/kontakt")

    return Score(total, breakdown, penalties, plusy, minusy, do_zapytania)
