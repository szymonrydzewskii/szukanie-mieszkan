from datetime import datetime, timezone

from core import filters
from core.cost import CostBreakdown
from sources.base import Offer


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)

CONFIG = {
    "budget": {"hard_limit": 3500},
    "filters": {
        "min_area_m2": 35,
        "min_rooms": 2,
        "max_age_days": 7,
        "allowed_cities": ["Gdańsk", "Sopot", "Gdynia"],
        "studio_bedroom_keywords": ["oddzielna sypialnia", "osobna sypialnia"],
        "reject_phrases": ["nie wynajmę studentom", "tylko dla pracujących"],
        "type_reject_keywords": ["współlokator", "wynajmę pokój"],
        "no_bathroom_keywords": ["łazienka wspólna", "bez łazienki"],
        "souterrain_keywords": ["suteren"],  # rdzeń: suterena/suterenie/suterenę
    },
}


def offer(**kw):
    base = dict(source="olx", source_id="1", url="u", title="Mieszkanie",
                price=2500, rent_admin=400, area_m2=45.0, rooms=2,
                builttype="blok", city="Gdańsk", district="Wrzeszcz",
                created_time="2026-07-23T10:00:00+00:00")
    base.update(kw)
    return Offer(**base)


def make_cost(total=3250, heating=None):
    return CostBreakdown(najem=2500, czynsz=400, czynsz_estimated=False,
                         media=350, media_estimated=True, heating=heating,
                         total=total, notes=[])


def evaluate(o, text="", cost=None):
    return filters.evaluate(o, text, cost or make_cost(), CONFIG, NOW)


def test_clean_offer_passes():
    assert evaluate(offer()).passed is True


def test_area_below_minimum_rejected():
    r = evaluate(offer(area_m2=30.0))
    assert r.passed is False and "powierzchnia" in r.reason.lower()


def test_area_exactly_minimum_passes():
    assert evaluate(offer(area_m2=35.0)).passed is True


def test_rooms_below_minimum_rejected():
    assert evaluate(offer(rooms=1)).passed is False


def test_studio_with_separate_bedroom_keyword_passes():
    r = evaluate(offer(rooms=1), text="kawalerka z oddzielna sypialnia w głębi")
    assert r.passed is True


def test_city_outside_trojmiasto_rejected():
    r = evaluate(offer(city="Kraków"))
    assert r.passed is False and "lokalizacja" in r.reason.lower()


def test_anti_student_phrase_rejected():
    r = evaluate(offer(), text="mieszkanie nie wynajmę studentom, tylko rodzina")
    assert r.passed is False


def test_type_reject_keyword_rejected():
    r = evaluate(offer(), text="szukam współlokator do pokoju")
    assert r.passed is False


def test_stove_heating_rejected():
    r = evaluate(offer(), cost=make_cost(heating="stove"))
    assert r.passed is False and "ogrzewan" in r.reason.lower()


def test_souterrain_rejected():
    assert evaluate(offer(), text="lokal w suterenie").passed is False


def test_no_bathroom_rejected():
    assert evaluate(offer(), text="łazienka wspólna na korytarzu").passed is False


def test_offer_older_than_7_days_rejected():
    r = evaluate(offer(created_time="2026-07-10T10:00:00+00:00"))
    assert r.passed is False and "starsze" in r.reason.lower()


def test_recent_offer_passes_age_check():
    assert evaluate(offer(created_time="2026-07-24T09:00:00+00:00")).passed is True


def test_total_cost_over_limit_rejected():
    r = evaluate(offer(), cost=make_cost(total=3600))
    assert r.passed is False and "koszt" in r.reason.lower()


def test_unknown_total_not_rejected_on_cost():
    # brak najmu -> total None -> nie odrzucamy z powodu kosztu (SPEC: nie odrzucaj za brak danych)
    assert evaluate(offer(price=None), cost=make_cost(total=None)).passed is True


def test_offer_text_strips_html_and_lowercases():
    o = offer(title="Ładne", description="Salon<br/>2 <b>pokoje</b>")
    text = filters.offer_text(o)
    assert "<" not in text
    assert "pokoje" in text and text == text.lower()
