from datetime import datetime, timezone

from core import sale, filters
from sources.base import Offer


NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)

CONFIG = {
    "sale": {"budget_match": 600000, "budget_near_miss": 650000, "deal_price_per_m2": 13000},
    "filters": {
        "min_area_m2": 35, "min_rooms": 2,
        "allowed_cities": ["Gdańsk", "Sopot", "Gdynia"],
        "location_accept_tiers": ["best", "very_good", "good", "ok"],
        "type_reject_keywords": ["lokal usługowy", "garaż"],
        "no_bathroom_keywords": ["bez łazienki"],
        "souterrain_keywords": ["suteren"],
    },
    "location": {"tier_districts": {
        "best": ["oliwa", "sopot", "przymorze"], "very_good": ["wrzeszcz"],
        "good": ["morena"], "ok": ["chełm"],
    }},
}


def offer(**kw):
    base = dict(source="olx_sale", source_id="1", url="u", title="Mieszkanie",
                price=550000, area_m2=50.0, rooms=2, city="Gdańsk", district="Oliwa",
                market="secondary", created_time="2026-07-24T10:00:00+00:00")
    base.update(kw)
    return Offer(**base)


# --- sale.py ---
def test_price_per_m2():
    assert sale.price_per_m2(600000, 50) == 12000
    assert sale.price_per_m2(None, 50) is None
    assert sale.price_per_m2(600000, None) is None


def test_is_deal():
    assert sale.is_deal(600000, 50, 13000) is True   # 12000 <= 13000
    assert sale.is_deal(700000, 50, 13000) is False  # 14000 > 13000


# --- classify_sale ---
def clf(o, text=""):
    return filters.classify_sale(o, text, CONFIG, NOW)


def test_within_budget_good_location_matches():
    assert clf(offer(price=550000)).kind == "match"


def test_price_between_budgets_is_near_miss():
    r = clf(offer(price=630000))
    assert r.kind == "near_miss" and "budżet" in r.reason.lower()


def test_price_over_near_miss_rejected():
    assert clf(offer(price=700000)).kind == "reject"


def test_primary_market_rejected():
    assert clf(offer(market="primary")).kind == "reject"


def test_far_district_rejected():
    assert clf(offer(district="Ujeścisko")).kind == "reject"


def test_too_small_rejected():
    assert clf(offer(area_m2=30)).kind == "reject"


def test_too_few_rooms_rejected():
    assert clf(offer(rooms=1)).kind == "reject"


def test_type_keyword_rejected():
    assert clf(offer(), text="lokal usługowy na sprzedaż").kind == "reject"
