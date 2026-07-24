"""Budowa embeda Discorda i wysyłka przez webhook.

SPEC: embed składamy w kodzie na podstawie struktury danych, nigdy jako
sklejony string. Webhook wyłącznie ze zmiennych środowiskowych (lokalnie z
.env, na produkcji z Actions secrets) — żadnych sekretów w kodzie.

Kanał główny (#mieszkania) dostaje pełny embed z oceną, rozbiciem kosztu,
plusami/minusami, sekcją "Do zapytania" i gotową wiadomością do właściciela.
Kanał #odrzucone dostaje kompaktowy embed (ocena + powód).
"""

from __future__ import annotations

import os
import time

import requests

from core.cost import CostBreakdown
from core.scoring import Score
from sources.base import Offer

# Kolor paska wg oceny (SPEC: zielony 88+, żółty 78–87; #odrzucone szary).
COLOR_GREEN = 0x2ECC71
COLOR_YELLOW = 0xF1C40F
COLOR_REJECTED = 0x95A5A6


class NotifyError(Exception):
    """Błąd wysyłki na Discord."""


def get_webhook(env_name: str = "DISCORD_WEBHOOK") -> str:
    url = os.environ.get(env_name)
    if not url:
        raise NotifyError(
            f"Brak {env_name} w środowisku. Ustaw go w .env (lokalnie) "
            f"lub jako Actions secret (produkcja)."
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


def color_for(total: int, top: int = 88, main: int = 78) -> int:
    if total >= top:
        return COLOR_GREEN
    if total >= main:
        return COLOR_YELLOW
    return COLOR_REJECTED


def render_owner_message(offer: Offer, template: str) -> str:
    vals = {
        "district": offer.district or offer.city or "—",
        "city": offer.city or "—",
        "area": f"{offer.area_m2:g}" if offer.area_m2 is not None else "?",
        "rooms": offer.rooms if offer.rooms is not None else "?",
        "floor": offer.floor or "?",
    }
    try:
        return template.format(**vals)
    except (KeyError, IndexError, ValueError):
        return template


def _rozbicie(score: Score) -> str:
    parts = [f"{k} {v}" for k, v in score.breakdown.items()]
    line = " · ".join(parts)
    if score.penalties:
        kary = ", ".join(f"{label} {delta}" for label, delta in score.penalties)
        line += f"\n(kary: {kary})"
    return line


def build_embed(
    offer: Offer,
    score: Score,
    cost: CostBreakdown,
    station_info: tuple[str, int] | None = None,
    photo_size: str = "640x480",
    price_drop: tuple[int, int] | None = None,
    owner_message_template: str | None = None,
    thresholds: dict | None = None,
) -> dict:
    """Pełny embed na kanał główny (czysta struktura, bez sklejania stringów)."""
    th = thresholds or {"top": 88, "main": 78}
    price_note = f" ({offer.price_note})" if offer.price_note else ""
    fields = []

    if price_drop is not None:
        old, new = price_drop
        fields.append({"name": "🔻 OBNIŻKA",
                       "value": f"{_fmt_pln(old)} → {_fmt_pln(new)}", "inline": False})

    fields.append({"name": "Ocena", "value": f"**{score.total}/100**", "inline": False})
    fields.append({"name": "Rozbicie oceny", "value": _rozbicie(score), "inline": False})

    total_val = _fmt_pln(cost.total)
    if cost.total is not None and (cost.czynsz_estimated or cost.media_estimated):
        total_val += " ⚠"
    fields.append({"name": "Koszt całkowity", "value": total_val, "inline": False})

    media_val = _fmt_pln(cost.media) + " ⚠" + (" (elektr.)" if cost.heating == "electric" else "")
    fields.append({"name": "Najem", "value": _fmt_pln(offer.price) + price_note, "inline": True})
    fields.append({"name": "Czynsz admin.",
                   "value": _fmt_pln(cost.czynsz) + (" ⚠" if cost.czynsz_estimated else ""),
                   "inline": True})
    fields.append({"name": "Media", "value": media_val, "inline": True})

    fields.append({"name": "Powierzchnia",
                   "value": f"{offer.area_m2:g} m²" if offer.area_m2 is not None else "brak danych",
                   "inline": True})
    fields.append({"name": "Pokoje",
                   "value": str(offer.rooms) if offer.rooms is not None else "brak danych",
                   "inline": True})
    fields.append({"name": "Piętro", "value": offer.floor or "brak danych", "inline": True})

    loc = " · ".join(x for x in (offer.city, offer.district) if x) or "brak danych"
    if station_info is not None:
        loc += f"\nSKM {station_info[0]} — ~{station_info[1]} min pieszo (szac.)"
    fields.append({"name": "Lokalizacja", "value": loc, "inline": False})

    fields.append({"name": "Telefon", "value": "📞 tak" if offer.has_phone else "nie", "inline": True})

    if score.plusy:
        fields.append({"name": "Plusy", "value": "\n".join(f"✅ {p}" for p in score.plusy), "inline": False})
    if score.minusy:
        fields.append({"name": "Minusy", "value": "\n".join(f"➖ {m}" for m in score.minusy), "inline": False})
    if score.do_zapytania:
        fields.append({"name": "Do zapytania",
                       "value": "\n".join(f"❔ {q}" for q in score.do_zapytania), "inline": False})
    if cost.notes:
        fields.append({"name": "⚠ Oszacowano",
                       "value": "\n".join(f"• {n}" for n in cost.notes), "inline": False})
    if owner_message_template:
        fields.append({"name": "✉ Wiadomość do właściciela (skopiuj)",
                       "value": render_owner_message(offer, owner_message_template), "inline": False})

    embed: dict = {
        "title": offer.title[:256] if offer.title else "(bez tytułu)",
        "url": offer.url,
        "color": color_for(score.total, th["top"], th["main"]),
        "fields": fields,
        "footer": {"text": f"{offer.source.upper()} · id {offer.source_id}"},
    }
    if offer.created_time:
        embed["timestamp"] = offer.created_time
    thumb = _photo_url(offer, photo_size)
    if thumb:
        embed["thumbnail"] = {"url": thumb}
    return embed


def build_rejected_embed(offer: Offer, score: Score, cost: CostBreakdown, reason: str) -> dict:
    """Kompaktowy embed na #odrzucone (SPEC: jedna linijka z powodem)."""
    return {
        "title": offer.title[:256] if offer.title else "(bez tytułu)",
        "url": offer.url,
        "color": COLOR_REJECTED,
        "fields": [
            {"name": "Ocena", "value": f"{score.total}/100", "inline": True},
            {"name": "Koszt całkowity", "value": _fmt_pln(cost.total), "inline": True},
            {"name": "Powód", "value": reason, "inline": False},
        ],
        "footer": {"text": f"{offer.source.upper()} · id {offer.source_id} · {offer.district or offer.city or ''}"},
    }


def _post(webhook: str, embed: dict, timeout: int) -> None:
    payload = {"embeds": [embed]}
    resp = requests.post(webhook, json=payload, timeout=timeout)
    if resp.status_code == 429:  # rate limit — odczekaj raz
        retry_after = 1.0
        try:
            retry_after = float(resp.json().get("retry_after", 1.0))
        except ValueError:
            pass
        time.sleep(min(retry_after, 10) + 0.25)
        resp = requests.post(webhook, json=payload, timeout=timeout)
    if resp.status_code not in (200, 204):
        raise NotifyError(f"Discord odrzucił wysyłkę: HTTP {resp.status_code} ({resp.text[:300]!r})")


def send_offer(
    offer: Offer,
    score: Score,
    cost: CostBreakdown,
    *,
    channel: str = "main",
    reason: str = "",
    station_info: tuple[str, int] | None = None,
    photo_size: str = "640x480",
    price_drop: tuple[int, int] | None = None,
    owner_message_template: str | None = None,
    thresholds: dict | None = None,
    webhook_env: str = "DISCORD_WEBHOOK",
    timeout: int = 20,
) -> None:
    """Wyślij ofertę na wskazany kanał (webhook z env). Rzuca NotifyError przy błędzie."""
    webhook = get_webhook(webhook_env)
    if channel == "rejected":
        embed = build_rejected_embed(offer, score, cost, reason)
    else:
        embed = build_embed(offer, score, cost, station_info=station_info,
                            photo_size=photo_size, price_drop=price_drop,
                            owner_message_template=owner_message_template, thresholds=thresholds)
    _post(webhook, embed, timeout)
