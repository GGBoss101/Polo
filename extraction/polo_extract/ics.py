import hashlib
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .schema import Event

TZ = ZoneInfo("America/Vancouver")
DEFAULT_DURATION = timedelta(hours=1)


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    raw = line.encode()
    if len(raw) <= 75:
        return line
    parts, chunk = [], b""
    for ch in line:
        b = ch.encode()
        if len(chunk) + len(b) > (75 if not parts else 74):
            parts.append(chunk.decode())
            chunk = b""
        chunk += b
    parts.append(chunk.decode())
    return "\r\n ".join(parts)


def _utc(d: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=TZ).astimezone(timezone.utc)


def event_times(e: Event) -> tuple[datetime | date, datetime | date]:
    d = date.fromisoformat(e.date)
    if e.all_day or not e.start_time:
        return d, d + timedelta(days=1)
    start = _utc(d, e.start_time)
    end = _utc(d, e.end_time) if e.end_time else start + DEFAULT_DURATION
    if end <= start:
        end += timedelta(days=1)
    return start, end


def location_line(e: Event) -> str | None:
    if e.building_name:
        where = f"{e.building_name} ({e.building_code})"
        if e.room:
            where = f"{e.building_code} {e.room}, {e.building_name}"
        return f"{where}, UBC Vancouver"
    return e.location_text


def _description(e: Event) -> str:
    bits = [e.description or ""]
    if e.organizer:
        bits.append(f"Host: {e.organizer}")
    if e.cost:
        bits.append(f"Cost: {e.cost}")
    if e.free_food:
        bits.append("Free food")
    if e.link:
        bits.append(e.link)
    bits.append("Added with Polo")
    return "\n".join(b for b in bits if b)


def uid(e: Event) -> str:
    key = f"{e.title.lower()}|{e.date}|{e.start_time}|{e.building_code or e.location_text}"
    return hashlib.sha1(key.encode()).hexdigest()[:20] + "@polo.app"


def to_ics(events: list[Event], now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Polo//Capture//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for e in events:
        if not e.date:
            continue
        start, end = event_times(e)
        lines += ["BEGIN:VEVENT", f"UID:{uid(e)}", f"DTSTAMP:{stamp}"]
        if isinstance(start, datetime):
            lines += [f"DTSTART:{start:%Y%m%dT%H%M%SZ}", f"DTEND:{end:%Y%m%dT%H%M%SZ}"]
        else:
            lines += [f"DTSTART;VALUE=DATE:{start:%Y%m%d}", f"DTEND;VALUE=DATE:{end:%Y%m%d}"]
        lines.append(f"SUMMARY:{_escape(e.title)}")
        if loc := location_line(e):
            lines.append(f"LOCATION:{_escape(loc)}")
        lines.append(f"DESCRIPTION:{_escape(_description(e))}")
        if e.link and e.link.startswith("http"):
            lines.append(f"URL:{e.link}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"


def google_calendar_url(e: Event) -> str | None:
    if not e.date:
        return None
    start, end = event_times(e)
    fmt = "%Y%m%dT%H%M%SZ" if isinstance(start, datetime) else "%Y%m%d"
    params = {
        "action": "TEMPLATE",
        "text": e.title,
        "dates": f"{start.strftime(fmt)}/{end.strftime(fmt)}",
        "details": _description(e),
    }
    if loc := location_line(e):
        params["location"] = loc
    return "https://calendar.google.com/calendar/render?" + urlencode(params)
