"""Orkiestracja bota.

Komendy:
    python main.py --once             # jeden przebieg (pobierz -> wyślij)
    python main.py --debug-raw olx    # pokaż surową odpowiedź portalu, bez parsera

`--once` jest jedynym punktem wejścia na produkcji — cron w GitHub Actions
wywołuje wyłącznie tę komendę.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from core import cost as cost_mod
from core import filters, notify, pipeline, state
from sources.base import Source
from sources.olx import OlxSource

# Rejestr portali. Dokładanie kolejnego = jedna linijka tutaj.
SOURCE_CLASSES: dict[str, type[Source]] = {
    "olx": OlxSource,
}

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _force_utf8_stdout() -> None:
    # Konsola Windows (cp1250) nie poradzi sobie z polskimi znakami w JSON-ie.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def load_dotenv() -> None:
    """Wczytaj .env do os.environ (bez nadpisywania istniejących zmiennych).

    Tylko dla wygody lokalnej. W GitHub Actions DISCORD_WEBHOOK przychodzi
    bezpośrednio ze środowiska (secrets), a pliku .env tam nie ma.
    """
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_config() -> dict[str, Any]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_source(name: str, config: dict[str, Any]) -> Source:
    if name not in SOURCE_CLASSES:
        raise SystemExit(f"Nieznany portal: {name!r}. Dostępne: {list(SOURCE_CLASSES)}")
    src_cfg = config["sources"][name]
    return SOURCE_CLASSES[name](config=src_cfg, http=config["http"])


def cmd_debug_raw(name: str, config: dict[str, Any]) -> None:
    source = build_source(name, config)
    raw = source.fetch_raw()

    for city, payload in raw.items():
        data = payload.get("data", [])
        meta = payload.get("metadata", {})
        print(f"\n===== {name} / {city} =====")
        print(f"total_elements: {meta.get('total_elements')}  |  zwrócono: {len(data)}")

    # Pełny surowy zrzut do pliku, żeby dało się go spokojnie przejrzeć.
    dump = Path(__file__).parent / f"debug_raw_{name}.json"
    with open(dump, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    print(f"\nPełny surowy zrzut zapisany do: {dump.name}")

    # Pierwsza oferta z pierwszego miasta — w całości, żeby pokazać nazwy pól.
    first_city = next(iter(raw))
    offers = raw[first_city].get("data", [])
    if offers:
        print(f"\n----- PIERWSZA OFERTA ({first_city}), pełny obiekt -----")
        print(json.dumps(offers[0], ensure_ascii=False, indent=2))


def cmd_once(config: dict[str, Any]) -> None:
    photo_size = config.get("notify", {}).get("photo_size", "640x480")
    state_cfg = config.get("state", {})
    state_path = Path(__file__).parent / state_cfg.get("path", "state/seen.json")
    max_age_days = state_cfg.get("max_age_days", 60)
    threshold = config.get("dedup", {}).get("price_drop_threshold", 100)

    st = state.load_state(state_path)
    now = datetime.now(timezone.utc)
    pruned = state.prune(st, max_age_days, now)
    if pruned:
        print(f"stan: usunięto {pruned} wpisów starszych niż {max_age_days} dni")

    def send_fn(offer, price_drop, cost):
        notify.send_offer(offer, cost=cost, photo_size=photo_size, price_drop=price_drop)
        tag = "OBNIŻKA" if price_drop else "NOWA"
        total = f"{cost.total} zł" if cost and cost.total is not None else "koszt ?"
        print(f"  -> [{tag}] {offer.source_id} ({total}) {offer.title[:45]}")

    def filter_fn(offer):
        text = filters.offer_text(offer)
        cost = cost_mod.compute_cost(offer, text, config)
        fr = filters.evaluate(offer, text, cost, config, now)
        if not fr.passed:
            print(f"  [ODRZUT] {offer.source_id} — {fr.reason}")
        return pipeline.Evaluation(passed=fr.passed, reason=fr.reason, cost=cost)

    for name, src_cfg in config["sources"].items():
        if not src_cfg.get("enabled"):
            continue
        cold = state.get_high_water(st, name) is None
        source = build_source(name, config)
        offers = source.fetch()  # rzuca wyjątek przy błędzie (nigdy ciche [])

        summary = pipeline.process_source(name, offers, st, threshold, now, send_fn, filter_fn)
        if cold:
            print(
                f"{name}: cold start — zasiano {summary['seeded']} ofert, nic nie "
                f"wysłano (kolejne przebiegi wyślą tylko nowe)"
            )
        else:
            print(
                f"{name}: pobrano {summary['fetched']} | nowe {summary['sent_new']} | "
                f"obniżki {summary['sent_drop']} | odfiltrowane {summary['filtered']} | "
                f"backfill {summary['backfilled']} | pominięte {summary['skipped']}"
            )

    state.save_state(state_path, st)
    print(f"stan zapisany: {state_path.relative_to(Path(__file__).parent)}")


def main() -> None:
    _force_utf8_stdout()
    load_dotenv()
    parser = argparse.ArgumentParser(description="Bot wyszukujący mieszkania w Trójmieście")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="jeden przebieg skanu")
    group.add_argument("--debug-raw", metavar="PORTAL", help="pokaż surową odpowiedź portalu")
    args = parser.parse_args()

    config = load_config()

    if args.debug_raw:
        cmd_debug_raw(args.debug_raw, config)
    elif args.once:
        cmd_once(config)


if __name__ == "__main__":
    main()
