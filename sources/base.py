"""Kontrakt między warstwami.

Każdy portal implementuje `fetch() -> list[Offer]`. Reszta systemu nie wie,
z jakiego portalu pochodzi oferta (poza polem `Offer.source`, potrzebnym do
dedupu i stanu).

ZASADA KRYTYCZNA (SPEC): `fetch()` przy błędzie sieci lub parsowania MUSI
rzucić wyjątek. Pusta lista oznacza wyłącznie "sprawdziłem i naprawdę nic
nowego nie ma" — nigdy nie może być skutkiem cichego błędu.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class SourceError(Exception):
    """Błąd pobierania/parsowania portalu. Zawsze rzucany zamiast zwracania []."""


@dataclass
class Offer:
    """Znormalizowana oferta, niezależna od portalu.

    Etap 1 wypełnia pola surowe (bez oceniania, filtrów i kalkulacji kosztów).
    Kwoty trzymamy w PLN. Pola, których portal nie podał, zostają None.
    """

    source: str                 # nazwa portalu, np. "olx"
    source_id: str              # ID ogłoszenia w obrębie portalu
    url: str
    title: str

    price: int | None = None            # najem (bez czynszu i mediów), PLN
    price_note: str | None = None       # np. "do uzgodnienia" / "do negocjacji"
    rent_admin: int | None = None       # czynsz administracyjny "dodatkowo", PLN
    area_m2: float | None = None
    rooms: int | None = None
    builttype: str | None = None        # blok / kamienica / apartamentowiec / ...

    city: str | None = None
    district: str | None = None

    created_time: str | None = None     # ISO 8601, tak jak podaje portal
    description: str | None = None
    photo_url: str | None = None        # miniatura / pierwsze zdjęcie
    has_phone: bool | None = None

    # Surowe dane portalu — przydatne przy debugowaniu i kolejnych etapach.
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class Source(ABC):
    """Klasa bazowa portalu."""

    #: krótka nazwa portalu, np. "olx" — używana w konfiguracji i stanie
    name: str

    def __init__(self, config: dict[str, Any], http: dict[str, Any]):
        self.config = config
        self.http = http

    @abstractmethod
    def fetch(self) -> list[Offer]:
        """Zwróć listę ofert. Przy błędzie sieci/parsowania rzuć SourceError."""
        raise NotImplementedError

    @abstractmethod
    def fetch_raw(self) -> Any:
        """Zwróć surową odpowiedź portalu (dla `--debug-raw`), bez parsowania."""
        raise NotImplementedError
