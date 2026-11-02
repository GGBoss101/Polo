"""Pre-fill labels for new poster images. Correct every field by hand before moving lines into posters.jsonl."""
import argparse
import json
from datetime import date
from pathlib import Path

from .run import EVAL_DIR, load_labels, predict

FIELDS = ["title", "date", "start_time", "end_time", "building_code", "room", "free_food"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--posters", type=Path, default=EVAL_DIR / "posters")
    ap.add_argument("--labels", type=Path, default=EVAL_DIR / "labels" / "posters.jsonl")
    ap.add_argument("--out", type=Path, default=EVAL_DIR / "labels" / "drafts.jsonl")
    ap.add_argument("--captured-on", default=date.today().isoformat())
    ap.add_argument("--model", default="claude-opus-5-5")
    args = ap.parse_args(argv)

    done = set()
    for f in (args.labels, args.out):
        if f.exists():
            done |= {l.get("image") for l in load_labels(f)}
    images = sorted(p for p in args.posters.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    todo = [p for p in images if f"posters/{p.name}" not in done]
    with args.out.open("a") as f:
        for i, p in enumerate(todo, 1):
            label = {"id": p.stem, "image": f"posters/{p.name}", "captured_on": args.captured_on, "source": "photo"}
            pred = predict({**label, "events": []}, args.model, "medium")
            events = [{k: e.get(k) for k in FIELDS} for e in pred.get("events", [])]
            f.write(json.dumps({**label, "events": events, "status": "draft"}) + "\n")
            print(f"[{i}/{len(todo)}] {p.name}: {len(events)} events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
