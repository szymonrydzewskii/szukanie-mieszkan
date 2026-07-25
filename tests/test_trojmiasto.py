from sources.trojmiasto import TrojmiastoSource


FIXTURE = """
<div class="list__wrap">
  <article class="list__item">
    <a s-ogl="true" href="https://ogloszenia.trojmiasto.pl/nieruchomosci-mam-do-wynajecia/mieszkanie-ogl66466261.html">
      <img class="list__item__img" data-id="66466261">
    </a>
    <h2 class="list__item__content__title">
      <a class="list__item__content__title__name" href="https://ogloszenia.trojmiasto.pl/x-ogl66466261.html">2 pokoje z aneksem, Kliniczna</a>
    </h2>
    <p class="list__item__content__subtitle">Gdańsk Wrzeszcz Dolny, Kliniczna</p>
    <ul class="list__item__details__icons">
      <li class="list__item__details__icons__element details--icons--element--powierzchnia"><p class="list__item__details__icons__element__desc">37.99 m2</p></li>
      <li class="list__item__details__icons__element details--icons--element--l_pokoi"><p class="list__item__details__icons__element__desc">2                pokoje</p></li>
      <li class="list__item__details__icons__element details--icons--element--pietro"><p class="list__item__details__icons__element__desc">3 piętro</p></li>
    </ul>
    <p class="list__item__price__value"><span>3 300 zł</span></p>
    <div class="listItemFooter__date"><time datetime="2026-07-25 09:00:00">Dodano: dzisiaj</time></div>
  </article>
  <article class="list__item">
    <a s-ogl="true" href="https://ogloszenia.trojmiasto.pl/nieruchomosci-mam-do-wynajecia/sopot-ogl66470000.html"><img data-id="66470000"></a>
    <a class="list__item__content__title__name" href="https://ogloszenia.trojmiasto.pl/y-ogl66470000.html">Mieszkanie 2 pokoje Sopot</a>
    <p class="list__item__content__subtitle">Sopot Dolny, Monte Cassino</p>
    <ul class="list__item__details__icons">
      <li class="details--icons--element--powierzchnia"><p class="list__item__details__icons__element__desc">45 m2</p></li>
      <li class="details--icons--element--l_pokoi"><p class="list__item__details__icons__element__desc">2 pokoje</p></li>
    </ul>
    <p class="list__item__price__value"><span>2 300 zł</span></p>
    <div class="listItemFooter__date"><time datetime="2026-07-25 08:00:00">Dodano: dzisiaj</time></div>
  </article>
  <article class="list__item">
    <a s-ogl="true" href="https://ogloszenia.trojmiasto.pl/x-ogl66480000.html"><img data-id="66480000"></a>
    <a class="list__item__content__title__name" href="https://ogloszenia.trojmiasto.pl/z-ogl66480000.html">Pokój | Gdańsk Marina Szafarnia</a>
    <p class="list__item__content__subtitle">Gdańsk Śródmieście, Szafarnia</p>
    <p class="list__item__price__value"><span>1 800 zł</span></p>
    <div class="listItemFooter__date"><time datetime="2026-07-25 07:00:00">Dodano</time></div>
  </article>
  <article class="list__item">
    <a s-ogl="true" href="https://ogloszenia.trojmiasto.pl/x-ogl66481000.html"><img data-id="66481000"></a>
    <a class="list__item__content__title__name" href="https://ogloszenia.trojmiasto.pl/z-ogl66481000.html">Lokal usługowy 60 m2 Wrzeszcz</a>
    <p class="list__item__content__subtitle">Gdańsk Wrzeszcz, Grunwaldzka</p>
    <p class="list__item__price__value"><span>3 000 zł</span></p>
    <div class="listItemFooter__date"><time datetime="2026-07-25 06:00:00">Dodano</time></div>
  </article>
  <article class="list__item"><p>reklama bez linku do oferty</p></article>
</div>
"""


def parse(html):
    return TrojmiastoSource(config={}, http={})._parse_html(html)


def test_page_url_builds_pagination():
    src = TrojmiastoSource(config={"base_url": "https://x.pl/wynajem/"}, http={})
    assert src._page_url(1) == "https://x.pl/wynajem/"
    assert src._page_url(3) == "https://x.pl/wynajem/?strona=3"
    src2 = TrojmiastoSource(config={"base_url": "https://x.pl/wynajem/?a=1"}, http={})
    assert src2._page_url(2) == "https://x.pl/wynajem/?a=1&strona=2"


def test_fetch_aggregates_pages_and_dedupes():
    src = TrojmiastoSource(config={"base_url": "https://x.pl/", "pages": 3}, http={})
    pages = {
        "https://x.pl/": FIXTURE,                       # 2 mieszkania (66466261, 66470000)
        "https://x.pl/?strona=2": FIXTURE,              # te same -> dedup
        "https://x.pl/?strona=3": FIXTURE.replace("66466261", "66499999"),
    }
    src._get_html = lambda url: pages[url]
    offers = src.fetch()
    ids = sorted(o.source_id for o in offers)
    assert ids == ["66466261", "66470000", "66499999"]   # bez duplikatów, z 3 stron


def test_fetch_raises_when_nothing_parsed():
    import pytest
    from sources.base import SourceError
    src = TrojmiastoSource(config={"base_url": "https://x.pl/", "pages": 1}, http={})
    src._get_html = lambda url: "<html><body>brak ofert</body></html>"
    with pytest.raises(SourceError):
        src.fetch()


def test_parses_only_apartments():
    offers = parse(FIXTURE)
    # 2 mieszkania; pominięte: reklama bez linku, "Pokój | Marina", "Lokal usługowy"
    assert len(offers) == 2
    assert all("pokój" not in o.title.lower() and "lokal" not in o.title.lower() for o in offers)


def test_first_offer_fields():
    o = parse(FIXTURE)[0]
    assert o.source == "trojmiasto"
    assert o.source_id == "66466261"
    assert "ogl66466261.html" in o.url
    assert o.price == 3300
    assert o.area_m2 == 37.99
    assert o.rooms == 2
    assert o.floor == "3"
    assert o.city == "Gdańsk"
    assert "Wrzeszcz" in o.district
    assert o.created_time.startswith("2026-07-25T09:00:00")
    assert o.novelty_key == "000066466261"      # wyściełane ID (nowość po ID)


def test_second_offer_city_sopot():
    o = parse(FIXTURE)[1]
    assert o.city == "Sopot"
    assert o.price == 2300 and o.rooms == 2 and o.area_m2 == 45.0
