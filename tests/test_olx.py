from sources.olx import OlxSource


RAW = {
    "id": 123,
    "url": "https://olx.pl/d/x",
    "title": "Mieszkanie 2 pokoje",
    "created_time": "2026-07-24T10:00:00+02:00",
    "description": "Ładne mieszkanie",
    "params": [
        {"key": "price", "value": {"value": 2500, "currency": "PLN",
                                    "arranged": False, "negotiable": False}},
        {"key": "rent", "value": {"key": "400"}},
        {"key": "m", "value": {"key": "45"}},
        {"key": "rooms", "value": {"key": "two"}},
        {"key": "builttype", "value": {"key": "blok", "label": "Blok"}},
        {"key": "floor_select", "value": {"key": "floor_2", "label": "2"}},
    ],
    "location": {"city": {"name": "Gdańsk"}, "district": {"name": "Wrzeszcz"}},
    "map": {"lat": 54.4098, "lon": 18.5810, "zoom": 13},
    "photos": [{"link": "https://cdn/x;s={width}x{height}"}],
    "contact": {"phone": True},
}


def parse(raw):
    return OlxSource(config={"cities": {}}, http={})._parse_offer(raw)


def test_parses_builttype():
    assert parse(RAW).builttype == "blok"


def test_parses_coordinates():
    o = parse(RAW)
    assert o.lat == 54.4098
    assert o.lon == 18.5810


def test_parses_floor():
    assert parse(RAW).floor == "2"
    parter = dict(RAW, params=[{"key": "floor_select", "value": {"key": "floor_0"}}])
    assert parse(parter).floor == "parter"


def test_parses_core_fields():
    o = parse(RAW)
    assert o.price == 2500
    assert o.rent_admin == 400
    assert o.area_m2 == 45.0
    assert o.rooms == 2
    assert o.city == "Gdańsk"
    assert o.district == "Wrzeszcz"
    assert o.has_phone is True
