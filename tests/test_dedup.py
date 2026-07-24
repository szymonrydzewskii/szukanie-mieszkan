from datetime import datetime, timezone

from core import dedup, state
from sources.base import Offer


def make_offer(**kw):
    base = dict(
        source="olx",
        source_id="123",
        url="https://olx.pl/d/x",
        title="Mieszkanie",
        price=2500,
        area_m2=45.0,
        rooms=2,
        district="Wrzeszcz",
    )
    base.update(kw)
    return Offer(**base)


def seen_state(offer, cena):
    st = {"version": 1, "seen": {}}
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)
    state.record(st, dedup.key_for(offer), fingerprint=dedup.fingerprint(offer),
                 cena=cena, sent_at=now)
    return st


def test_key_for_builds_source_and_id():
    assert dedup.key_for(make_offer(source="olx", source_id="999")) == "olx:999"


def test_fingerprint_is_deterministic():
    assert dedup.fingerprint(make_offer()) == dedup.fingerprint(make_offer())


def test_fingerprint_differs_on_district():
    a = dedup.fingerprint(make_offer(district="Wrzeszcz"))
    b = dedup.fingerprint(make_offer(district="Oliwa"))
    assert a != b


def test_classify_new_when_not_seen():
    result = dedup.classify(make_offer(), {"version": 1, "seen": {}}, price_drop_threshold=100)
    assert result.status is dedup.DedupStatus.NEW


def test_classify_duplicate_when_seen_same_price():
    offer = make_offer(price=2500)
    st = seen_state(offer, cena=2500)
    result = dedup.classify(offer, st, price_drop_threshold=100)
    assert result.status is dedup.DedupStatus.DUPLICATE


def test_classify_price_drop_when_drop_exceeds_threshold():
    offer = make_offer(price=2350)
    st = seen_state(offer, cena=2500)  # spadek o 150 > 100
    result = dedup.classify(offer, st, price_drop_threshold=100)
    assert result.status is dedup.DedupStatus.PRICE_DROP
    assert result.old_price == 2500
    assert result.new_price == 2350


def test_classify_duplicate_when_drop_equals_threshold():
    offer = make_offer(price=2400)
    st = seen_state(offer, cena=2500)  # spadek dokładnie 100, nie > 100
    result = dedup.classify(offer, st, price_drop_threshold=100)
    assert result.status is dedup.DedupStatus.DUPLICATE


def test_classify_duplicate_when_price_increased():
    offer = make_offer(price=2700)
    st = seen_state(offer, cena=2500)
    result = dedup.classify(offer, st, price_drop_threshold=100)
    assert result.status is dedup.DedupStatus.DUPLICATE


def test_classify_duplicate_when_current_price_missing():
    offer = make_offer(price=None)
    st = seen_state(offer, cena=2500)
    result = dedup.classify(offer, st, price_drop_threshold=100)
    assert result.status is dedup.DedupStatus.DUPLICATE


def test_classify_duplicate_when_stored_price_missing():
    offer = make_offer(price=2300)
    st = seen_state(offer, cena=None)
    result = dedup.classify(offer, st, price_drop_threshold=100)
    assert result.status is dedup.DedupStatus.DUPLICATE
