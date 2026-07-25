"""Portal Nieruchomosci-online.pl (ogłoszenia najmu).

Server-side HTML (brak wewnętrznego JSON per oferta — ld+json ma tylko dane
zbiorcze), więc parsujemy kafelki `div.tile` przez BeautifulSoup. Cała treść
jest na liście: id (data-id), cena, metraż, pokoje, dzielnica, a nawet OPIS
(teaser) — więc filtry tekstowe działają dobrze.

Nowość liczymy po ID (rosnące), nie po dacie (data nie jest podana na kafelku).
Wyszukiwanie jest per-miasto (URL zawiera nazwę miasta), więc pytamy po jednym
zapytaniu na miasto. `fetch()` przy błędzie sieci/parsowania rzuca SourceError.
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from .base import Offer, Source, SourceError

_ID_RE = re.compile(r"/(\d+)\.html")
_ALIAS = {"gdansk": "Gdańsk", "sopot": "Sopot", "gdynia": "Gdynia"}
_PRICE_RE = re.compile(r"([\d ]+)\s*zł")
_AREA_RE = re.compile(r"([\d ]+(?:[.,]\d+)?)\s*m")
_ROOMS_RE = re.compile(r"pokoi[:\s]*(\d+)", re.I)


class NieruchomosciOnlineSource(Source):
    name = "nieruchomosci_online"

    def _sleep_jitter(self) -> None:
        lo, hi = self.http.get("jitter_seconds", [0, 0])
        if hi > 0:
            time.sleep(__import__("random").uniform(lo, hi))

    def _get_html(self, url: str) -> str:
        headers = {"User-Agent": self.http["user_agent"], "Accept-Language": "pl"}
        try:
            resp = requests.get(url, headers=headers, timeout=self.http["timeout_seconds"])
        except requests.RequestException as e:
            raise SourceError(f"Nieruchomosci-online: błąd sieci: {e}") from e
        if resp.status_code != 200:
            raise SourceError(
                f"Nieruchomosci-online: HTTP {resp.status_code} "
                f"(pierwsze 300 znaków: {resp.text[:300]!r})"
            )
        return resp.text

    def _city_urls(self) -> dict[str, str]:
        tmpl = self.config["search_url_template"]
        return {c: tmpl.format(city=quote(c)) for c in self.config["cities"]}

    def fetch_raw(self) -> dict[str, str]:
        out = {}
        for city, url in self._city_urls().items():
            self._sleep_jitter()
            out[city] = self._get_html(url)
        return out

    @staticmethod
    def _clean(text: str | None) -> str:
        return (text or "").replace("\xa0", " ").replace(" ", " ")

    def _parse_tile(self, tile) -> Offer | None:
        did = tile.get("data-id")
        link = tile.select_one('a[href*=".html"]')
        if not did or not link:
            return None  # reklama / plug bez oferty
        if tile.get("data-market-type") == "primary":
            return None  # rynek pierwotny (deweloper) — pomijamy

        href = link.get("href", "")
        m = _ID_RE.search(href)
        oid = m.group(1) if m else did.lstrip("a")

        name_el = tile.select_one(".name")
        title = name_el.get_text(strip=True) if name_el else self._clean(link.get_text(strip=True))

        # Cena (najem) z ".title-a" ("3 600 zł 39 m² 92,31 zł/m²") — pierwsza kwota.
        ta = self._clean(tile.select_one(".title-a").get_text()) if tile.select_one(".title-a") else ""
        pm = _PRICE_RE.search(ta)
        price = int(pm.group(1).replace(" ", "")) if pm else None

        area_el = tile.select_one(".area")
        area = None
        am = _AREA_RE.search(self._clean(area_el.get_text()) if area_el else ta)
        if am:
            area = float(am.group(1).replace(" ", "").replace(",", "."))

        full_text = self._clean(tile.get_text(" ", strip=True))
        rm = _ROOMS_RE.search(full_text)
        rooms = int(rm.group(1)) if rm else None

        # Miasto z pewnego data-location-alias; dzielnica z pierwszego członu .province.
        city = _ALIAS.get(tile.get("data-location-alias"))
        district = None
        prov_el = tile.select_one(".province")
        if prov_el:
            parts = [p.strip() for p in prov_el.get_text(strip=True).split(",") if p.strip()]
            if parts:
                district = parts[0]
            if not city:  # fallback: miasto z .province (pomijając "pomorskie")
                cands = [p for p in parts if p.lower() != "pomorskie"]
                if len(cands) >= 2:
                    city = cands[-1]

        return Offer(
            source=self.name,
            source_id=oid,
            url=href,
            title=title,
            price=price,
            area_m2=area,
            rooms=rooms,
            city=city,
            district=district,
            description=full_text,          # kafelek zawiera teaser opisu -> filtry tekstowe
            novelty_key=f"{int(oid):012d}",  # nowość po ID (brak daty na kafelku)
        )

    def _parse_html(self, html: str) -> list[Offer]:
        soup = BeautifulSoup(html, "html.parser")
        offers = []
        for tile in soup.select("div.tile"):
            try:
                offer = self._parse_tile(tile)
            except Exception as e:
                raise SourceError(f"Nieruchomosci-online: błąd parsowania kafelka: {e}") from e
            if offer:
                offers.append(offer)
        return offers

    def fetch(self) -> list[Offer]:
        offers: list[Offer] = []
        for city, url in self._city_urls().items():
            self._sleep_jitter()
            offers.extend(self._parse_html(self._get_html(url)))
        if not offers:
            raise SourceError(
                "Nieruchomosci-online: strony pobrane, ale nie sparsowano żadnej oferty "
                "(możliwa zmiana layoutu albo miękka blokada Cloudflare)."
            )
        return offers
