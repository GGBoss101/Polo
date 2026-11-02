from datetime import date

import pytest

from polo_extract.normalize import match_building, normalize, resolve_date_text

TODAY = date(2026, 11, 1)  # Sunday


@pytest.mark.parametrize("text,code,room", [
    ("ICCS X150", "ICCS", "X150"),
    ("BUCH A102", "BUCH", "A102"),
    ("the Nest, room 2306", "NEST", "2306"),
    ("AMS Student Nest", "NEST", None),
    ("IKB 182", "IBLC", "182"),
    ("Irving K. Barber Learning Centre", "IBLC", None),
    ("Sauder", "ANGU", None),
    ("Life Sci Centre lobby", "LSC", None),
    ("Koerner Libary", "KOER", None),
    ("Birdcoop", "SRC", None),
])
def test_match_building(text, code, room):
    m = match_building(text)
    assert m is not None
    assert m.building.code == code
    assert m.room == room


def test_match_building_none():
    assert match_building("Jericho Beach") is None
    assert match_building(None) is None


@pytest.mark.parametrize("text,expected", [
    ("today", date(2026, 11, 1)),
    ("tomorrow at 5", date(2026, 11, 2)),
    ("this Friday", date(2026, 11, 6)),
    ("Thurs", date(2026, 11, 5)),
    ("Sunday", date(2026, 11, 1)),
    ("next Sunday", date(2026, 11, 8)),
    ("Nov 7", date(2026, 11, 7)),
    ("November 14th", date(2026, 11, 14)),
    ("14 Nov", date(2026, 11, 14)),
    ("Jan 9", date(2027, 1, 9)),
    ("2026-12-03", date(2026, 12, 3)),
    ("sometime soon", None),
])
def test_resolve_date_text(text, expected):
    assert resolve_date_text(text, TODAY) == expected


def test_normalize_happy_path(make_event):
    e = normalize(make_event(), TODAY)
    assert e.building_code == "ICCS"
    assert e.room == "X150"
    assert e.date == "2026-11-07"
    assert e.needs_review == []
    assert not e.all_day


def test_normalize_flags_date_disagreement(make_event):
    e = normalize(make_event(date_text="Thursday", date="2026-11-07"), TODAY)
    assert "date" in e.needs_review
    assert e.confidence["date"] <= 0.5


def test_normalize_falls_back_to_rule_date(make_event):
    e = normalize(make_event(date=None, date_text="tomorrow"), TODAY)
    assert e.date == "2026-11-02"


def test_normalize_flags_missing_and_low_confidence(make_event):
    ev = make_event(start_time=None, location_text="Somewhere downtown")
    ev.confidence.title = 0.3
    e = normalize(ev, TODAY)
    assert e.all_day
    assert {"start_time", "location", "title"} <= set(e.needs_review)


def test_normalize_bad_time_format(make_event):
    e = normalize(make_event(start_time="6pm", end_time="25:00"), TODAY)
    assert e.start_time is None and e.end_time is None
