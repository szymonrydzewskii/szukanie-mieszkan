"""Portal OLX.

Podejście (SPEC): korzystamy z wewnętrznego endpointu JSON OLX
(`/api/v1/offers/`), nie z parsowania HTML. Struktura JSON jest znacznie
stabilniejsza niż selektory CSS.

Etap 1: zaimplementowany jest tylko `fetch_raw()` (podgląd surowej odpowiedzi).
Parser `fetch()` powstanie po zatwierdzeniu mapowania pól przez użytkownika.
"""

from __future__ import annotations

import random
import time
from typing import Any

import requests

from .base import Offer, Source, SourceError


class OlxSource(Source):
    name = "olx"

    def _sleep_jitter(self) -> None:
        lo, hi = self.http.get("jitter_seconds", [0, 0])
        if hi > 0:
            time.sleep(random.uniform(lo, hi))

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        """Pojedyncze zapytanie do API OLX. Rzuca SourceError przy każdym błędzie."""
        headers = {
            "User-Agent": self.http["user_agent"],
            "Accept": "application/json",
        }
        try:
            resp = requests.get(
                self.config["base_url"],
                params=params,
                headers=headers,
                timeout=self.http["timeout_seconds"],
            )
        except requests.RequestException as e:
            raise SourceError(f"OLX: błąd sieci przy zapytaniu {params}: {e}") from e

        if resp.status_code != 200:
            # 403/captcha traktujemy jako błąd do zgłoszenia, nie jako "pusto".
            raise SourceError(
                f"OLX: HTTP {resp.status_code} dla params={params} "
                f"(pierwsze 300 znaków: {resp.text[:300]!r})"
            )
        try:
            return resp.json()
        except ValueError as e:
            raise SourceError(f"OLX: odpowiedź nie jest JSON-em: {e}") from e

    def _city_params(self, city_id: int) -> dict[str, Any]:
        return {
            "offset": 0,
            "limit": self.config["limit"],
            "category_id": self.config["category_id"],
            "city_id": city_id,
            "sort_by": self.config["sort_by"],
        }

    def fetch_raw(self) -> dict[str, Any]:
        """Surowe odpowiedzi API dla każdego skonfigurowanego miasta."""
        out: dict[str, Any] = {}
        for city_name, city_id in self.config["cities"].items():
            self._sleep_jitter()
            out[city_name] = self._get(self._city_params(city_id))
        return out

    # enum OLX "rooms" -> liczba pokoi
    _ROOMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}

    @staticmethod
    def _param(raw_offer: dict[str, Any], key: str) -> dict[str, Any] | None:
        for p in raw_offer.get("params", []):
            if p.get("key") == key:
                return p.get("value")
        return None

    def _parse_offer(self, o: dict[str, Any]) -> Offer:
        price_v = self._param(o, "price")
        price = price_v.get("value") if price_v else None

        price_note = None
        if price_v:
            if price_v.get("arranged"):
                price_note = "do uzgodnienia"
            elif price_v.get("negotiable"):
                price_note = "do negocjacji"

        rent_v = self._param(o, "rent")
        rent_admin = None
        if rent_v and str(rent_v.get("key", "")).strip():
            try:
                rent_admin = int(float(str(rent_v["key"]).replace(",", ".")))
            except (TypeError, ValueError):
                rent_admin = None  # nie zmyślamy; brak danych zostaje None

        area_v = self._param(o, "m")
        area_m2 = None
        if area_v and str(area_v.get("key", "")).strip():
            try:
                area_m2 = float(str(area_v["key"]).replace(",", "."))
            except (TypeError, ValueError):
                area_m2 = None

        rooms_v = self._param(o, "rooms")
        rooms = self._ROOMS.get(rooms_v.get("key")) if rooms_v else None

        built_v = self._param(o, "builttype")
        builttype = built_v.get("key") if built_v else None

        floor_v = self._param(o, "floor_select")
        floor = None
        if floor_v and floor_v.get("key"):
            n = str(floor_v["key"]).replace("floor_", "")
            floor = "parter" if n == "0" else n

        loc = o.get("location", {}) or {}
        city = (loc.get("city") or {}).get("name")
        district = (loc.get("district") or {}).get("name")

        geo = o.get("map") or {}
        lat = geo.get("lat")
        lon = geo.get("lon")

        photos = o.get("photos") or []
        photo_url = photos[0].get("link") if photos else None

        contact = o.get("contact") or {}

        return Offer(
            source=self.name,
            source_id=str(o.get("id")),
            url=o.get("url", ""),
            title=o.get("title", ""),
            price=price,
            price_note=price_note,
            rent_admin=rent_admin,
            area_m2=area_m2,
            rooms=rooms,
            floor=floor,
            builttype=builttype,
            city=city,
            district=district,
            lat=lat,
            lon=lon,
            created_time=o.get("created_time"),
            description=o.get("description"),
            photo_url=photo_url,
            has_phone=bool(contact.get("phone")),
            raw=o,
        )

    def fetch(self) -> list[Offer]:
        """Pobierz oferty ze wszystkich skonfigurowanych miast Trójmiasta.

        Błąd sieci/HTTP/parsowania -> SourceError (nigdy ciche []).
        Pusta lista oznacza wyłącznie: sprawdziłem i nic nie ma.
        """
        offers: list[Offer] = []
        for city_id in self.config["cities"].values():
            self._sleep_jitter()
            payload = self._get(self._city_params(city_id))
            data = payload.get("data")
            if not isinstance(data, list):
                raise SourceError(
                    f"OLX: nieoczekiwany kształt odpowiedzi dla city_id={city_id} "
                    f"(brak listy 'data')"
                )
            for raw_offer in data:
                try:
                    offers.append(self._parse_offer(raw_offer))
                except Exception as e:
                    # Błąd parsowania pojedynczej oferty jest awarią, nie "pustką".
                    raise SourceError(
                        f"OLX: błąd parsowania oferty id={raw_offer.get('id')}: {e}"
                    ) from e

        # Najnowsze najpierw (deterministycznie; promowane w API bywają przypięte na górze).
        offers.sort(key=lambda x: x.created_time or "", reverse=True)
        return offers
