"""Logika specyficzna dla trybu SPRZEDAŻ.

Przy kupnie metryką jest cena ZAKUPU (setki tys. zł) i cena za m² — nie
miesięczny koszt (najem+czynsz+media). Dlatego zamiast core.cost (szacowanie
czynsz/media) używamy prostego cena + zł/m², plus flagi „okazja" (niskie zł/m²).
"""

from __future__ import annotations


def price_per_m2(price: int | None, area: float | None) -> int | None:
    if price is None or not area:
        return None
    return round(price / area)


def is_deal(price: int | None, area: float | None, threshold: int) -> bool:
    """Czy oferta to okazja — cena za m² poniżej progu (sygnał, nie filtr)."""
    ppm = price_per_m2(price, area)
    return ppm is not None and ppm <= threshold
