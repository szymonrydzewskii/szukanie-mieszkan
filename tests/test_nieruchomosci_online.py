from sources.nieruchomosci_online import NieruchomosciOnlineSource


FIXTURE = """
<div class="listing">
  <div class="tile" data-id="a26832013" data-market-type="secondary" data-location-alias="gdansk">
    <a href="https://gdansk.nieruchomosci-online.pl/mieszkanie,m2/26832013.html">
      <h2 class="name">Mieszkanie umeblowane, ul. Krynicka</h2>
    </a>
    <span class="title-a">3&nbsp;600&nbsp;zł 39&nbsp;m² 92,31&nbsp;zł/m²</span>
    <span class="area">39&nbsp;m²</span>
    <span class="province">Przymorze Małe, Gdańsk</span>
    <div class="tile-details">Piętro: 3 Liczba pokoi: 2 Umeblowane: tak. Mieszkanie dla dwójki studentów.</div>
  </div>
  <div class="tile" data-id="a26900000" data-market-type="secondary" data-location-alias="sopot">
    <a href="https://sopot.nieruchomosci-online.pl/mieszkanie/26900000.html">
      <h2 class="name">Apartament 2-pokojowy, ul. Monte Cassino</h2>
    </a>
    <span class="title-a">2&nbsp;900&nbsp;zł 45&nbsp;m²</span>
    <span class="area">45&nbsp;m²</span>
    <span class="province">Dolny Sopot, Sopot</span>
    <div class="tile-details">Liczba pokoi: 2</div>
  </div>
  <div class="tile" data-id="a26955555" data-market-type="primary" data-location-alias="gdansk">
    <a href="https://gdansk.nieruchomosci-online.pl/mieszkanie/26955555.html">
      <h2 class="name">Nowe mieszkanie od dewelopera</h2></a>
    <span class="title-a">3&nbsp;000&nbsp;zł 40&nbsp;m²</span>
    <span class="province">Jasień, Gdańsk</span>
    <div class="tile-details">Liczba pokoi: 2</div>
  </div>
  <div class="tile tile-plug"><div class="tile-plug__content">reklama</div></div>
</div>
"""


def parse(html):
    return NieruchomosciOnlineSource(config={}, http={})._parse_html(html)


def test_parses_secondary_offers_skips_plug_and_primary():
    offers = parse(FIXTURE)
    # 2 wtórne mieszkania; pominięte: rynek pierwotny (deweloper) i reklama (bez id/linku)
    assert len(offers) == 2


def test_first_offer_fields():
    o = parse(FIXTURE)[0]
    assert o.source == "nieruchomosci_online"
    assert o.source_id == "26832013"
    assert "26832013.html" in o.url
    assert o.price == 3600
    assert o.area_m2 == 39.0
    assert o.rooms == 2
    assert o.city == "Gdańsk"
    assert o.district == "Przymorze Małe"
    assert o.novelty_key == "000026832013"
    assert "studentów" in (o.description or "").lower()   # opis dostępny na kafelku


def test_second_offer_city_sopot_and_comma_area():
    o = parse(FIXTURE)[1]
    assert o.city == "Sopot" and o.district == "Dolny Sopot"
    assert o.price == 2900 and o.rooms == 2 and o.area_m2 == 45.0
