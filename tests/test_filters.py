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
        "location_accept_tiers": ["best", "very_good", "good", "ok"],
        "near_miss_cost_max": 3900,
        "studio_bedroom_keywords": ["sypialni"],
        "reject_phrases": ["nie wynajmę studentom", "tylko dla pracujących"],
        "type_reject_keywords": ["współlokator", "wynajmę pokój"],
        "no_bathroom_keywords": ["łazienka wspólna", "bez łazienki"],
        "souterrain_keywords": ["suteren"],
    },
    "location": {
        "tier_districts": {
            "best": ["oliwa", "żabianka", "przymorze", "sopot", "jelitkowo"],
            "very_good": ["wrzeszcz", "zaspa", "strzyża", "brzeźno"],
            "good": ["brętowo", "morena", "piecki", "migowo"],
            "ok": ["suchanino", "aniołki", "śródmieście", "chełm"],
        },
    },
}


def offer(**kw):
    base = dict(source="olx", source_id="1", url="u", title="Mieszkanie",
                price=2500, rent_admin=400, area_m2=45.0, rooms=2,
                builttype="blok", city="Gdańsk", district="Oliwa",
                created_time="2026-07-23T10:00:00+00:00")
    base.update(kw)
    return Offer(**base)


def cost(total=3250, heating=None):
    return CostBreakdown(najem=2500, czynsz=400, czynsz_estimated=False,
                         media=350, media_estimated=True, heating=heating,
                         total=total, notes=[])


def classify(o, text="", c=None):
    return filters.classify(o, text, c or cost(), CONFIG, NOW)


# --- location_tier ---
def test_location_tier_matches_city_and_district():
    loc = CONFIG["location"]
    assert filters.location_tier("Gdańsk", "Oliwa", loc) == "best"
    assert filters.location_tier("Sopot", "Centrum", loc) == "best"       # po mieście
    assert filters.location_tier("Gdańsk", "Wrzeszcz", loc) == "very_good"
    assert filters.location_tier("Gdańsk", "Ujeścisko", loc) == "other"


# --- match ---
def test_clean_good_location_offer_matches():
    assert classify(offer()).kind == "match"


# --- twarde odrzuty ---
def test_area_below_min_rejected():
    assert classify(offer(area_m2=30)).kind == "reject"


def test_city_outside_trojmiasto_rejected():
    assert classify(offer(city="Kraków", district="Stare Miasto")).kind == "reject"


def test_far_district_rejected():
    r = classify(offer(district="Ujeścisko - Łostowice"))
    assert r.kind == "reject" and "lokaliz" in r.reason.lower()


def test_anti_student_rejected():
    assert classify(offer(), text="nie wynajmę studentom").kind == "reject"


def test_type_keyword_rejected():
    assert classify(offer(), text="szukam współlokator").kind == "reject"


def test_stove_heating_rejected():
    assert classify(offer(), c=cost(heating="stove")).kind == "reject"


def test_souterrain_rejected():
    assert classify(offer(), text="lokal w suterenie").kind == "reject"


def test_no_bathroom_rejected():
    assert classify(offer(), text="łazienka wspólna").kind == "reject"


def test_old_listing_rejected():
    assert classify(offer(created_time="2026-07-10T10:00:00+00:00")).kind == "reject"


def test_studio_without_bedroom_rejected():
    assert classify(offer(rooms=1), text="kawalerka open space").kind == "reject"


def test_cost_far_over_limit_rejected():
    assert classify(offer(), c=cost(total=4200)).kind == "reject"


# --- prawie-trafienia (#odrzucone) ---
def test_studio_with_bedroom_is_near_miss():
    r = classify(offer(rooms=1), text="kawalerka z oddzielna sypialnia")
    assert r.kind == "near_miss" and "sypialni" in r.reason.lower()


def test_cost_slightly_over_limit_is_near_miss():
    r = classify(offer(), c=cost(total=3650))
    assert r.kind == "near_miss" and "koszt" in r.reason.lower()


def test_unknown_cost_not_rejected():
    assert classify(offer(price=None), c=cost(total=None)).kind == "match"


# --- offer_text ---
def test_offer_text_strips_html_and_lowercases():
    o = offer(title="Ładne", description="Salon<br/>2 <b>pokoje</b>")
    text = filters.offer_text(o)
    assert "<" not in text and "pokoje" in text and text == text.lower()
