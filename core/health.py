"""Monitoring: zdrowie źródeł, wykrywanie martwego crona, dzienne podsumowanie.

SPEC (MONITORING): jeśli źródło rzuci wyjątek albo zwróci zero ogłoszeń (nawet
już widzianych) w trzech kolejnych przebiegach → alert z nazwą źródła i treścią
błędu. Raz dziennie podsumowanie: ile sprawdzonych per źródło, ile wysłanych,
ile odrzuconych.

Dodatkowo (nie w SPEC, ale bolało w praktyce): wykrywanie luki między
przebiegami — jeśli zewnętrzny cron padnie, bot sam to zgłosi po powrocie.

Cały stan mieszka w commitowanym seen.json, więc trzymamy go MAŁY: liczniki
i krótkie komunikaty, bez historii ofert.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

_MAX_ERRORS_PER_DAY = 5


def note_run(state: dict[str, Any], now: datetime, max_gap_hours: float) -> str | None:
    """Zapisz czas przebiegu. Zwróć komunikat, jeśli poprzedni był dawno (cron padł)."""
    prev = state.get("last_run")
    state["last_run"] = now.isoformat()
    if not prev:
        return None
    try:
        gap_h = (now - datetime.fromisoformat(prev)).total_seconds() / 3600
    except ValueError:
        return None
    if gap_h >= max_gap_hours:
        return (f"Przerwa {gap_h:.1f} h między przebiegami (poprzedni: {prev}). "
                f"Zewnętrzny cron mógł nie działać.")
    return None


def record_source(
    state: dict[str, Any],
    source: str,
    fetched: int,
    error: str | None,
    threshold: int,
    realert_every: int,
) -> str | None:
    """Zaktualizuj licznik nieudanych przebiegów źródła.

    Zły przebieg = wyjątek ALBO zero pobranych ofert. Zwraca treść alertu przy
    osiągnięciu progu i potem co `realert_every` przebiegów (żeby nie spamować).
    """
    entry = state.setdefault("health", {}).setdefault(source, {"bad": 0, "last_error": None})

    if error is None and fetched > 0:
        entry["bad"] = 0
        entry["last_error"] = None
        return None

    entry["bad"] += 1
    entry["last_error"] = error or "zero ofert"
    n = entry["bad"]
    if n == threshold or (n > threshold and (n - threshold) % realert_every == 0):
        return f"{source}: {n} kolejnych nieudanych przebiegów — {entry['last_error']}"
    return None


def accumulate_digest(
    state: dict[str, Any],
    day: str,
    source: str,
    summary: dict[str, Any],
    error: str | None,
) -> None:
    """Dolicz wynik przebiegu do podsumowania danego dnia (klucz: data lokalna)."""
    days = state.setdefault("digest", {}).setdefault("days", {})
    bucket = days.setdefault(day, {"sources": {}, "errors": []})

    stats = bucket["sources"].setdefault(
        source, {"fetched": 0, "sent_main": 0, "sent_near": 0, "dropped": 0}
    )
    for key in stats:
        stats[key] += summary.get(key, 0)

    if error:
        line = f"{source}: {error}"
        errors = bucket["errors"]
        if line not in errors and len(errors) < _MAX_ERRORS_PER_DAY:
            errors.append(line)


def due_digest(state: dict[str, Any], now_local: datetime, digest_hour: int) -> dict | None:
    """Zwróć podsumowanie zamkniętego dnia (i usuń je ze stanu), gdy pora wysyłki.

    Wysyłamy dopiero po godzinie `digest_hour` czasu lokalnego, żeby raport
    trafiał na Discorda rano, a nie zaraz po północy.
    """
    days = state.setdefault("digest", {}).setdefault("days", {})
    if now_local.hour < digest_hour:
        return None
    today = now_local.date().isoformat()
    past = sorted(d for d in days if d < today)
    if not past:
        return None
    day = past[0]
    return {"date": day, **days.pop(day)}
