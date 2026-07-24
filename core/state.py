"""Odczyt/zapis stanu widzianych ogłoszeń (state/seen.json).

SPEC / ograniczenia techniczne:
- Stan trzymamy w małym pliku JSON commitowanym do repo (NIE SQLite).
- Na wpis tylko: {id, fingerprint, cena, data_wyslania}. Bez opisów i zdjęć.
- Wpisy starsze niż 60 dni usuwamy.
- Zapis deterministyczny (sort_keys), żeby diffy w gicie były minimalne
  i odporne na konflikty.
- Żadnych sekretów w stanie (repo publiczne).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class StateError(Exception):
    """Błąd odczytu/zapisu stanu (np. uszkodzony JSON)."""


def load_state(path: str | Path) -> dict[str, Any]:
    """Wczytaj stan. Brak pliku = pusty stan (cold start). Uszkodzony = StateError."""
    path = Path(path)
    if not path.exists():
        return {"version": 1, "seen": {}, "high_water": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        # Uszkodzony stan zgłaszamy głośno — cichy reset = zalew ponownych wysyłek.
        raise StateError(f"Nie mogę wczytać stanu {path}: {e}") from e
    data.setdefault("version", 1)
    data.setdefault("seen", {})
    data.setdefault("high_water", {})
    return data


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    """Zapisz stan deterministycznie (posortowane klucze, wcięcie 2)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")


def record(
    state: dict[str, Any],
    key: str,
    fingerprint: str,
    cena: int | None,
    sent_at: datetime,
) -> None:
    """Dodaj lub zaktualizuj wpis. Zapisuje wyłącznie 4 pola z SPEC."""
    state["seen"][key] = {
        "id": key,
        "fingerprint": fingerprint,
        "cena": cena,
        "data_wyslania": sent_at.isoformat(),
    }


def is_seen(state: dict[str, Any], key: str) -> bool:
    return key in state["seen"]


def get_entry(state: dict[str, Any], key: str) -> dict[str, Any] | None:
    return state["seen"].get(key)


def has_source(state: dict[str, Any], source: str) -> bool:
    """Czy w stanie jest jakikolwiek wpis danego portalu (klucz 'portal:...')."""
    prefix = f"{source}:"
    return any(k.startswith(prefix) for k in state["seen"])


def get_high_water(state: dict[str, Any], source: str) -> str | None:
    """Najnowszy `created_time` (ISO), jaki widzieliśmy dla danego portalu.

    Granica nowości: oferty starsze/równe temu znacznikowi to nie są nowe
    ogłoszenia, tylko stare (często promowane/bumpowane) rotujące w okno wyników.
    """
    return state.setdefault("high_water", {}).get(source)


def set_high_water(state: dict[str, Any], source: str, iso: str) -> None:
    state.setdefault("high_water", {})[source] = iso


def prune(state: dict[str, Any], max_age_days: int, now: datetime) -> int:
    """Usuń wpisy starsze niż max_age_days. Zwróć liczbę usuniętych."""
    cutoff = now - timedelta(days=max_age_days)
    to_remove = []
    for key, entry in state["seen"].items():
        sent = datetime.fromisoformat(entry["data_wyslania"])
        if sent < cutoff:
            to_remove.append(key)
    for key in to_remove:
        del state["seen"][key]
    return len(to_remove)
