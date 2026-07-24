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


def seed(st, sid="0"):
    run([make_offer(sid, created="2026-07-24T10:00:00+00:00")], st, SendRec())


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


def test_watermark_advances():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    run([make_offer("1", created="2026-07-24T11:00:00+00:00")], st, SendRec())
    run([make_offer("2", created="2026-07-24T11:45:00+00:00")], st, SendRec())
    assert state.get_high_water(st, "olx") == "2026-07-24T11:45:00+00:00"
