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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from core import cost as cost_mod
from core import filters, geo, health, notify, pipeline, sale, state

try:
    from zoneinfo import ZoneInfo
    _WARSAW: Any = ZoneInfo("Europe/Warsaw")
except Exception:  # brak bazy stref -> stałe +02:00 (raport dzienny o poranku)
    _WARSAW = timezone(timedelta(hours=2))
from sources.base import Source, SourceError
from sources.nieruchomosci_online import NieruchomosciOnlineSource
from sources.olx import OlxSource
from sources.trojmiasto import TrojmiastoSource

# Rejestr portali. Dokładanie kolejnego = jedna linijka tutaj.
SOURCE_CLASSES: dict[str, type[Source]] = {
    "olx": OlxSource,
    "trojmiasto": TrojmiastoSource,
    "nieruchomosci_online": NieruchomosciOnlineSource,
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
    src_cfg = config["sources"][name]
    cls_key = src_cfg.get("class", name)  # która klasa Source (domyślnie = klucz configu)
    if cls_key not in SOURCE_CLASSES:
        raise SystemExit(f"Nieznana klasa portalu: {cls_key!r}. Dostępne: {list(SOURCE_CLASSES)}")
    src = SOURCE_CLASSES[cls_key](config=src_cfg, http=config["http"])
    # Nazwa źródła = klucz configu (np. 'olx_sale') -> osobny stan/dedup/nowość
    # dla wynajmu i sprzedaży tego samego portalu.
    src.name = name
    return src


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


def _station_info(offer, loc_cfg) -> tuple[str, int] | None:
    """Najbliższa stacja SKM (preferencyjnie na osi) + szac. czas dojścia pieszo."""
    if offer.lat is None or offer.lon is None:
        return None
    stations = loc_cfg.get("stations", [])
    res = geo.nearest_station(offer.lat, offer.lon, stations)
    if not res:
        return None
    station, dist = res
    w = loc_cfg["walk"]
    return station["name"], geo.walk_minutes(dist, w["straight_factor"], w["speed_m_per_min"])


def cmd_test_alert(config: dict[str, Any]) -> None:
    """Wyślij testową wiadomość na #alerty — weryfikacja webhooka bez czekania na raport."""
    sources = [n for n, c in config["sources"].items() if c.get("enabled")]
    embed = notify.build_digest_embed({
        "date": "TEST — sprawdzenie webhooka",
        "sources": {n: {"fetched": 0, "sent_main": 0, "sent_near": 0, "dropped": 0}
                    for n in sources},
        "errors": ["to jest wiadomość testowa, nie błąd"],
    })
    notify.send_monitoring(embed)
    print(f"Wysłano testową wiadomość na #alerty ({len(sources)} źródeł na liście).")


def cmd_once(config: dict[str, Any]) -> None:
    notify_cfg = config.get("notify", {})
    photo_size = notify_cfg.get("photo_size", "640x480")
    owner_tmpl = notify_cfg.get("owner_message_template")
    state_cfg = config.get("state", {})
    state_path = Path(__file__).parent / state_cfg.get("path", "state/seen.json")
    max_age_days = state_cfg.get("max_age_days", 60)
    dedup_cfg = config.get("dedup", {})
    threshold = dedup_cfg.get("price_drop_threshold", 100)
    cross = dedup_cfg.get("cross_portal", {})
    loc_cfg = config["location"]
    sale_cfg = config.get("sale", {})
    buy_tmpl = notify_cfg.get("buy_message_template")

    st = state.load_state(state_path)
    now = datetime.now(timezone.utc)
    pruned = state.prune(st, max_age_days, now)
    if pruned:
        print(f"stan: usunięto {pruned} wpisów starszych niż {max_age_days} dni")

    def evaluate_fn(offer):
        text = filters.offer_text(offer)
        cost = cost_mod.compute_cost(offer, text, config)
        v = filters.classify(offer, text, cost, config, now)
        if v.kind == "reject":
            print(f"  [odrzut] {offer.source_id} — {v.reason}")
        return pipeline.Decision(v.kind, v.reason, cost)

    def send_fn(offer, cost, channel, reason, price_drop):
        if channel == "rejected":
            if not os.environ.get("DISCORD_WEBHOOK_REJECTED"):
                print(f"  [#odrzucone pominięte — brak DISCORD_WEBHOOK_REJECTED] "
                      f"{offer.source_id} — {reason}")
                return
            notify.send_offer(offer, cost, channel="rejected", reason=reason,
                              price_drop=price_drop, webhook_env="DISCORD_WEBHOOK_REJECTED")
            print(f"  -> [#odrzucone] {offer.source_id} — {reason}")
        else:
            notify.send_offer(offer, cost, channel="main",
                              station_info=_station_info(offer, loc_cfg),
                              photo_size=photo_size, price_drop=price_drop,
                              owner_message_template=owner_tmpl)
            tag = "OBNIŻKA " if price_drop else ""
            total = f"{cost.total} zł" if cost.total is not None else "koszt ?"
            print(f"  -> [#mieszkania {tag}] {offer.source_id} ({total}) {offer.title[:45]}")

    # --- Tryb SPRZEDAŻ ---
    def evaluate_fn_sale(offer):
        text = filters.offer_text(offer)
        v = filters.classify_sale(offer, text, config, now)
        if v.kind == "reject":
            print(f"  [odrzut] {offer.source_id} — {v.reason}")
        return pipeline.Decision(v.kind, v.reason, None)

    def send_fn_sale(offer, cost, channel, reason, price_drop):
        ppm = sale.price_per_m2(offer.price, offer.area_m2)
        deal = sale.is_deal(offer.price, offer.area_m2, sale_cfg.get("deal_price_per_m2", 0))
        if channel == "rejected":
            if not os.environ.get("DISCORD_WEBHOOK_SALE_REJECTED"):
                print(f"  [#sprzedaz-odrzucone pominięte — brak webhooka] {offer.source_id} — {reason}")
                return
            notify.send_sale_offer(offer, ppm, deal, channel="rejected", reason=reason,
                                   webhook_env="DISCORD_WEBHOOK_SALE_REJECTED")
            print(f"  -> [#sprzedaz-odrzucone] {offer.source_id} — {reason}")
        else:
            if not os.environ.get("DISCORD_WEBHOOK_SALE"):
                print(f"  [#sprzedaz pominięte — brak DISCORD_WEBHOOK_SALE] {offer.source_id} "
                      f"({offer.price} zł)")
                return
            notify.send_sale_offer(offer, ppm, deal, channel="main",
                                   station_info=_station_info(offer, loc_cfg), photo_size=photo_size,
                                   buy_message_template=buy_tmpl, webhook_env="DISCORD_WEBHOOK_SALE")
            badge = "🔥OKAZJA " if deal else ""
            print(f"  -> [#sprzedaz {badge}] {offer.source_id} ({offer.price} zł, {ppm} zł/m²) "
                  f"{offer.title[:40]}")

    # --- Monitoring: luka między przebiegami (martwy cron) ---
    mon = config.get("monitoring", {})
    problems: list[str] = []
    gap = health.note_run(st, now, mon.get("cron_gap_alert_hours", 2))
    if gap:
        problems.append(gap)
        print(f"[monitoring] {gap}")
    now_local = now.astimezone(_WARSAW)
    day_local = now_local.date().isoformat()

    # Izolacja per-źródło (Etap 6): błąd jednego portalu nie wywraca pozostałych.
    for name, src_cfg in config["sources"].items():
        if not src_cfg.get("enabled"):
            continue
        mode = src_cfg.get("mode", "rent")
        ev, snd = (evaluate_fn_sale, send_fn_sale) if mode == "sale" else (evaluate_fn, send_fn)
        cold = state.get_high_water(st, name) is None
        try:
            source = build_source(name, config)
            offers = source.fetch()  # rzuca wyjątek przy błędzie (nigdy ciche [])
            summary = pipeline.process_source(
                name, offers, st, threshold, now, evaluate_fn=ev, send_fn=snd,
                cross_price_tol=cross.get("price_tol"), cross_area_tol=cross.get("area_tol"),
            )
        except SourceError as e:
            print(f"{name}: BŁĄD ŹRÓDŁA — {e} (pomijam, pozostałe portale lecą dalej)")
            alert = health.record_source(st, name, 0, str(e)[:200],
                                         mon.get("bad_runs_threshold", 3),
                                         mon.get("realert_every", 20))
            if alert:
                problems.append(alert)
            health.accumulate_digest(st, day_local, name, {}, str(e)[:120])
            continue

        alert = health.record_source(st, name, summary["fetched"], None,
                                     mon.get("bad_runs_threshold", 3),
                                     mon.get("realert_every", 20))
        if alert:
            problems.append(alert)
        health.accumulate_digest(st, day_local, name, summary, None)

        if cold:
            print(f"{name}: cold start — zasiano {summary['seeded']} ofert, nic nie wysłano")
        else:
            main_ch, near_ch = ("#sprzedaz", "#sprzedaz-odrzucone") if mode == "sale" \
                else ("#mieszkania", "#odrzucone")
            print(
                f"{name} [{mode}]: pobrano {summary['fetched']} | {main_ch} {summary['sent_main']} | "
                f"{near_ch} {summary['sent_near']} | odrzucone {summary['dropped']} | "
                f"dubel-portal {summary['cross_dup']} | backfill {summary['backfilled']} | "
                f"pominięte {summary['skipped']}"
            )

    # --- Monitoring: wyślij alerty i (raz dziennie) raport na #alerty ---
    digest = health.due_digest(st, now_local, mon.get("digest_hour", 8))
    if problems or digest:
        if not os.environ.get("DISCORD_WEBHOOK_ALERTS"):
            print("[monitoring] brak DISCORD_WEBHOOK_ALERTS — pomijam wysyłkę na #alerty")
        else:
            try:
                if problems:
                    notify.send_monitoring(notify.build_alert_embed(problems))
                    print(f"[monitoring] wysłano alert ({len(problems)} problemów)")
                if digest:
                    notify.send_monitoring(notify.build_digest_embed(digest))
                    print(f"[monitoring] wysłano raport dzienny za {digest['date']}")
            except notify.NotifyError as e:
                # Monitoring nie może wywrócić przebiegu ani zablokować zapisu stanu.
                print(f"[monitoring] nie udało się wysłać: {e}")

    state.save_state(state_path, st)
    print(f"stan zapisany: {state_path.relative_to(Path(__file__).parent)}")


def main() -> None:
    _force_utf8_stdout()
    load_dotenv()
    parser = argparse.ArgumentParser(description="Bot wyszukujący mieszkania w Trójmieście")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true", help="jeden przebieg skanu")
    group.add_argument("--debug-raw", metavar="PORTAL", help="pokaż surową odpowiedź portalu")
    group.add_argument("--test-alert", action="store_true",
                       help="wyślij testową wiadomość na #alerty (sprawdzenie webhooka)")
    args = parser.parse_args()

    config = load_config()

    if args.debug_raw:
        cmd_debug_raw(args.debug_raw, config)
    elif args.test_alert:
        cmd_test_alert(config)
    elif args.once:
        cmd_once(config)


if __name__ == "__main__":
    main()
