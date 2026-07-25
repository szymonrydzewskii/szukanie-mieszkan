import json

from core import notify
from core.cost import CostBreakdown
from sources.base import Offer


def make_offer(**kw):
    base = dict(
        source="olx", source_id="123", url="https://olx.pl/d/x", title="Mieszkanie",
        price=2500, rent_admin=500, area_m2=45.0, rooms=2, floor="2", city="Gdańsk",
        district="Oliwa", has_phone=True, photo_url="https://cdn/x;s={width}x{height}",
    )
    base.update(kw)
    return Offer(**base)


def make_cost(total=3350, czynsz=500, czynsz_estimated=False, media=350,
              heating=None, notes=None):
    return CostBreakdown(najem=2500, czynsz=czynsz, czynsz_estimated=czynsz_estimated,
                         media=media, media_estimated=True, heating=heating,
                         total=total, notes=notes or ["media ≈ 350 zł"])


OWNER = "Dzień dobry, czy mieszkanie ({district}, {area} m², {rooms} pok.) jest dostępne?"


def test_embed_has_cost_no_score():
    embed = notify.build_embed(make_offer(), make_cost())
    blob = json.dumps(embed, ensure_ascii=False)
    names = {f["name"] for f in embed["fields"]}
    assert "Koszt całkowity" in names
    assert "/100" not in blob and "Ocena" not in names   # ocena usunięta


def test_match_color_is_green():
    assert notify.build_embed(make_offer(), make_cost())["color"] == notify.COLOR_GREEN


def test_embed_includes_owner_message_and_questions():
    embed = notify.build_embed(make_offer(district="Oliwa", area_m2=45, rooms=2),
                               make_cost(), owner_message_template=OWNER)
    blob = json.dumps(embed, ensure_ascii=False)
    assert "dostępne" in blob and "Oliwa" in blob
    assert "Do zapytania" in blob


def test_embed_includes_station_and_phone():
    embed = notify.build_embed(make_offer(), make_cost(), station_info=("Gdańsk Oliwa", 8))
    blob = json.dumps(embed, ensure_ascii=False)
    assert "Gdańsk Oliwa" in blob and "8" in blob and "📞" in blob


def test_embed_substitutes_photo_size():
    embed = notify.build_embed(make_offer(), make_cost(), photo_size="640x480")
    assert embed["thumbnail"]["url"] == "https://cdn/x;s=640x480"


def test_price_drop_marks_obnizka():
    embed = notify.build_embed(make_offer(price=2350), make_cost(total=3200),
                               price_drop=(2500, 2350))
    blob = json.dumps(embed, ensure_ascii=False)
    assert "OBNIŻKA" in blob and "2 500" in blob and "2 350" in blob


def test_sale_embed_shows_price_and_price_per_m2():
    embed = notify.build_sale_embed(make_offer(price=550000, area_m2=50.0), price_per_m2=11000,
                                    is_deal=False)
    blob = json.dumps(embed, ensure_ascii=False)
    assert "550 000 zł" in blob and "11 000" in blob and "zł/m²" in blob
    assert "OKAZJA" not in blob


def test_sale_embed_marks_okazja_when_deal():
    embed = notify.build_sale_embed(make_offer(price=550000, area_m2=60.0), price_per_m2=9167,
                                    is_deal=True)
    blob = json.dumps(embed, ensure_ascii=False)
    assert "OKAZJA" in blob
    assert embed["color"] == notify.COLOR_GOLD


def test_sale_rejected_embed_compact_with_reason():
    embed = notify.build_sale_rejected_embed(make_offer(price=630000), price_per_m2=14000,
                                             reason="cena 630000 zł — powyżej budżetu")
    blob = json.dumps(embed, ensure_ascii=False)
    assert "powyżej budżetu" in blob and embed["color"] == notify.COLOR_AMBER
    assert len(embed.get("fields", [])) <= 4


def test_near_miss_embed_is_compact_amber_with_reason():
    embed = notify.build_rejected_embed(make_offer(), make_cost(total=3650),
                                        reason="koszt 3650 zł — ponad limit")
    blob = json.dumps(embed, ensure_ascii=False)
    assert embed["color"] == notify.COLOR_AMBER
    assert "ponad limit" in blob
    assert len(embed.get("fields", [])) <= 3
