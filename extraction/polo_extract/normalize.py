import csv
import re
from dataclasses import dataclass
from datetime import date, timedelta
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from .schema import Event, ExtractedEvent

BUILDINGS_CSV = Path(__file__).parent / "data" / "ubc_buildings.csv"
REVIEW_THRESHOLD = 0.7

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY_ABBR = {d[:3]: i for i, d in enumerate(WEEKDAYS)} | {"tues": 1, "thur": 3, "thurs": 3}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}
MONTH_ABBR = {m[:3]: n for m, n in MONTHS.items()} | {"sept": 9}


@dataclass(frozen=True)
class Building:
    code: str
    name: str
    aliases: tuple[str, ...]


@dataclass
class BuildingMatch:
    building: Building
    room: str | None
    score: float


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


@lru_cache
def buildings() -> dict[str, Building]:
    with BUILDINGS_CSV.open() as f:
        rows = list(csv.DictReader(f))
    return {
        r["code"]: Building(r["code"], r["name"], tuple(_clean(a) for a in r["aliases"].split("|") if a))
        for r in rows
    }


def match_building(location: str | None) -> BuildingMatch | None:
    if not location:
        return None
    table = buildings()

    m = re.search(r"\b([A-Z]{2,5})\s*-?\s*([A-Z]?\d{3,4}[A-Z]?)\b", location)
    if m and m.group(1) in table:
        return BuildingMatch(table[m.group(1)], m.group(2), 1.0)

    room = None
    rm = re.search(r"\b(?:room|rm\.?)\s*#?\s*([A-Z]?\d{2,4}[A-Z]?)\b", location, re.I)
    if rm:
        room = rm.group(1).upper()

    text = f" {_clean(location)} "
    best: tuple[int, Building, str] | None = None
    for b in table.values():
        for term in (_clean(b.name), _clean(b.code), *b.aliases):
            if term and f" {term} " in text and (best is None or len(term) > best[0]):
                best = (len(term), b, term)
    if best:
        if room is None:
            after = re.search(rf"\b{re.escape(best[2])}\s+([a-z]?\d{{3,4}}[a-z]?)\b", text)
            room = after.group(1).upper() if after else None
        return BuildingMatch(best[1], room, 0.95)

    words = text.split()
    top: tuple[float, Building] | None = None
    for b in table.values():
        for term in (_clean(b.name), *b.aliases):
            n = len(term.split())
            for i in range(max(1, len(words) - n + 1)):
                ratio = SequenceMatcher(None, term, " ".join(words[i:i + n])).ratio()
                if ratio >= 0.85 and (top is None or ratio > top[0]):
                    top = (ratio, b)
    if top:
        return BuildingMatch(top[1], room, round(top[0] * 0.9, 3))
    return None


def resolve_date_text(text: str, today: date) -> date | None:
    t = _clean(text)
    if not t:
        return None
    if re.search(r"\btoday\b|\btonight\b", t):
        return today
    if re.search(r"\btomorrow\b", t):
        return today + timedelta(days=1)

    m = re.search(r"\b(\d{4}) (\d{1,2}) (\d{1,2})\b", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    month = day = None
    m = re.search(r"\b([a-z]+) (\d{1,2})(?:st|nd|rd|th)?\b", t)
    if m and (m.group(1) in MONTHS or m.group(1) in MONTH_ABBR):
        month, day = MONTHS.get(m.group(1)) or MONTH_ABBR[m.group(1)], int(m.group(2))
    else:
        m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)? ([a-z]+)\b", t)
        if m and (m.group(2) in MONTHS or m.group(2) in MONTH_ABBR):
            month, day = MONTHS.get(m.group(2)) or MONTH_ABBR[m.group(2)], int(m.group(1))
    if month:
        for year in (today.year, today.year + 1):
            try:
                d = date(year, month, day)
            except ValueError:
                return None
            if d >= today:
                return d
        return None

    for word in t.split():
        idx = WEEKDAYS.index(word) if word in WEEKDAYS else WEEKDAY_ABBR.get(word)
        if idx is not None:
            delta = (idx - today.weekday()) % 7
            if "next" in t.split() and delta == 0:
                delta = 7
            return today + timedelta(days=delta)
    return None


def _valid_iso(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _valid_time(s: str | None) -> str | None:
    if not s:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s.strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def normalize(e: ExtractedEvent, today: date) -> Event:
    conf = e.confidence.model_dump()
    review: set[str] = {k for k, v in conf.items() if v < REVIEW_THRESHOLD}

    llm_date = _valid_iso(e.date)
    rule_date = resolve_date_text(e.date_text, today)
    final_date = llm_date or rule_date
    if final_date is None:
        review.add("date")
    elif llm_date and rule_date and llm_date != rule_date:
        review.add("date")
        conf["date"] = min(conf["date"], 0.5)

    start = _valid_time(e.start_time)
    end = _valid_time(e.end_time)
    if start is None:
        review.add("start_time")
    if start and end and end <= start:
        review.add("end_time")

    match = match_building(e.location_text)
    if e.location_text and match is None:
        review.add("location")
    if match:
        conf["location"] = round(min(conf["location"], match.score), 3)

    return Event(
        title=e.title.strip(),
        date=final_date.isoformat() if final_date else None,
        start_time=start,
        end_time=end,
        all_day=start is None,
        location_text=e.location_text,
        building_code=match.building.code if match else None,
        building_name=match.building.name if match else None,
        room=e.room or (match.room if match else None),
        organizer=e.organizer,
        description=e.description,
        free_food=e.free_food,
        cost=e.cost,
        category=e.category,
        link=e.link,
        confidence=conf,
        needs_review=sorted(review),
    )
