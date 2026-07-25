"""Budowa embeda Discorda i wysyłka przez webhook.

Model bez oceniania (decyzja użytkownika): embed pokazuje FAKTY o ofercie —
koszt całkowity z rozbiciem, lokalizacja + stacja SKM, metraż/pokoje/piętro,
sekcja "Do zapytania" (co dopytać, bo oszacowane/nieznane) i gotowa wiadomość
do właściciela. Żadnej liczby /100.

Kanał główny (#mieszkania) = pełny embed (kolor zielony). #odrzucone =
kompaktowy embed prawie-trafienia z powodem (kolor bursztynowy).
"""

from __future__ import annotations

import os
import time

import requests

from core.cost import CostBreakdown
from sources.base import Offer

COLOR_GREEN = 0x2ECC71     # dopasowanie -> #mieszkania / #sprzedaz
COLOR_AMBER = 0xE67E22     # prawie-trafienie -> #odrzucone / #sprzedaz-odrzucone
COLOR_GOLD = 0xF1C40F      # 🔥 okazja (sprzedaż, niskie zł/m²)
COLOR_RED = 0xE74C3C       # alert (padnięte źródło, luka w przebiegach)
COLOR_BLUE = 0x3498DB      # dzienne podsumowanie


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


def build_questions(offer: Offer, cost: CostBreakdown) -> list[str]:
    """Praktyczne pytania do właściciela/ogłoszenia (braki i szacunki)."""
    q = ["układ/sypialnia — poproś o zdjęcia i potwierdź rozkład",
         "koszt na start — dopytaj o kaucję i ewentualną prowizję"]
    if cost.media_estimated:
        q.append("media/ogrzewanie — dopytaj (kwota oszacowana)")
    if cost.czynsz_estimated:
        q.append("czynsz administracyjny — dopytaj (oszacowany)")
    if not offer.has_phone:
        q.append("brak telefonu — poproś o numer/kontakt")
    return q


def build_embed(
    offer: Offer,
    cost: CostBreakdown,
    *,
    station_info: tuple[str, int] | None = None,
    photo_size: str = "640x480",
    price_drop: tuple[int, int] | None = None,
    owner_message_template: str | None = None,
) -> dict:
    """Pełny embed na kanał główny (czysta struktura, bez sklejania stringów)."""
    price_note = f" ({offer.price_note})" if offer.price_note else ""
    fields = []

    if price_drop is not None:
        old, new = price_drop
        fields.append({"name": "🔻 OBNIŻKA",
                       "value": f"{_fmt_pln(old)} → {_fmt_pln(new)}", "inline": False})

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

    if cost.notes:
        fields.append({"name": "⚠ Oszacowano",
                       "value": "\n".join(f"• {n}" for n in cost.notes), "inline": False})
    fields.append({"name": "Do zapytania",
                   "value": "\n".join(f"❔ {q}" for q in build_questions(offer, cost)), "inline": False})
    if owner_message_template:
        fields.append({"name": "✉ Wiadomość do właściciela (skopiuj)",
                       "value": render_owner_message(offer, owner_message_template), "inline": False})

    embed: dict = {
        "title": offer.title[:256] if offer.title else "(bez tytułu)",
        "url": offer.url,
        "color": COLOR_GREEN,
        "fields": fields,
        "footer": {"text": f"{offer.source.upper()} · id {offer.source_id}"},
    }
    if offer.created_time:
        embed["timestamp"] = offer.created_time
    thumb = _photo_url(offer, photo_size)
    if thumb:
        embed["thumbnail"] = {"url": thumb}
    return embed


def build_rejected_embed(offer: Offer, cost: CostBreakdown, reason: str) -> dict:
    """Kompaktowy embed na #odrzucone (prawie-trafienie) — powód + podstawowe fakty."""
    return {
        "title": offer.title[:256] if offer.title else "(bez tytułu)",
        "url": offer.url,
        "color": COLOR_AMBER,
        "fields": [
            {"name": "Prawie-trafienie", "value": reason, "inline": False},
            {"name": "Koszt całkowity", "value": _fmt_pln(cost.total), "inline": True},
            {"name": "Metraż / pokoje",
             "value": (f"{offer.area_m2:g} m²" if offer.area_m2 else "?")
                      + f" · {offer.rooms if offer.rooms is not None else '?'} pok", "inline": True},
        ],
        "footer": {"text": f"{offer.source.upper()} · id {offer.source_id} · {offer.district or offer.city or ''}"},
    }


def build_sale_embed(
    offer: Offer,
    price_per_m2: int | None,
    is_deal: bool,
    *,
    station_info: tuple[str, int] | None = None,
    photo_size: str = "640x480",
    buy_message_template: str | None = None,
) -> dict:
    """Pełny embed sprzedaży (#sprzedaz): cena zakupu + zł/m² + fakty. 🔥 gdy okazja."""
    fields = []
    if is_deal:
        fields.append({"name": "🔥 OKAZJA", "value": "niska cena za m²", "inline": False})
    fields.append({"name": "Cena", "value": _fmt_pln(offer.price), "inline": True})
    fields.append({"name": "Cena za m²",
                   "value": _fmt_pln(price_per_m2) + "/m²" if price_per_m2 is not None else "brak danych",
                   "inline": True})
    fields.append({"name": "Powierzchnia",
                   "value": f"{offer.area_m2:g} m²" if offer.area_m2 is not None else "brak danych",
                   "inline": True})
    fields.append({"name": "Pokoje",
                   "value": str(offer.rooms) if offer.rooms is not None else "brak danych", "inline": True})
    fields.append({"name": "Piętro", "value": offer.floor or "brak danych", "inline": True})

    loc = " · ".join(x for x in (offer.city, offer.district) if x) or "brak danych"
    if station_info is not None:
        loc += f"\nSKM {station_info[0]} — ~{station_info[1]} min pieszo (szac.)"
    fields.append({"name": "Lokalizacja", "value": loc, "inline": False})
    fields.append({"name": "Telefon", "value": "📞 tak" if offer.has_phone else "nie", "inline": True})
    if buy_message_template:
        fields.append({"name": "✉ Wiadomość do sprzedającego (skopiuj)",
                       "value": render_owner_message(offer, buy_message_template), "inline": False})

    embed: dict = {
        "title": offer.title[:256] if offer.title else "(bez tytułu)",
        "url": offer.url,
        "color": COLOR_GOLD if is_deal else COLOR_GREEN,
        "fields": fields,
        "footer": {"text": f"{offer.source.upper()} · id {offer.source_id}"},
    }
    if offer.created_time:
        embed["timestamp"] = offer.created_time
    thumb = _photo_url(offer, photo_size)
    if thumb:
        embed["thumbnail"] = {"url": thumb}
    return embed


