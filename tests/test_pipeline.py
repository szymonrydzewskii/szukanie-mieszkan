from datetime import datetime, timezone

from core import pipeline, state
from core.cost import CostBreakdown
from sources.base import Offer


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def make_offer(source_id="1", price=2500, created="2026-07-24T11:00:00+00:00", **kw):
    base = dict(source="olx", source_id=source_id, url=f"https://olx.pl/{source_id}",
                title="Mieszkanie", price=price, area_m2=45.0, rooms=2, district="Oliwa",
                created_time=created)
    base.update(kw)
    return Offer(**base)


def _cost():
    return CostBreakdown(najem=2500, czynsz=400, czynsz_estimated=False, media=350,
                         media_estimated=True, heating=None, total=3250, notes=[])


def evaluate(kind, reason=None):
    def f(o):
        return pipeline.Decision(kind, reason, _cost())
    return f


class SendRec:
    def __init__(self):
        self.calls = []

    def __call__(self, offer, cost, channel, reason, price_drop):
        self.calls.append((offer.source_id, channel, price_drop))


def run(offers, st, send, evaluate_fn=None):
    return pipeline.process_source("olx", offers, st, price_drop_threshold=100, now=NOW,
                                   evaluate_fn=evaluate_fn or evaluate("match"), send_fn=send)


def seed(st, sid="0", created="2026-07-24T10:00:00+00:00"):
    run([make_offer(sid, created=created)], st, SendRec())


def test_cold_start_seeds_and_sends_nothing():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    send = SendRec()
    summary = run([make_offer("1"), make_offer("2")], st, send)
    assert send.calls == [] and summary["seeded"] == 2


def test_match_goes_to_main():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    seed(st)
    send = SendRec()
    summary = run([make_offer("2", created="2026-07-24T11:30:00+00:00")], st, send)
    assert send.calls == [("2", "main", None)]
    assert summary["sent_main"] == 1


def test_near_miss_goes_to_rejected():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    seed(st)
    send = SendRec()
    summary = run([make_offer("2", created="2026-07-24T11:30:00+00:00")], st, send,
                  evaluate_fn=evaluate("near_miss", "koszt ponad limit"))
    assert send.calls == [("2", "rejected", None)]
    assert summary["sent_near"] == 1


def test_reject_not_sent_but_recorded():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    seed(st)
    send = SendRec()
    summary = run([make_offer("2", created="2026-07-24T11:30:00+00:00")], st, send,
                  evaluate_fn=evaluate("reject", "za drogo"))
    assert send.calls == []
    assert summary["dropped"] == 1
    assert state.is_seen(st, "olx:2")


def test_price_drop_match_sent_with_annotation():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    run([make_offer("1", price=2500)], st, SendRec())
    send = SendRec()
    run([make_offer("1", price=2300)], st, send)
    assert send.calls == [("1", "main", (2500, 2300))]


def test_duplicate_not_resent():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    run([make_offer("1")], st, SendRec())
    send = SendRec()
    run([make_offer("1")], st, send)
    assert send.calls == []


def test_old_rotating_offer_backfilled():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    seed(st)
    send = SendRec()
    summary = run([make_offer("9", created="2026-05-01T10:00:00+00:00")], st, send)
    assert send.calls == [] and summary["backfilled"] == 1


def test_late_indexed_offer_older_than_watermark_is_still_sent():
    """Regresja: oferta z prawdziwą datą utworzenia, zindeksowana z opóźnieniem.

    Powstała 2 h temu, ale trafiła do feedu, gdy znacznik stał już wyżej.
    Wcześniej ginęła (backfill) — teraz decyduje okno świeżości.
    """
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    seed(st, created="2026-07-24T11:00:00+00:00")
    # znacznik przesunięty do przodu przez szybciej zindeksowaną ofertę
    run([make_offer("2", created="2026-07-24T11:50:00+00:00")], st, SendRec())
    send = SendRec()
    late = make_offer("3", created="2026-07-24T11:20:00+00:00")   # starsza niż znacznik, ale świeża
    summary = run([late], st, send)
    assert send.calls == [("3", "main", None)]
    assert summary["sent_main"] == 1


def test_offer_outside_freshness_window_is_backfilled():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    seed(st)
    send = SendRec()
    old = make_offer("9", created="2026-05-01T10:00:00+00:00")   # sprzed miesięcy
    summary = run([old], st, send)
    assert send.calls == [] and summary["backfilled"] == 1


def test_novelty_key_beats_bumped_date():
    # Trojmiasto: nowość po ID (novelty_key), nie po dacie (bump).
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    run([make_offer("1", novelty_key="000000000100", created="2026-07-24T10:00:00+00:00")],
        st, SendRec())  # cold seed -> hwm = "000000000100"
    send = SendRec()
    # bumpnięta stara oferta: ŚWIEŻA data, ale NISKIE id -> nie wysyłać
    bumped = make_offer("2", novelty_key="000000000050", created="2026-07-24T11:59:00+00:00")
    summary = run([bumped], st, send)
    assert send.calls == [] and summary["backfilled"] == 1
    # genuinie nowa: WYŻSZE id -> wysłać, nawet ze starszą datą
    send2 = SendRec()
    fresh = make_offer("3", novelty_key="000000000200", created="2020-01-01T00:00:00+00:00")
    run([fresh], st, send2)
    assert send2.calls == [("3", "main", None)]


def _troj(sid, nk, **kw):
    base = dict(source="trojmiasto", source_id=sid, url="u", title="Mieszkanie",
                price=2550, area_m2=46.0, rooms=2, district="Wrzeszcz Dolny", novelty_key=nk)
    base.update(kw)
    return Offer(**base)


def test_cross_portal_duplicate_suppressed():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    # OLX ma już ten lokal: 2500/45/2/Wrzeszcz
    olx = make_offer("111", price=2500, area_m2=45.0, rooms=2, district="Wrzeszcz")
    pipeline.process_source("olx", [olx], st, 100, NOW,
                            evaluate_fn=evaluate("match"), send_fn=SendRec())
    # Trojmiasto cold-start (ustawia hwm)
    pipeline.process_source("trojmiasto", [_troj("1", "000000000001", price=1, area_m2=1,
                            rooms=1, district="x")], st, 100, NOW,
                            evaluate_fn=evaluate("match"), send_fn=SendRec(),
                            cross_price_tol=100, cross_area_tol=2)
    # Ta sama oferta z Trojmiasto (±tol, dzielnica zgodna) -> stłumiona
    send = SendRec()
    summary = pipeline.process_source("trojmiasto", [_troj("999", "000000000999")], st, 100, NOW,
                                      evaluate_fn=evaluate("match"), send_fn=send,
                                      cross_price_tol=100, cross_area_tol=2)
    assert send.calls == []
    assert summary["cross_dup"] == 1


def test_watermark_advances():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    run([make_offer("1", created="2026-07-24T11:00:00+00:00")], st, SendRec())
    run([make_offer("2", created="2026-07-24T11:45:00+00:00")], st, SendRec())
    assert state.get_high_water(st, "olx") == "2026-07-24T11:45:00+00:00"
