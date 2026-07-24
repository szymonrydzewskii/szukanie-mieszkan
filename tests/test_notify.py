import json

from core import notify
from core.cost import CostBreakdown
from core.scoring import Score
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


def make_score(total=90):
    return Score(total=total,
                 breakdown={"Cena": 30, "Lokalizacja": 25, "Układ i metraż": 20,
                            "Standard": 10, "Wyposażenie": 5},
                 penalties=[("ogrzewanie elektryczne", -8)],
                 plusy=["dobra lokalizacja (Oliwa)"],
                 minusy=["ogrzewanie elektryczne"],
                 do_zapytania=["układ/sypialnia — poproś o zdjęcia"])


OWNER_TMPL = "Dzień dobry, czy mieszkanie ({district}, {area} m², {rooms} pok.) jest dostępne?"


def test_embed_shows_score_and_breakdown():
    embed = notify.build_embed(make_offer(), make_score(90), make_cost())
    names = {f["name"]: f["value"] for f in embed["fields"]}
    assert any("90" in v and "100" in v for v in names.values())


def test_color_green_for_top():
    embed = notify.build_embed(make_offer(), make_score(90), make_cost())
    assert embed["color"] == notify.COLOR_GREEN


def test_color_yellow_for_mid_band():
    embed = notify.build_embed(make_offer(), make_score(80), make_cost())
    assert embed["color"] == notify.COLOR_YELLOW


def test_embed_includes_owner_message():
    embed = notify.build_embed(make_offer(district="Oliwa", area_m2=45, rooms=2),
                               make_score(90), make_cost(), owner_message_template=OWNER_TMPL)
    blob = json.dumps(embed, ensure_ascii=False)
    assert "Oliwa" in blob and "45" in blob and "dostępne" in blob


def test_embed_includes_sections_and_station():
    embed = notify.build_embed(make_offer(), make_score(90), make_cost(),
                               station_info=("Gdańsk Oliwa", 8))
    blob = json.dumps(embed, ensure_ascii=False)
    assert "Gdańsk Oliwa" in blob and "8" in blob
    assert "dobra lokalizacja (Oliwa)" in blob  # plus
    assert "📞" in blob  # ma telefon


def test_embed_substitutes_photo_size():
    embed = notify.build_embed(make_offer(), make_score(90), make_cost(), photo_size="640x480")
    assert embed["thumbnail"]["url"] == "https://cdn/x;s=640x480"


def test_price_drop_marks_obnizka():
    embed = notify.build_embed(make_offer(price=2350), make_score(90), make_cost(total=3200),
                               price_drop=(2500, 2350))
    blob = json.dumps(embed, ensure_ascii=False)
    assert "OBNIŻKA" in blob and "2 500" in blob and "2 350" in blob


def test_rejected_embed_is_compact_with_score_and_reason():
    embed = notify.build_rejected_embed(make_offer(), make_score(70), make_cost(),
                                        reason="ocena 70 — poniżej progu")
    blob = json.dumps(embed, ensure_ascii=False)
    assert "70" in blob and "poniżej progu" in blob
    # kompaktowy: mniej pól niż pełny embed
    assert len(embed.get("fields", [])) <= 3
