# Polo

Snap any poster and it's in your calendar, and on everyone's map.

This repo starts with validation step 1: a web prototype that turns a poster photo or pasted text into calendar events. It is laid out so the same code becomes the production extraction service and the eval harness.

```
extraction/   FastAPI service: image/text -> Claude (structured output) -> normalize -> .ics
  polo_extract/
    schema.py      fixed JSON schema with per-field confidence
    llm.py         model call, latency and cost tracking
    normalize.py   relative dates, UBC building nicknames, review flags
    ics.py         .ics and Google Calendar links
    qr.py          QR code decoding (OpenCV)
    links.py       safe fetch of linked event pages, schema.org Event parsing
    enrich.py      QR + links -> extra context for the model
    api.py         /api/extract, /api/ics, /api/log, serves web/
    data/ubc_buildings.csv
web/          prototype page (served by the API)
eval/         labeled posters and scoring
scripts/      pilot analytics
app/          Expo app (later)
```

## Run it

Needs [uv](https://docs.astral.sh/uv/) and at least one model provider. [docs/SETUP.md](docs/SETUP.md) covers getting keys (Claude, plus free options: Ollama, Gemini, Groq, OpenRouter) and comparing models.

```sh
uv sync
cp .env.example .env                 # add ANTHROPIC_API_KEY
uv run --env-file .env uvicorn polo_extract.api:app --reload --app-dir extraction
```

Open http://localhost:8000. On a phone on the same Wi-Fi, add `--host 0.0.0.0` and open your laptop's IP.

```sh
uv run pytest
```

All settings are listed with comments in `.env.example`. `POLO_DEV=1` adds a model picker and a compare-all mode to the page; set it to 0 before testers use it.

## Eval

Labels live in `eval/labels/*.jsonl`, one poster per line. Gold fields: `title`, `date`, `start_time`, `end_time`, `building_code`, `room`, `free_food`. A non-event has `"events": []`.

```sh
uv run --env-file .env python -m polo_eval --labels eval/labels/examples.jsonl
uv run --env-file .env python -m polo_eval --model claude-haiku-5-5        # compare cost vs accuracy
uv run --env-file .env python -m polo_eval --no-links                       # ablation: without QR/page reading
uv run python -m polo_eval --rescore eval/runs/<run>                       # rescore without API calls
uv run --env-file .env python -m polo_eval.draft                           # prefill labels for eval/posters/*
```

Each run writes `eval/runs/<stamp>-<model>-<effort>/` with predictions, `metrics.json` and `report.md`. Metrics: event precision/recall, per-field accuracy (dates separate), zero-edit rate, confidence calibration (ECE, Brier), whether review flags catch the errors, latency p50/p95, cost per scan.

`examples.jsonl` is a handful of synthetic text seeds so the harness runs today. Real numbers need real posters: put photos in `eval/posters/`, run `draft`, then correct every field by hand before moving lines into `labels/posters.jsonl`. Drafts anchor you toward the model's answer, so check against the poster, not the draft.

## Pilot

The page logs to `extraction/logs/`: captures, visibility choices, saves, and which fields people edited. `uv run python scripts/pilot_stats.py` prints the pass-bar numbers (share of testers with 3+ saved captures, share saved as public, most-edited fields, cost).

## Notes

- Times are converted to UTC in .ics files using the system tz database. BC's offset rules change from November 2026, so keep tzdata current on whatever hosts this.
- `ubc_buildings.csv` is a seed. Rows with `code_verified=n` use made-up codes for places without an official one; check them against UBC's building list before relying on them.
