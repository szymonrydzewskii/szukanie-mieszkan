from datetime import datetime, timezone

from core import pipeline, state
from sources.base import Offer


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def make_offer(source_id="1", price=2500, created="2026-07-24T11:00:00+00:00", **kw):
    base = dict(
        source="olx", source_id=source_id, url=f"https://olx.pl/{source_id}",
        title="Mieszkanie", price=price, area_m2=45.0, rooms=2, district="Wrzeszcz",
        created_time=created,
    )
    base.update(kw)
    return Offer(**base)


def passing_filter(offer):
    return pipeline.Evaluation(passed=True, reason=None, cost=None)


def rejecting_filter(offer):
    return pipeline.Evaluation(passed=False, reason="odrzut testowy", cost=None)


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, offer, price_drop, cost):
        self.calls.append((offer.source_id, price_drop))


def run(offers, st, send, filter_fn=passing_filter):
    return pipeline.process_source("olx", offers, st, price_drop_threshold=100,
                                   now=NOW, send_fn=send, filter_fn=filter_fn)


def test_cold_start_seeds_all_sends_nothing_and_sets_watermark():
    st = {"version": 1, "seen": {}}
    send = Recorder()
    offers = [
        make_offer("1", created="2026-07-24T10:00:00+00:00"),
        make_offer("2", created="2026-07-24T11:00:00+00:00"),
    ]
    summary = run(offers, st, send)
    assert send.calls == []
    assert summary["seeded"] == 2
    assert state.get_high_water(st, "olx") == "2026-07-24T11:00:00+00:00"


def test_offer_created_after_watermark_and_passing_filter_is_sent():
    st = {"version": 1, "seen": {}}
    run([make_offer("1", created="2026-07-24T11:00:00+00:00")], st, Recorder())
    send = Recorder()
    summary = run([make_offer("2", created="2026-07-24T11:30:00+00:00")], st, send)
    assert send.calls == [("2", None)]
    assert summary["sent_new"] == 1


def test_new_offer_failing_filter_is_recorded_but_not_sent():
    st = {"version": 1, "seen": {}}
    run([make_offer("1", created="2026-07-24T11:00:00+00:00")], st, Recorder())
    send = Recorder()
    summary = run([make_offer("2", created="2026-07-24T11:30:00+00:00")], st, send,
                  filter_fn=rejecting_filter)
    assert send.calls == []
    assert summary["filtered"] == 1
    assert state.is_seen(st, "olx:2")  # zapamiętane, nie rozważymy ponownie


def test_unseen_but_old_offer_is_backfilled_not_sent():
    st = {"version": 1, "seen": {}}
    run([make_offer("1", created="2026-07-24T11:00:00+00:00")], st, Recorder())
    send = Recorder()
    old = make_offer("999", created="2026-05-20T12:00:00+00:00")
    summary = run([old], st, send)
    assert send.calls == []
    assert summary["backfilled"] == 1
    assert state.is_seen(st, "olx:999")


def test_duplicate_is_not_resent():
    st = {"version": 1, "seen": {}}
    run([make_offer("1")], st, Recorder())
    send = Recorder()
    run([make_offer("1")], st, send)
    assert send.calls == []


def test_price_drop_passing_filter_is_resent_and_updates_state():
    st = {"version": 1, "seen": {}}
    run([make_offer("1", price=2500)], st, Recorder())
    send = Recorder()
    summary = run([make_offer("1", price=2300)], st, send)
    assert send.calls == [("1", (2500, 2300))]
    assert summary["sent_drop"] == 1
    assert state.get_entry(st, "olx:1")["cena"] == 2300


def test_price_drop_failing_filter_not_sent_but_price_updated():
    st = {"version": 1, "seen": {}}
    run([make_offer("1", price=2500)], st, Recorder())
    send = Recorder()
    summary = run([make_offer("1", price=2300)], st, send, filter_fn=rejecting_filter)
    assert send.calls == []
    assert summary["filtered"] == 1
    assert state.get_entry(st, "olx:1")["cena"] == 2300


def test_watermark_advances_after_newer_offer():
    st = {"version": 1, "seen": {}}
    run([make_offer("1", created="2026-07-24T11:00:00+00:00")], st, Recorder())
    run([make_offer("2", created="2026-07-24T11:45:00+00:00")], st, Recorder())
    assert state.get_high_water(st, "olx") == "2026-07-24T11:45:00+00:00"
