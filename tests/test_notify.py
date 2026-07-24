import json

from core import notify
from core.cost import CostBreakdown
from sources.base import Offer


def make_offer(**kw):
    base = dict(
        source="olx", source_id="123", url="https://olx.pl/d/x", title="Mieszkanie",
        price=2500, rent_admin=500, area_m2=45.0, rooms=2, city="Gdańsk",
        district="Wrzeszcz", photo_url="https://cdn/x;s={width}x{height}",
    )
    base.update(kw)
    return Offer(**base)


def make_cost(total=3350, czynsz=500, czynsz_estimated=False, media=350,
              heating=None, notes=None):
    return CostBreakdown(najem=2500, czynsz=czynsz, czynsz_estimated=czynsz_estimated,
                         media=media, media_estimated=True, heating=heating,
                         total=total, notes=notes or ["media ≈ 350 zł"])


def test_embed_has_title_url_and_najem_field():
    embed = notify.build_embed(make_offer(), cost=make_cost())
    assert embed["title"] == "Mieszkanie"
    assert embed["url"] == "https://olx.pl/d/x"
    names = {f["name"]: f["value"] for f in embed["fields"]}
    assert names["Najem"].startswith("2 500 zł")


def test_embed_substitutes_photo_size():
    embed = notify.build_embed(make_offer(), cost=make_cost(), photo_size="640x480")
    assert embed["thumbnail"]["url"] == "https://cdn/x;s=640x480"


def test_embed_shows_total_cost():
    embed = notify.build_embed(make_offer(), cost=make_cost(total=3350))
    names = {f["name"]: f["value"] for f in embed["fields"]}
    assert "Koszt całkowity" in names
    assert "3 350 zł" in names["Koszt całkowity"]


def test_embed_marks_estimated_parts_with_warning():
    cost = make_cost(czynsz=550, czynsz_estimated=True,
                     notes=["czynsz administracyjny (blok) ≈ 550 zł", "media ≈ 350 zł"])
    embed = notify.build_embed(make_offer(rent_admin=None), cost=cost)
    blob = json.dumps(embed, ensure_ascii=False)
    assert "⚠" in blob
    assert "czynsz administracyjny (blok) ≈ 550 zł" in blob


def test_embed_with_price_drop_marks_obnizka():
    embed = notify.build_embed(make_offer(price=2350), cost=make_cost(total=3200),
                               price_drop=(2500, 2350))
    blob = json.dumps(embed, ensure_ascii=False)
    assert "OBNIŻKA" in blob
    assert "2 500" in blob and "2 350" in blob
