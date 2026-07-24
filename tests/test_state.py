from datetime import date, datetime, timedelta, timezone

import pytest

from core import state


def test_load_missing_file_returns_empty_state(tmp_path):
    result = state.load_state(tmp_path / "seen.json")
    assert result == {"version": 1, "seen": {}, "high_water": {}, "daily": {}}


def test_save_then_load_roundtrips_entries(tmp_path):
    path = tmp_path / "seen.json"
    st = state.load_state(path)
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    state.record(st, "olx:123", fingerprint="fp1", cena=2500, sent_at=now)
    state.save_state(path, st)

    reloaded = state.load_state(path)
    assert reloaded["seen"]["olx:123"] == {
        "id": "olx:123",
        "fingerprint": "fp1",
        "cena": 2500,
        "data_wyslania": now.isoformat(),
    }


def test_save_is_deterministic_for_stable_diffs(tmp_path):
    path = tmp_path / "seen.json"
    st = state.load_state(path)  # znormalizowany, pusty stan
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)
    # Insert in a deliberately non-sorted order.
    state.record(st, "olx:200", fingerprint="b", cena=3000, sent_at=now)
    state.record(st, "olx:100", fingerprint="a", cena=2000, sent_at=now)
    state.save_state(path, st)
    first = path.read_text(encoding="utf-8")

    state.save_state(path, state.load_state(path))
    second = path.read_text(encoding="utf-8")
    assert first == second
    # Keys must be sorted so git diffs stay minimal.
    assert first.index('"olx:100"') < first.index('"olx:200"')


def test_load_corrupt_json_raises(tmp_path):
    path = tmp_path / "seen.json"
    path.write_text("{ this is not json ", encoding="utf-8")
    with pytest.raises(state.StateError):
        state.load_state(path)


def test_record_updates_existing_entry(tmp_path):
    st = {"version": 1, "seen": {}}
    t1 = datetime(2026, 7, 20, tzinfo=timezone.utc)
    t2 = datetime(2026, 7, 24, tzinfo=timezone.utc)
    state.record(st, "olx:1", fingerprint="fp", cena=2500, sent_at=t1)
    state.record(st, "olx:1", fingerprint="fp", cena=2300, sent_at=t2)
    assert len(st["seen"]) == 1
    assert st["seen"]["olx:1"]["cena"] == 2300
    assert st["seen"]["olx:1"]["data_wyslania"] == t2.isoformat()


def test_is_seen_and_get_entry():
    st = {"version": 1, "seen": {}}
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)
    state.record(st, "olx:1", fingerprint="fp", cena=2500, sent_at=now)
    assert state.is_seen(st, "olx:1") is True
    assert state.is_seen(st, "olx:2") is False
    assert state.get_entry(st, "olx:1")["cena"] == 2500
    assert state.get_entry(st, "olx:2") is None


def test_has_source_detects_prefix():
    st = {"version": 1, "seen": {}}
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)
    assert state.has_source(st, "olx") is False
    state.record(st, "olx:1", fingerprint="fp", cena=2500, sent_at=now)
    assert state.has_source(st, "olx") is True
    assert state.has_source(st, "otodom") is False


def test_high_water_defaults_to_none():
    st = {"version": 1, "seen": {}}
    assert state.get_high_water(st, "olx") is None


def test_set_and_get_high_water():
    st = {"version": 1, "seen": {}}
    state.set_high_water(st, "olx", "2026-07-24T11:00:00+00:00")
    assert state.get_high_water(st, "olx") == "2026-07-24T11:00:00+00:00"
    assert state.get_high_water(st, "otodom") is None


def test_high_water_survives_save_load(tmp_path):
    path = tmp_path / "seen.json"
    st = state.load_state(path)
    state.set_high_water(st, "olx", "2026-07-24T11:00:00+00:00")
    state.save_state(path, st)
    assert state.get_high_water(state.load_state(path), "olx") == "2026-07-24T11:00:00+00:00"


def test_daily_counter_bump_and_get():
    st = {"version": 1, "seen": {}, "high_water": {}, "daily": {}}
    state.bump_daily(st, "2026-07-24", "main")
    state.bump_daily(st, "2026-07-24", "main")
    state.bump_daily(st, "2026-07-24", "band")
    assert state.get_daily(st, "2026-07-24", "main") == 2
    assert state.get_daily(st, "2026-07-24", "band") == 1
    assert state.get_daily(st, "2026-07-24", "rejected") == 0
    assert state.get_daily(st, "2026-07-23", "main") == 0


def test_prune_daily_removes_old_days():
    st = {"version": 1, "seen": {}, "high_water": {},
          "daily": {"2026-05-01": {"main": 3}, "2026-07-24": {"main": 1}}}
    state.prune_daily(st, keep_days=30, today=date(2026, 7, 24))
    assert "2026-05-01" not in st["daily"]
    assert "2026-07-24" in st["daily"]


def test_prune_removes_entries_older_than_max_age():
    st = {"version": 1, "seen": {}}
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)
    old = now - timedelta(days=61)
    fresh = now - timedelta(days=10)
    state.record(st, "olx:old", fingerprint="fp", cena=1000, sent_at=old)
    state.record(st, "olx:fresh", fingerprint="fp", cena=1000, sent_at=fresh)

    removed = state.prune(st, max_age_days=60, now=now)
    assert removed == 1
    assert "olx:old" not in st["seen"]
    assert "olx:fresh" in st["seen"]
