from core import scoring

CFG = {
    "thresholds": {"top": 88, "main": 78, "rejected": 60},
    "limits": {"daily_main": 8, "daily_78_87": 6},
}


def route(total, daily_main=0, daily_band=0):
    return scoring.decide_route(total, daily_main, daily_band, CFG)


def test_top_goes_to_main_with_ping():
    r = route(90)
    assert r.channel == "main" and r.ping is True


def test_mid_band_goes_to_main_no_ping_under_limits():
    r = route(80)
    assert r.channel == "main" and r.ping is False


def test_mid_band_suppressed_when_main_daily_limit_reached():
    r = route(80, daily_main=8)
    assert r.channel == "rejected"


def test_mid_band_suppressed_when_band_limit_reached():
    r = route(80, daily_band=6)
    assert r.channel == "rejected"


def test_60_to_77_goes_rejected():
    r = route(70)
    assert r.channel == "rejected"


def test_below_60_not_sent():
    r = route(50)
    assert r.channel is None


def test_top_still_main_even_over_limits():
    r = route(95, daily_main=20, daily_band=20)
    assert r.channel == "main" and r.ping is True
