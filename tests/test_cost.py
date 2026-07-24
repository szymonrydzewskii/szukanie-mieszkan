from core import cost
from sources.base import Offer


CONFIG = {
    "budget": {
        "hard_limit": 3500,
        "min_plausible_rent": 50,
        "estimates": {
            "czynsz_blok": 550,
            "czynsz_kamienica": 400,
            "media_default": 350,
            "media_electric": 700,
        },
    },
    "heating": {
        "electric_keywords": ["ogrzewanie elektryczne", "grzejniki elektryczne"],
        "reject_keywords": ["piec kaflowy", "węglowe", "ogrzewanie piecowe"],
    },
}


def offer(**kw):
    base = dict(source="olx", source_id="1", url="u", title="t",
                price=2500, rent_admin=400, area_m2=45.0, rooms=2,
                builttype="blok", city="Gdańsk", district="Wrzeszcz")
    base.update(kw)
    return Offer(**base)


def compute(o, text=""):
    return cost.compute_cost(o, text, CONFIG)


def test_total_sums_najem_rent_and_default_media():
    c = compute(offer(price=2500, rent_admin=400))
    assert c.media == 350 and c.media_estimated is True
    assert c.czynsz == 400 and c.czynsz_estimated is False
    assert c.total == 2500 + 400 + 350


def test_missing_rent_estimated_from_builttype_blok():
    c = compute(offer(rent_admin=None, builttype="blok"))
    assert c.czynsz == 550 and c.czynsz_estimated is True
    assert any("czynsz" in n.lower() for n in c.notes)


def test_missing_rent_estimated_from_kamienica():
    c = compute(offer(rent_admin=None, builttype="kamienica"))
    assert c.czynsz == 400 and c.czynsz_estimated is True


def test_other_builttype_uses_block_estimate():
    c = compute(offer(rent_admin=None, builttype="apartamentowiec"))
    assert c.czynsz == 550


def test_implausibly_low_rent_is_treated_as_missing():
    # rent_admin=1 zł to śmieciowy placeholder -> szacujemy jak przy braku danych
    c = compute(offer(rent_admin=1, builttype="blok"))
    assert c.czynsz == 550 and c.czynsz_estimated is True


def test_electric_heating_bumps_media_to_700():
    c = compute(offer(price=2500, rent_admin=400), text="mieszkanie, ogrzewanie elektryczne")
    assert c.heating == "electric"
    assert c.media == 700
    assert c.total == 2500 + 400 + 700


def test_stove_heating_is_flagged():
    c = compute(offer(), text="stary piec kaflowy w salonie")
    assert c.heating == "stove"


def test_no_heating_keywords_gives_none_and_default_media():
    c = compute(offer(), text="ciche i jasne mieszkanie")
    assert c.heating is None
    assert c.media == 350


def test_missing_najem_gives_no_total():
    c = compute(offer(price=None))
    assert c.total is None


def test_media_always_estimated_and_noted():
    c = compute(offer())
    assert c.media_estimated is True
    assert any("media" in n.lower() for n in c.notes)
