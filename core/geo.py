"""Geografia: odległość i szacowany czas dojścia do stacji SKM/PKM.

SPEC: nie liczymy czasów PRZEJAZDU (zmyślanie). Podajemy tylko szacowany czas
DOJŚCIA do najbliższej stacji = odległość w linii prostej × 1,3, podzielona
przez prędkość marszu. Współrzędne stacji są w config.yaml (przybliżone,
edytowalne) — służą do wyświetlania, nie do twardej oceny lokalizacji
(ta idzie po tabeli dzielnic z SPEC).
"""

from __future__ import annotations

import math

_EARTH_R = 6_371_000  # promień Ziemi w metrach


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Odległość w linii prostej między dwoma punktami (metry)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_R * math.asin(math.sqrt(a))


def walk_minutes(dist_m: float, straight_factor: float, speed_m_per_min: float) -> int:
    """Szacowany czas dojścia pieszo (min) z odległości w linii prostej."""
    return round(dist_m * straight_factor / speed_m_per_min)


def _nearest(lat, lon, stations: list[dict]) -> tuple[dict, float] | None:
    if lat is None or lon is None or not stations:
        return None
    best = min(stations, key=lambda s: haversine(lat, lon, s["lat"], s["lon"]))
    return best, haversine(lat, lon, best["lat"], best["lon"])


def nearest_station(lat, lon, stations: list[dict]) -> tuple[dict, float] | None:
    """Najbliższa stacja (dowolna). None gdy brak współrzędnych/stacji."""
    return _nearest(lat, lon, stations)


def nearest_on_axis(lat, lon, stations: list[dict]) -> tuple[dict, float] | None:
    """Najbliższa stacja NA OSI SKM (obsługującej oba wydziały bez przesiadki)."""
    return _nearest(lat, lon, [s for s in stations if s.get("on_axis")])
