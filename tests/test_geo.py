from core import geo


STATIONS = [
    {"name": "Gdańsk Oliwa", "lat": 54.4090, "lon": 18.5760, "on_axis": True},
    {"name": "Sopot", "lat": 54.4420, "lon": 18.5610, "on_axis": True},
    {"name": "Gdańsk Wrzeszcz", "lat": 54.3800, "lon": 18.6090, "on_axis": False},
]


def test_haversine_zero_for_same_point():
    assert geo.haversine(54.4, 18.5, 54.4, 18.5) == 0


def test_haversine_one_degree_latitude_is_about_111km():
    d = geo.haversine(54.0, 18.0, 55.0, 18.0)
    assert 110_000 < d < 112_000


def test_walk_minutes_applies_factor_and_speed():
    # 830 m w linii prostej * 1.3 / 83 m/min = 13 min
    assert geo.walk_minutes(830, straight_factor=1.3, speed_m_per_min=83) == 13


def test_nearest_station_picks_closest():
    # punkt tuż przy Oliwie
    station, dist = geo.nearest_station(54.4095, 18.5762, STATIONS)
    assert station["name"] == "Gdańsk Oliwa"
    assert dist < 100


def test_nearest_station_none_without_coords():
    assert geo.nearest_station(None, None, STATIONS) is None


def test_nearest_on_axis_ignores_off_axis():
    # punkt bliżej Wrzeszcza (off-axis), ale on-axis ma być Oliwa/Sopot
    station, dist = geo.nearest_on_axis(54.3800, 18.6090, STATIONS)
    assert station["on_axis"] is True
    assert station["name"] in {"Gdańsk Oliwa", "Sopot"}
