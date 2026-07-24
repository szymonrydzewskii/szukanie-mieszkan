"""Budowa embeda Discorda i wysyłka przez webhook.

SPEC: embed składamy w kodzie na podstawie struktury danych, nigdy jako
sklejony string. Webhook wyłącznie ze zmiennej środowiskowej DISCORD_WEBHOOK
(lokalnie z pliku .env, na produkcji z secrets.DISCORD_WEBHOOK) — żadnych
sekretów w kodzie ani w configu.

Etap 1: embed pokazuje surowe dane oferty (bez oceniania, kosztu całkowitego,
plusów/minusów, wiadomości do właściciela — to dojdzie na kolejnych etapach).
"""

from __future__ import annotations

import os
import time

import requests

from core.cost import CostBreakdown
from sources.base import Offer

# Neutralny kolor na Etap 1 (kolory zależne od oceny dojdą na Etapie 4).
_COLOR_NEUTRAL = 0x3498DB


class NotifyError(Exception):
    """Błąd wysyłki na Discord."""


def get_webhook() -> str:
    url = os.environ.get("DISCORD_WEBHOOK")
    if not url:
        raise NotifyError(
            "Brak DISCORD_WEBHOOK w środowisku. Ustaw go w .env (lokalnie) "
            "lub jako secrets.DISCORD_WEBHOOK (GitHub Actions)."
        )
    return url


def _fmt_pln(value: int | None) -> str:
    if value is None:
        return "brak danych"
    return f"{value:,}".replace(",", " ") + " zł"


def _photo_url(offer: Offer, size: str) -> str | None:
    if not offer.photo_url:
        return None
    width, height = size.split("x")
    return offer.photo_url.replace("{width}", width).replace("{height}", height)


def build_embed(
    offer: Offer,
    cost: "CostBreakdown | None" = None,
    photo_size: str = "640x480",
    price_drop: tuple[int, int] | None = None,
) -> dict:
    """Zbuduj embed Discorda z obiektu Offer (czysta struktura, bez sklejania).

    cost      – rozbicie kosztu całkowitego (z ⚠ przy oszacowanych składnikach).
    price_drop=(stara, nowa) dodaje adnotację "OBNIŻKA".
    """
    price_note = f" ({offer.price_note})" if offer.price_note else ""

    fields = []
    if price_drop is not None:
        old, new = price_drop
        fields.append({
            "name": "🔻 OBNIŻKA",
            "value": f"{_fmt_pln(old)} → {_fmt_pln(new)}",
            "inline": False,
        })

    # Koszt całkowity (najbardziej istotne) + rozbicie.
    if cost is not None:
        total_val = _fmt_pln(cost.total)
        if cost.total is not None and (cost.czynsz_estimated or cost.media_estimated):
            total_val += " ⚠"
        fields.append({"name": "Koszt całkowity", "value": total_val, "inline": False})

    fields.append({"name": "Najem", "value": _fmt_pln(offer.price) + price_note, "inline": True})

    if cost is not None:
        czynsz_val = _fmt_pln(cost.czynsz) + (" ⚠" if cost.czynsz_estimated else "")
        media_val = _fmt_pln(cost.media) + " ⚠"
        if cost.heating == "electric":
            media_val += " (elektr.)"
    else:
        czynsz_val = _fmt_pln(offer.rent_admin)
        media_val = "—"
    fields.append({"name": "Czynsz admin.", "value": czynsz_val, "inline": True})
    fields.append({"name": "Media", "value": media_val, "inline": True})

    fields += [
        {
            "name": "Powierzchnia",
            "value": f"{offer.area_m2:g} m²" if offer.area_m2 is not None else "brak danych",
            "inline": True,
        },
        {
            "name": "Pokoje",
            "value": str(offer.rooms) if offer.rooms is not None else "brak danych",
            "inline": True,
        },
        {
            "name": "Telefon",
            "value": "📞 tak" if offer.has_phone else "nie",
            "inline": True,
        },
        {
            "name": "Lokalizacja",
            "value": " · ".join(x for x in (offer.city, offer.district) if x) or "brak danych",
            "inline": False,
        },
    ]

    # Sekcja "co oszacowano" (SPEC: wypisz, co dokładnie zostało oszacowane).
    if cost is not None and cost.notes:
        fields.append({
            "name": "⚠ Oszacowano",
            "value": "\n".join(f"• {n}" for n in cost.notes),
            "inline": False,
        })

    embed: dict = {
        "title": offer.title[:256] if offer.title else "(bez tytułu)",
        "url": offer.url,
        "color": _COLOR_NEUTRAL,
        "fields": fields,
        "footer": {"text": f"{offer.source.upper()} · id {offer.source_id}"},
    }
    if offer.created_time:
        embed["timestamp"] = offer.created_time
    thumb = _photo_url(offer, photo_size)
    if thumb:
        embed["thumbnail"] = {"url": thumb}
    return embed


def send_offer(
    offer: Offer,
    cost: CostBreakdown | None = None,
    photo_size: str = "640x480",
    timeout: int = 20,
    price_drop: tuple[int, int] | None = None,
) -> None:
    """Wyślij pojedynczą ofertę na główny webhook. Rzuca NotifyError przy błędzie."""
    webhook = get_webhook()
    payload = {"embeds": [build_embed(offer, cost=cost, photo_size=photo_size, price_drop=price_drop)]}

    resp = requests.post(webhook, json=payload, timeout=timeout)

    # Discord: 429 = rate limit; spróbuj raz odczekać retry_after.
    if resp.status_code == 429:
        retry_after = 1.0
        try:
            retry_after = float(resp.json().get("retry_after", 1.0))
        except ValueError:
            pass
        time.sleep(min(retry_after, 10) + 0.25)
        resp = requests.post(webhook, json=payload, timeout=timeout)

    # Sukces webhooka to zwykle 204 No Content (lub 200 przy ?wait=true).
    if resp.status_code not in (200, 204):
        raise NotifyError(
            f"Discord odrzucił wysyłkę: HTTP {resp.status_code} "
            f"({resp.text[:300]!r})"
        )
