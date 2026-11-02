from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from polo_extract.ics import google_calendar_url, to_ics
from polo_extract.schema import Event

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
TZ = ZoneInfo("America/Vancouver")


def utc(y, mo, d, h, mi=0):
    # Expected values come from the tz database, since BC's offset rules can change.
    return datetime(y, mo, d, h, mi, tzinfo=TZ).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ev(**kw):
    base = dict(title="Board Game Night, with pizza; all welcome", date="2026-11-07",
                start_time="18:00", end_time="21:00", building_code="ICCS",
                building_name="ICICS/CS Building", room="X150", free_food=True)
    base.update(kw)
    return Event(**base)


def test_timed_event_converts_to_utc():
    out = to_ics([ev()], NOW)
    assert f"DTSTART:{utc(2026, 11, 7, 18)}" in out
    assert f"DTEND:{utc(2026, 11, 7, 21)}" in out
    assert "SUMMARY:Board Game Night\\, with pizza\\; all welcome" in out
    assert "LOCATION:ICCS X150\\, ICICS/CS Building\\, UBC Vancouver" in out
    assert out.startswith("BEGIN:VCALENDAR\r\n") and out.endswith("END:VCALENDAR\r\n")


def test_summer_time_offset():
    out = to_ics([ev(date="2026-07-01")], NOW)
    assert "DTSTART:20260702T010000Z" in out


def test_all_day_and_default_duration():
    out = to_ics([ev(start_time=None, end_time=None, all_day=True)], NOW)
    assert "DTSTART;VALUE=DATE:20261107" in out and "DTEND;VALUE=DATE:20261108" in out
    out = to_ics([ev(end_time=None)], NOW)
    assert f"DTEND:{utc(2026, 11, 7, 19)}" in out


def test_past_midnight_end():
    out = to_ics([ev(start_time="22:00", end_time="01:00")], NOW)
    assert f"DTSTART:{utc(2026, 11, 7, 22)}" in out and f"DTEND:{utc(2026, 11, 8, 1)}" in out


def test_lines_are_folded():
    out = to_ics([ev(description="x" * 300)], NOW)
    assert all(len(l.encode()) <= 75 for l in out.split("\r\n"))


def test_undated_events_skipped_and_stable_uid():
    a = to_ics([ev(), ev(date=None)], NOW)
    assert a.count("BEGIN:VEVENT") == 1
    assert to_ics([ev()], NOW) == a


def test_google_url():
    url = google_calendar_url(ev())
    assert url.startswith("https://calendar.google.com/calendar/render?")
    assert f"{utc(2026, 11, 7, 18)}%2F{utc(2026, 11, 7, 21)}" in url
