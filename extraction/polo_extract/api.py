import json
import os
import time
import uuid
from collections import defaultdict, deque
from datetime import date, datetime, timezone
from pathlib import Path

import anthropic
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import llm
from .enrich import enrich, fill_links
from .qr import for_model
from .ics import google_calendar_url, to_ics
from .normalize import normalize
from .schema import Event

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
LOG_DIR = Path(os.environ.get("POLO_LOG_DIR", ROOT / "extraction" / "logs"))
SAVE_UPLOADS = os.environ.get("POLO_SAVE_UPLOADS") == "1"
DEV = os.environ.get("POLO_DEV") == "1"
RATE_LIMIT = int(os.environ.get("POLO_RATE_LIMIT_PER_HOUR", "40"))
MAX_BYTES = 15 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

app = FastAPI(title="Polo extraction")
_hits: dict[str, deque] = defaultdict(deque)


def _log(name: str, record: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now(timezone.utc).isoformat(), **record}
    with (LOG_DIR / name).open("a") as f:
        f.write(json.dumps(record) + "\n")


def _rate_limit(ip: str) -> None:
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(429, "Too many scans this hour, try again later")
    q.append(now)


def _with_links(e: Event) -> dict:
    return {**e.model_dump(), "google_calendar_url": google_calendar_url(e)}


@app.post("/api/extract")
async def extract(
    request: Request,
    image: UploadFile | None = File(None),
    text: str | None = Form(None),
    captured_on: str | None = Form(None),
    session: str | None = Form(None),
    source: str | None = Form(None),
    model: str | None = Form(None),
):
    chosen = model if DEV and model else llm.DEFAULT_MODEL
    if not llm.is_known_model(chosen):
        raise HTTPException(400, f"Unknown model {chosen}")
    _rate_limit(request.client.host if request.client else "unknown")
    data = None
    media_type = "image/jpeg"
    if image is not None and image.filename:
        if image.content_type not in IMAGE_TYPES:
            raise HTTPException(415, f"Unsupported image type {image.content_type}")
        data = await image.read()
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "Image too large")
        media_type = image.content_type
    text = (text or "").strip() or None
    if data is None and text is None:
        raise HTTPException(400, "Send a photo or some text")

    try:
        today = date.fromisoformat(captured_on) if captured_on else date.today()
    except ValueError:
        raise HTTPException(400, "captured_on must be YYYY-MM-DD")

    extra = await run_in_threadpool(enrich, data, text)
    model_image, model_type = (await run_in_threadpool(for_model, data, media_type)) if data else (None, media_type)
    try:
        result = await run_in_threadpool(
            llm.extract, image=model_image, media_type=model_type, text=text, captured_on=today, model=chosen,
            context=extra.context,
        )
    except llm.NotConfigured as exc:
        raise HTTPException(503, f"Not set up: {exc}")
    except RuntimeError as exc:
        raise HTTPException(422, str(exc))
    except anthropic.RateLimitError:
        raise HTTPException(503, "Busy right now, try again in a minute")
    except (anthropic.APIConnectionError, anthropic.InternalServerError):
        raise HTTPException(503, "Couldn't reach the extraction model, try again")
    except anthropic.AnthropicError as exc:
        raise HTTPException(502, f"Model error: {exc}")

    events = [normalize(e, today) for e in result.extraction.events]
    fill_links(events, extra)
    capture_id = uuid.uuid4().hex[:12]

    if SAVE_UPLOADS and data is not None:
        up = LOG_DIR / "uploads"
        up.mkdir(parents=True, exist_ok=True)
        (up / f"{capture_id}.{media_type.split('/')[1]}").write_bytes(data)

    meta = {
        "model": result.model,
        "latency_ms": result.latency_ms,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": result.cost_usd,
        "enrich_ms": extra.ms,
    }
    _log("captures.jsonl", {
        "capture_id": capture_id,
        "session": session,
        "source": source or ("image" if data else "text"),
        "dev": DEV,
        "is_event_source": result.extraction.is_event_source,
        "n_events": len(events),
        "events": [e.model_dump() for e in events],
        "sources": extra.sources(),
        **meta,
    })
    return {
        "capture_id": capture_id,
        "is_event_source": result.extraction.is_event_source,
        "events": [_with_links(e) for e in events],
        "sources": extra.sources(),
        "meta": meta,
    }


class IcsRequest(BaseModel):
    events: list[Event]
    capture_id: str | None = None
    session: str | None = None


@app.post("/api/ics")
def ics(req: IcsRequest):
    events = [e for e in req.events if e.date]
    if not events:
        raise HTTPException(400, "No events with a date")
    _log("activity.jsonl", {"type": "ics_download", "capture_id": req.capture_id,
                            "session": req.session, "n_events": len(events)})
    return Response(
        to_ics(events),
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="polo-events.ics"'},
    )


class Activity(BaseModel):
    type: str
    session: str | None = None
    capture_id: str | None = None
    data: dict = {}


@app.post("/api/log", status_code=204)
def log_activity(a: Activity):
    _log("activity.jsonl", a.model_dump())


@app.get("/api/config")
def config():
    models = llm.available_models() if DEV else []
    return {"dev": DEV, "default_model": llm.DEFAULT_MODEL, "models": models}


@app.get("/api/health")
def health():
    return {"ok": True, "model": llm.DEFAULT_MODEL}


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")
