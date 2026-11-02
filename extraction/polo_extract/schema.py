from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "social", "academic", "career", "sports", "arts", "cultural",
    "wellness", "volunteering", "meetup", "other",
]


class FieldConfidence(BaseModel):
    title: float
    date: float
    start_time: float
    end_time: float
    location: float


class ExtractedEvent(BaseModel):
    """What the model returns for one event. Dates/times are as the model resolved them."""

    title: str
    date_text: str = Field(description="Date exactly as written on the source, e.g. 'Fri Nov 7' or 'this Thursday'")
    date: str | None = Field(description="Resolved ISO date YYYY-MM-DD, or null if unclear")
    start_time: str | None = Field(description="24h HH:MM, or null")
    end_time: str | None = Field(description="24h HH:MM, or null")
    location_text: str | None = Field(description="Location exactly as written")
    room: str | None
    organizer: str | None
    description: str | None = Field(description="One or two sentences, no marketing fluff")
    free_food: bool
    cost: str | None = Field(description="e.g. 'Free', '$5', '$10 members / $15 non-members'")
    category: Category
    link: str | None = Field(description="URL or @handle shown on the source")
    confidence: FieldConfidence


class Extraction(BaseModel):
    is_event_source: bool = Field(description="False if the input is not an event poster/announcement")
    events: list[ExtractedEvent]


class Event(BaseModel):
    """Normalized event returned to clients and fed into .ics."""

    title: str
    date: str | None
    start_time: str | None
    end_time: str | None
    all_day: bool = False
    location_text: str | None = None
    building_code: str | None = None
    building_name: str | None = None
    room: str | None = None
    organizer: str | None = None
    description: str | None = None
    free_food: bool = False
    cost: str | None = None
    category: str = "other"
    link: str | None = None
    confidence: dict[str, float] = {}
    needs_review: list[str] = []
