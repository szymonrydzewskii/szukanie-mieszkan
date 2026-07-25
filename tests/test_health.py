from datetime import datetime, timedelta, timezone

from core import health


NOW = datetime(2026, 7, 25, 9, 0, tzinfo=timezone.utc)


def empty_state():
    return {"version": 1, "seen": {}, "high_water": {}}


# --- luka między przebiegami (martwy cron) ---
def test_first_run_no_gap_alert():
    st = empty_state()
    assert health.note_run(st, NOW, max_gap_hours=2) is None
    assert st["last_run"] == NOW.isoformat()


def test_short_gap_no_alert():
    st = empty_state()
    health.note_run(st, NOW - timedelta(minutes=15), max_gap_hours=2)
    assert health.note_run(st, NOW, max_gap_hours=2) is None


def test_long_gap_alerts_and_updates_last_run():
    st = empty_state()
    health.note_run(st, NOW - timedelta(hours=5), max_gap_hours=2)
    msg = health.note_run(st, NOW, max_gap_hours=2)
    assert msg is not None and "5" in msg
    assert st["last_run"] == NOW.isoformat()


# --- zdrowie źródła (błąd albo zero ofert) ---
def ok(st, src="olx"):
    return health.record_source(st, src, fetched=10, error=None, threshold=3, realert_every=20)


def bad(st, src="olx", error="HTTP 403"):
    return health.record_source(st, src, fetched=0, error=error, threshold=3, realert_every=20)


def test_healthy_source_no_alert():
    st = empty_state()
    assert ok(st) is None


def test_alert_only_after_threshold():
    st = empty_state()
    assert bad(st) is None      # 1
    assert bad(st) is None      # 2
    msg = bad(st)               # 3 -> alert
    assert msg is not None and "olx" in msg and "403" in msg


def test_no_repeat_alert_right_after_threshold():
    st = empty_state()
    for _ in range(3):
        bad(st)
    assert bad(st) is None      # 4. przebieg — bez ponownego alertu


def test_realert_after_many_bad_runs():
    st = empty_state()
    msgs = [bad(st) for _ in range(23)]
    assert sum(1 for m in msgs if m) == 2   # przy 3. i przy 23. (3 + 20)


def test_zero_offers_counts_as_bad_even_without_error():
    st = empty_state()
    for _ in range(2):
        health.record_source(st, "olx", fetched=0, error=None, threshold=3, realert_every=20)
    msg = health.record_source(st, "olx", fetched=0, error=None, threshold=3, realert_every=20)
    assert msg is not None and "zero ofert" in msg.lower()


def test_success_resets_counter():
    st = empty_state()
    bad(st); bad(st)
    ok(st)
    assert bad(st) is None      # licznik wyzerowany, znów od 1


def test_sources_tracked_independently():
    st = empty_state()
    for _ in range(3):
        bad(st, "trojmiasto")
    assert ok(st, "olx") is None
    assert st["health"]["trojmiasto"]["bad"] == 3
    assert st["health"]["olx"]["bad"] == 0


# --- dzienne podsumowanie ---
def test_accumulate_sums_across_runs():
    st = empty_state()
    s = {"fetched": 100, "sent_main": 1, "sent_near": 2, "dropped": 90}
    health.accumulate_digest(st, "2026-07-25", "olx", s, None)
    health.accumulate_digest(st, "2026-07-25", "olx", s, None)
    got = st["digest"]["days"]["2026-07-25"]["sources"]["olx"]
    assert got["fetched"] == 200 and got["sent_main"] == 2 and got["sent_near"] == 4


def test_accumulate_records_unique_errors():
    st = empty_state()
    zero = {"fetched": 0}
    health.accumulate_digest(st, "2026-07-25", "olx", zero, "HTTP 403")
    health.accumulate_digest(st, "2026-07-25", "olx", zero, "HTTP 403")
    assert st["digest"]["days"]["2026-07-25"]["errors"] == ["olx: HTTP 403"]


def test_digest_not_due_same_day():
    st = empty_state()
    health.accumulate_digest(st, "2026-07-25", "olx", {"fetched": 10}, None)
    assert health.due_digest(st, NOW, digest_hour=8) is None      # dzień trwa


def test_digest_not_due_before_hour():
    st = empty_state()
    health.accumulate_digest(st, "2026-07-24", "olx", {"fetched": 10}, None)
    early = datetime(2026, 7, 25, 6, 0, tzinfo=timezone.utc)
    assert health.due_digest(st, early, digest_hour=8) is None


def test_digest_due_next_day_after_hour_and_consumed_once():
    st = empty_state()
    health.accumulate_digest(st, "2026-07-24", "olx", {"fetched": 10, "sent_main": 1}, None)
    d = health.due_digest(st, NOW, digest_hour=8)
    assert d is not None and d["date"] == "2026-07-24"
    assert d["sources"]["olx"]["sent_main"] == 1
    assert health.due_digest(st, NOW, digest_hour=8) is None   # tylko raz


def test_days_are_kept_separate():
    st = empty_state()
    health.accumulate_digest(st, "2026-07-24", "olx", {"fetched": 10}, None)
    health.accumulate_digest(st, "2026-07-25", "olx", {"fetched": 20}, None)
    d = health.due_digest(st, NOW, digest_hour=8)
    assert d["date"] == "2026-07-24" and d["sources"]["olx"]["fetched"] == 10
    assert "2026-07-25" in st["digest"]["days"]      # dzisiejszy zostaje
