"""Portal Trojmiasto.pl (ogłoszenia najmu).

Trojmiasto renderuje listę po stronie serwera (brak wewnętrznego JSON), więc
parsujemy HTML przez BeautifulSoup. Cała potrzebna treść jest na LIŚCIE
(id, tytuł, lokalizacja, metraż, pokoje, piętro, cena, data) — nie otwieramy
szczegółów ofert (to byłoby wiele zapytań = ryzyko blokady).

Nowość liczymy po ID (rosnące), nie po dacie: data na liście bywa datą BUMPU
("Zaktualizowano"), więc data nie odróżnia nowej oferty od odświeżonej starej.
`fetch()` przy błędzie sieci/parsowania rzuca SourceError (nigdy ciche []).
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

import requests
from bs4 import BeautifulSoup

from .base import Offer, Source, SourceError

try:
    from zoneinfo import ZoneInfo
    _WARSAW: Any = ZoneInfo("Europe/Warsaw")
except Exception:  # brak bazy stref (np. Windows bez tzdata) -> stałe +02:00
    from datetime import timedelta, timezone
    _WARSAW = timezone(timedelta(hours=2))

_CITIES = ("Gdańsk", "Sopot", "Gdynia")
_ID_RE = re.compile(r"ogl(\d+)\.html")
_NUM_RE = re.compile(r"[\d]+(?:[.,]\d+)?")

# Bazowa lista najmu Trojmiasto miesza typy (mieszkania/lokale/pokoje/domy), a
# filtr URL nie działa przez GET. Odsiewamy nie-mieszkania po tytule. UWAGA:
# "pokój" (z ó) NIE jest podłańcuchem "pokoje"/"pokoi" (z o), więc mieszkania
# 2-/3-pokojowe przechodzą. Dotyczy WYŁĄCZNIE Trojmiasto (OLX ma bogaty opis).
_NON_APARTMENT_TITLE = (
    "pokój", "lokal", "magazyn", "self storage", "hala ", "biuro", "garaż",
    "miejsce postojowe", "działka", "kebab", "restauracja", "dom ",
)


class TrojmiastoSource(Source):
    name = "trojmiasto"

    def _sleep_jitter(self) -> None:
        lo, hi = self.http.get("jitter_seconds", [0, 0])
        if hi > 0:
            time.sleep(__import__("random").uniform(lo, hi))

    def _get_html(self, url: str) -> str:
        headers = {"User-Agent": self.http["user_agent"], "Accept-Language": "pl"}
        try:
            resp = requests.get(url, headers=headers, timeout=self.http["timeout_seconds"])
        except requests.RequestException as e:
            raise SourceError(f"Trojmiasto: błąd sieci ({url}): {e}") from e
        if resp.status_code != 200:
            raise SourceError(
                f"Trojmiasto: HTTP {resp.status_code} dla {url} "
                f"(pierwsze 300 znaków: {resp.text[:300]!r})"
            )
        return resp.text

    def _page_url(self, page: int) -> str:
        """URL kolejnej strony wyników (paginacja Trojmiasto: ?strona=N)."""
        base = self.config["base_url"]
        if page <= 1:
            return base
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}strona={page}"

    def fetch_raw(self) -> dict[str, str]:
        out = {}
        for page in range(1, self.config.get("pages", 1) + 1):
            self._sleep_jitter()
            out[f"strona_{page}"] = self._get_html(self._page_url(page))
        return out

    @staticmethod
    def _num(text: str | None) -> str | None:
        if not text:
            return None
        m = _NUM_RE.search(text.replace(" ", "").replace("\xa0", ""))
        return m.group(0) if m else None

    @staticmethod
    def _icon(item, kind: str) -> str | None:
        el = item.select_one(f".details--icons--element--{kind} .list__item__details__icons__element__desc")
        return el.get_text(strip=True) if el else None

    def _parse_item(self, item) -> Offer | None:
        link = item.select_one('a[href*="ogl"]')
        if not link:
            return None
        m = _ID_RE.search(link.get("href", ""))
        if not m:
            return None
        oid = m.group(1)

        title_el = item.select_one(".list__item__content__title__name")
        price_el = item.select_one(".list__item__price__value")
        if not title_el or not price_el:
            return None

        title = title_el.get_text(strip=True)
        low = title.lower()
        if any(marker in low for marker in _NON_APARTMENT_TITLE):
            return None  # lokal / pokój / magazyn / dom — nie samodzielne mieszkanie

        # Cena (najem) — z listy; czynsz/media doszacuje core.cost.
        price_num = self._num(price_el.get_text())
        price = int(price_num) if price_num else None

        area_num = self._num(self._icon(item, "powierzchnia"))
        area = float(area_num.replace(",", ".")) if area_num else None

        rooms_num = self._num(self._icon(item, "l_pokoi"))
        rooms = int(rooms_num) if rooms_num else None

        floor_raw = self._icon(item, "pietro")
        floor = None
        if floor_raw:
            low = floor_raw.lower()
            floor = "parter" if "parter" in low else (self._num(floor_raw) or None)

        # Lokalizacja: "Miasto Dzielnica..., Ulica" -> miasto + dzielnica.
        sub_el = item.select_one(".list__item__content__subtitle")
        city = district = None
        if sub_el:
            left = sub_el.get_text(strip=True).split(",")[0].strip()
            for c in _CITIES:
                if left.startswith(c):
                    city = c
                    district = left[len(c):].strip() or None
                    break
            else:
                district = left or None

        created_time = None
        t = item.select_one(".listItemFooter__date time")
        if t and t.get("datetime"):
            try:
                dt = datetime.strptime(t["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=_WARSAW)
                created_time = dt.isoformat()
            except ValueError:
                pass

        return Offer(
            source=self.name,
            source_id=oid,
            url=link.get("href", ""),
            title=title,
            price=price,
            area_m2=area,
            rooms=rooms,
            floor=floor,
            city=city,
            district=district,
            created_time=created_time,
            novelty_key=f"{int(oid):012d}",   # nowość po ID (odporne na bumpy dat)
        )

    def _parse_html(self, html: str) -> list[Offer]:
        soup = BeautifulSoup(html, "html.parser")
        offers = []
        for item in soup.select(".list__item"):
            try:
                offer = self._parse_item(item)
            except Exception as e:
                raise SourceError(f"Trojmiasto: błąd parsowania oferty: {e}") from e
            if offer:
                offers.append(offer)
        return offers

    def fetch(self) -> list[Offer]:
        # Lista Trojmiasto miesza typy (mieszkania/lokale/pokoje), więc jedna strona
        # daje ~15 mieszkań. Kilka stron zwiększa pokrycie i daje zapas, gdy cron
        # pominie przebiegi. Jitter między stronami (kultura pobierania).
        offers: list[Offer] = []
        seen_ids: set[str] = set()
        for page in range(1, self.config.get("pages", 1) + 1):
            self._sleep_jitter()
            for offer in self._parse_html(self._get_html(self._page_url(page))):
                if offer.source_id not in seen_ids:
                    seen_ids.add(offer.source_id)
                    offers.append(offer)
        if not offers:
            # Zero sparsowanych ofert przy stronie 200 = zmiana layoutu/blokada, nie "pusto".
            raise SourceError(
                "Trojmiasto: strona pobrana, ale nie sparsowano żadnej oferty "
                "(możliwa zmiana layoutu selektorów albo miękka blokada)."
            )
        return offers