def build_sale_rejected_embed(offer: Offer, price_per_m2: int | None, reason: str) -> dict:
    """Kompaktowy embed sprzedaży na #sprzedaz-odrzucone (prawie-trafienie)."""
    return {
        "title": offer.title[:256] if offer.title else "(bez tytułu)",
        "url": offer.url,
        "color": COLOR_AMBER,
        "fields": [
            {"name": "Prawie-trafienie", "value": reason, "inline": False},
            {"name": "Cena", "value": _fmt_pln(offer.price), "inline": True},
            {"name": "Cena za m²",
             "value": _fmt_pln(price_per_m2) + "/m²" if price_per_m2 is not None else "?", "inline": True},
            {"name": "Metraż / pokoje",
             "value": (f"{offer.area_m2:g} m²" if offer.area_m2 else "?")
                      + f" · {offer.rooms if offer.rooms is not None else '?'} pok", "inline": True},
        ],
        "footer": {"text": f"{offer.source.upper()} · id {offer.source_id} · {offer.district or offer.city or ''}"},
    }


def build_alert_embed(problems: list[str]) -> dict:
    """Embed alertu na #alerty — lista problemów (padnięte źródło, luka w przebiegach)."""
    return {
        "title": "⚠ Alert bota mieszkaniowego",
        "color": COLOR_RED,
        "fields": [{"name": "Problemy", "value": "\n".join(f"• {p}" for p in problems),
                    "inline": False}],
    }


def build_digest_embed(digest: dict) -> dict:
    """Embed dziennego podsumowania na #alerty — dowód, że system żyje."""
    rows = []
    total_main = total_near = total_fetched = 0
    for source, s in sorted(digest.get("sources", {}).items()):
        total_fetched += s.get("fetched", 0)
        total_main += s.get("sent_main", 0)
        total_near += s.get("sent_near", 0)
        rows.append(
            f"**{source}** — sprawdzone {s.get('fetched', 0)} · wysłane {s.get('sent_main', 0)} · "
            f"prawie {s.get('sent_near', 0)} · odrzucone {s.get('dropped', 0)}"
        )

    fields = [{
        "name": "Podsumowanie",
        "value": (f"sprawdzone **{total_fetched}** · wysłane **{total_main}** · "
                  f"prawie-trafienia **{total_near}**"),
        "inline": False,
    }]
    if rows:
        fields.append({"name": "Per portal", "value": "\n".join(rows), "inline": False})
    errors = digest.get("errors") or []
    if errors:
        fields.append({"name": "⚠ Błędy w ciągu dnia",
                       "value": "\n".join(f"• {e}" for e in errors), "inline": False})

    return {
        "title": f"📊 Raport dzienny — {digest.get('date', '?')}",
        "color": COLOR_BLUE,
        "fields": fields,
    }


def send_monitoring(embed: dict, webhook_env: str = "DISCORD_WEBHOOK_ALERTS",
                    timeout: int = 20) -> None:
    """Wyślij embed monitoringu (alert lub raport) na kanał #alerty."""
    _post(get_webhook(webhook_env), embed, timeout)


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
    cost: CostBreakdown,
    *,
    channel: str = "main",
    reason: str = "",
    station_info: tuple[str, int] | None = None,
    photo_size: str = "640x480",
    price_drop: tuple[int, int] | None = None,
    owner_message_template: str | None = None,
    webhook_env: str = "DISCORD_WEBHOOK",
    timeout: int = 20,
) -> None:
    """Wyślij ofertę na wskazany kanał (webhook z env). Rzuca NotifyError przy błędzie."""
    webhook = get_webhook(webhook_env)
    if channel == "rejected":
        embed = build_rejected_embed(offer, cost, reason)
    else:
        embed = build_embed(offer, cost, station_info=station_info, photo_size=photo_size,
                            price_drop=price_drop, owner_message_template=owner_message_template)
    _post(webhook, embed, timeout)


def send_sale_offer(
    offer: Offer,
    price_per_m2: int | None,
    is_deal: bool,
    *,
    channel: str = "main",
    reason: str = "",
    station_info: tuple[str, int] | None = None,
    photo_size: str = "640x480",
    buy_message_template: str | None = None,
    webhook_env: str,
    timeout: int = 20,
) -> None:
    """Wyślij ofertę SPRZEDAŻY na kanał sprzedaży (webhook z env)."""
    webhook = get_webhook(webhook_env)
    if channel == "rejected":
        embed = build_sale_rejected_embed(offer, price_per_m2, reason)
    else:
        embed = build_sale_embed(offer, price_per_m2, is_deal, station_info=station_info,
                                 photo_size=photo_size, buy_message_template=buy_message_template)
    _post(webhook, embed, timeout)
