"""Kalkulacja kosztu całkowitego z konserwatywnym szacowaniem.

SPEC: KOSZT CAŁKOWITY = najem + czynsz administracyjny + media.

- najem: z danych portalu (offer.price). Brak -> total nieznany (nie zmyślamy).
- czynsz administracyjny: z danych (offer.rent_admin); brak -> szacujemy po
  rodzaju zabudowy (kamienica vs reszta).
- media: NIGDY nie ma w danych OLX -> zawsze szacowane. Domyślnie stawka
  "miejskie/gazowe"; podbita do "elektryczne", jeśli w opisie wykryjemy
  ogrzewanie elektryczne (decyzja użytkownika).

Każde oszacowanie trafia do `notes` (do oznaczenia ⚠ w embedzie).
Typ ogrzewania wykrywamy z tekstu (nie jest polem strukturalnym w OLX);
kategoria "stove" (piecowe/kaflowe/węglowe) służy filtrowi twardemu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sources.base import Offer


@dataclass
class CostBreakdown:
    najem: int | None
    czynsz: int | None
    czynsz_estimated: bool
    media: int
    media_estimated: bool
    heating: str | None          # "electric" / "stove" / None
    total: int | None
    notes: list[str] = field(default_factory=list)


def detect_heating(text: str, heating_cfg: dict) -> str | None:
    """Zwróć 'stove' / 'electric' / None na podstawie słów kluczowych w opisie.

    Piecowe/węglowe ('stove') ma priorytet — to najgorszy przypadek (odrzut).
    """
    low = text.lower()
    for kw in heating_cfg.get("reject_keywords", []):
        if kw.lower() in low:
            return "stove"
    for kw in heating_cfg.get("electric_keywords", []):
        if kw.lower() in low:
            return "electric"
    return None


def compute_cost(offer: Offer, text: str, config: dict) -> CostBreakdown:
    est = config["budget"]["estimates"]
    heating = detect_heating(text, config.get("heating", {}))
    notes: list[str] = []

    najem = offer.price

    # Czynsz administracyjny. Wartości poniżej progu wiarygodności (np. "1 zł")
    # traktujemy jak brak danych — to śmieciowe placeholdery.
    min_plausible = config["budget"].get("min_plausible_rent", 0)
    if offer.rent_admin is not None and offer.rent_admin >= min_plausible:
        czynsz = offer.rent_admin
        czynsz_estimated = False
    else:
        if offer.builttype == "kamienica":
            czynsz = est["czynsz_kamienica"]
            notes.append(f"czynsz administracyjny (kamienica) ≈ {czynsz} zł")
        else:
            czynsz = est["czynsz_blok"]
            label = offer.builttype or "blok"
            notes.append(f"czynsz administracyjny ({label}) ≈ {czynsz} zł")
        czynsz_estimated = True

    # Media — zawsze szacowane.
    if heating == "electric":
        media = est["media_electric"]
        notes.append(f"media (ogrzewanie elektryczne) ≈ {media} zł")
    else:
        media = est["media_default"]
        notes.append(f"media ≈ {media} zł")
    media_estimated = True

    total = None if najem is None else najem + czynsz + media

    return CostBreakdown(
        najem=najem,
        czynsz=czynsz,
        czynsz_estimated=czynsz_estimated,
        media=media,
        media_estimated=media_estimated,
        heating=heating,
        total=total,
        notes=notes,
    )
