from datetime import datetime, timezone

from core import scoring
from core.cost import CostBreakdown
from sources.base import Offer


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)

CONF = {
    "scoring": {
        "price": [[2800, 30], [3000, 25], [3300, 18], [3500, 10]],
        "location": {
            "tier_points": {"best": 25, "very_good": 18, "good": 10, "ok": 10, "other": 3},
            "tier_districts": {
                "best": ["oliwa", "żabianka", "przymorze", "sopot", "jelitkowo"],
                "very_good": ["wrzeszcz", "zaspa", "strzyża", "brzeźno"],
                "good": ["brętowo", "morena", "piecki", "migowo"],
                "ok": ["suchanino", "aniołki", "śródmieście", "chełm"],
            },
        },
        "layout": {
            "full_pts": 20, "alcove_pts": 14, "walkthrough_pts": 8,
            "ideal_area": [40, 50],
            "bedroom_keywords": ["sypialni"],
            "alcove_keywords": ["aneks"],
            "walkthrough_keywords": ["przechodni"],
        },
        "standard": {
            "default": 10,
            "renovated_pts": 15, "renovated_keywords": ["po remoncie", "wysoki standard"],
            "good_pts": 10, "good_keywords": ["zadbane"],
            "average_pts": 5, "average_keywords": ["przeciętn"],
            "neglected_pts": 0, "neglected_keywords": ["do remontu"],
        },
        "equipment": {
            "per_item": 2,
            "items": {
                "pralka": ["pralka"], "lodówka": ["lodówka"], "piekarnik": ["piekarnik"],
                "biurko": ["biurko"], "internet": ["internet w cenie"],
            },
        },
        "penalties": {
            "commission_full": -10, "commission_partial": -5,
            "electric_heating": -8, "rent_unknown": -5, "listing_4_7_days": -5,
            "commission_full_keywords": ["prowizja 100", "100% czynszu"],
            "commission_any_keywords": ["prowizja", "pośrednik"],
            "no_commission_keywords": ["bez prowizji"],
        },
    },
}


def offer(**kw):
    base = dict(source="olx", source_id="1", url="u", title="Mieszkanie",
                price=2500, rent_admin=400, area_m2=45.0, rooms=2,
                builttype="blok", city="Gdańsk", district="Oliwa",
                created_time="2026-07-23T10:00:00+00:00", has_phone=True)
    base.update(kw)
    return Offer(**base)


def cost(total=3250, heating=None, czynsz_estimated=False):
    return CostBreakdown(najem=2500, czynsz=400, czynsz_estimated=czynsz_estimated,
                         media=350, media_estimated=True, heating=heating,
                         total=total, notes=[])


# --- Cena /30 ---
def test_price_bands():
    p = CONF["scoring"]["price"]
    assert scoring.score_price(2700, p) == 30
    assert scoring.score_price(2900, p) == 25
    assert scoring.score_price(3200, p) == 18
    assert scoring.score_price(3500, p) == 10
    assert scoring.score_price(None, p) == 0


# --- Lokalizacja /25 (tabela dzielnic) ---
def test_location_tiers():
    loc = CONF["scoring"]["location"]
    assert scoring.score_location("Gdańsk", "Oliwa", loc)[0] == 25
    assert scoring.score_location("Gdańsk", "Wrzeszcz", loc)[0] == 18
    assert scoring.score_location("Gdańsk", "Morena", loc)[0] == 10
    assert scoring.score_location("Gdańsk", "Ktoś-tam-daleko", loc)[0] == 3


def test_location_matches_city_not_only_district():
    # Sopot ma district="Centrum" — musi trafić w tier 'best' po nazwie miasta
    loc = CONF["scoring"]["location"]
    assert scoring.score_location("Sopot", "Centrum", loc)[0] == 25


# --- Układ /20 ---
def test_layout_full_two_rooms_bedroom_ideal_area():
    lay = CONF["scoring"]["layout"]
    assert scoring.score_layout(offer(rooms=2, area_m2=45), "osobna sypialnia", lay) == 20


def test_layout_alcove_plus_bedroom():
    lay = CONF["scoring"]["layout"]
    # 2 pokoje ale metraż poza ideałem -> 14
    assert scoring.score_layout(offer(rooms=2, area_m2=60), "sypialnia i salon", lay) == 14


def test_layout_walkthrough():
    lay = CONF["scoring"]["layout"]
    assert scoring.score_layout(offer(rooms=2, area_m2=38), "pokój przechodni", lay) == 8


# --- Standard /15 ---
def test_standard_bands():
    std = CONF["scoring"]["standard"]
    assert scoring.score_standard("mieszkanie po remoncie", std) == 15
    assert scoring.score_standard("zadbane wnętrze", std) == 10
    assert scoring.score_standard("do remontu", std) == 0
    assert scoring.score_standard("nic o standardzie", std) == 10  # default


# --- Wyposażenie /10 ---
def test_equipment_counts_items_capped():
    eq = CONF["scoring"]["equipment"]
    assert scoring.score_equipment("pralka i lodówka", eq)[0] == 4
    full = "pralka lodówka piekarnik biurko internet w cenie"
    assert scoring.score_equipment(full, eq)[0] == 10


# --- Kary ---
def test_penalty_electric_and_rent_unknown():
    pens = scoring.compute_penalties(offer(), cost(heating="electric", czynsz_estimated=True),
                                     "opis", NOW, CONF["scoring"]["penalties"])
    deltas = dict(pens)
    assert deltas.get("ogrzewanie elektryczne") == -8
    assert any(d == -5 for _, d in pens)  # brak danych o czynszu


def test_penalty_full_commission():
    pens = scoring.compute_penalties(offer(), cost(), "prowizja 100% czynszu", NOW,
                                     CONF["scoring"]["penalties"])
    assert any(d == -10 for _, d in pens)


def test_no_commission_no_penalty():
    pens = scoring.compute_penalties(offer(), cost(), "bez prowizji, bezpośrednio", NOW,
                                     CONF["scoring"]["penalties"])
    assert all("prowizj" not in label.lower() for label, _ in pens)


def test_penalty_listing_age_4_to_7_days():
    old = offer(created_time="2026-07-19T12:00:00+00:00")  # 5 dni temu
    pens = scoring.compute_penalties(old, cost(), "opis", NOW, CONF["scoring"]["penalties"])
    assert any(d == -5 for _, d in pens)


# --- Agregacja ---
def test_score_offer_sums_and_builds_sections():
    s = scoring.score_offer(offer(price=2500, area_m2=45, district="Oliwa"),
                            cost(total=2700), "po remoncie, osobna sypialnia, pralka, lodówka",
                            NOW, CONF)
    # 30 (koszt całk. 2700<=2800) + 25 (Oliwa) + 20 (układ) + 15 (remont) + 4 (pralka+lodówka) = 94
    assert s.breakdown["Cena"] == 30
    assert s.breakdown["Lokalizacja"] == 25
    assert s.total == 94
    assert s.do_zapytania  # niepuste (co najmniej flaga o układzie)


def test_score_offer_never_negative():
    s = scoring.score_offer(offer(price=None, district="Nigdzie", rooms=2, area_m2=36),
                            cost(total=None, heating="electric", czynsz_estimated=True),
                            "prowizja 100% czynszu", NOW, CONF)
    assert s.total >= 0
