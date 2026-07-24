from datetime import datetime, timezone

from core import pipeline, state
from core.cost import CostBreakdown
from core.scoring import Score
from sources.base import Offer


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
TODAY = "2026-07-24"
ROUTING = {"thresholds": {"top": 88, "main": 78, "rejected": 60},
           "limits": {"daily_main": 8, "daily_78_87": 6}}


def make_offer(source_id="1", price=2500, created="2026-07-24T11:00:00+00:00", **kw):
    base = dict(source="olx", source_id=source_id, url=f"https://olx.pl/{source_id}",
                title="Mieszkanie", price=price, area_m2=45.0, rooms=2, district="Oliwa",
                created_time=created)
    base.update(kw)
    return Offer(**base)


def _cost():
    return CostBreakdown(najem=2500, czynsz=400, czynsz_estimated=False, media=350,
                         media_estimated=True, heating=None, total=3250, notes=[])


def passing_filter(o):
    return pipeline.Evaluation(True, None, _cost())


def rejecting_filter(o):
    return pipeline.Evaluation(False, "odrzut testowy", _cost())


def score_const(total):
    def f(o, cost):
        return Score(total=total, breakdown={"Cena": total})
    return f


class SendRec:
    def __init__(self):
        self.calls = []

    def __call__(self, offer, score, cost, channel, reason, price_drop):
        self.calls.append((offer.source_id, channel, score.total, price_drop))


def run(offers, st, send, filter_fn=passing_filter, total=90):
    return pipeline.process_source("olx", offers, st, price_drop_threshold=100, now=NOW,
                                   filter_fn=filter_fn, score_fn=score_const(total),
                                   send_fn=send, routing_cfg=ROUTING)


def seed(st, source_id="0", created="2026-07-24T10:00:00+00:00"):
    run([make_offer(source_id, created=created)], st, SendRec())


def test_cold_start_seeds_and_sends_nothing():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    send = SendRec()
    summary = run([make_offer("1"), make_offer("2")], st, send)
    assert send.calls == []
    assert summary["seeded"] == 2


def test_high_score_new_offer_goes_to_main_and_counts():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    seed(st)
    send = SendRec()
    summary = run([make_offer("2", created="2026-07-24T11:30:00+00:00")], st, send, total=90)
    assert send.calls == [("2", "main", 90, None)]
    assert summary["sent_main"] == 1
    assert state.get_daily(st, TODAY, "main") == 1


def test_mid_score_60_to_77_goes_to_rejected():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    seed(st)
    send = SendRec()
    summary = run([make_offer("2", created="2026-07-24T11:30:00+00:00")], st, send, total=70)
    assert send.calls[0][1] == "rejected"
    assert summary["sent_rejected"] == 1


def test_low_score_below_60_not_sent_but_recorded():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    seed(st)
    send = SendRec()
    summary = run([make_offer("2", created="2026-07-24T11:30:00+00:00")], st, send, total=50)
    assert send.calls == []
    assert summary["below"] == 1
    assert state.is_seen(st, "olx:2")


def test_failing_filter_not_scored_or_sent():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    seed(st)
    send = SendRec()
    summary = run([make_offer("2", created="2026-07-24T11:30:00+00:00")], st, send,
                  filter_fn=rejecting_filter)
    assert send.calls == []
    assert summary["filtered"] == 1


def test_daily_main_limit_pushes_mid_band_to_rejected():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {TODAY: {"main": 8}}}
    seed(st)
    send = SendRec()
    run([make_offer("2", created="2026-07-24T11:30:00+00:00")], st, send, total=80)
    assert send.calls[0][1] == "rejected"  # 78-87 przy wyczerpanym limicie -> odrzucone


def test_price_drop_high_score_sent_to_main_with_annotation():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    run([make_offer("1", price=2500)], st, SendRec())  # cold seed
    send = SendRec()
    run([make_offer("1", price=2300)], st, send, total=90)
    assert send.calls == [("1", "main", 90, (2500, 2300))]


def test_duplicate_not_resent():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    run([make_offer("1")], st, SendRec())
    send = SendRec()
    run([make_offer("1")], st, send)
    assert send.calls == []


def test_old_rotating_offer_backfilled_not_sent():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    seed(st, created="2026-07-24T11:00:00+00:00")
    send = SendRec()
    summary = run([make_offer("9", created="2026-05-01T10:00:00+00:00")], st, send)
    assert send.calls == []
    assert summary["backfilled"] == 1
