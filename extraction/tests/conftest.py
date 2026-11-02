import pytest

from polo_extract.schema import ExtractedEvent, FieldConfidence


def _make_event(**kw):
    base = dict(
        title="CS Club Board Game Night",
        date_text="Fri Nov 7",
        date="2026-11-07",
        start_time="18:00",
        end_time="21:00",
        location_text="ICCS X150",
        room=None,
        organizer="UBC CS Club",
        description="Board games and pizza.",
        free_food=True,
        cost="Free",
        category="social",
        link="@ubccsclub",
        confidence=FieldConfidence(title=0.99, date=0.95, start_time=0.95, end_time=0.9, location=0.95),
    )
    base.update(kw)
    return ExtractedEvent(**base)


@pytest.fixture
def make_event():
    return _make_event
