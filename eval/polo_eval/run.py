import argparse
import json
import mimetypes
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

from polo_extract import llm
from polo_extract.enrich import Enrichment, enrich, fill_links
from polo_extract.normalize import normalize
from polo_extract.qr import for_model

from .scoring import Report

EVAL_DIR = Path(__file__).resolve().parents[1]


def load_labels(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip() and not l.startswith("//")]


def predict(label: dict, model: str, effort: str, use_links: bool = True) -> dict:
    captured = date.fromisoformat(label["captured_on"])
    image = media_type = None
    if label.get("image"):
        p = EVAL_DIR / label["image"]
        image = p.read_bytes()
        media_type = mimetypes.guess_type(p.name)[0] or "image/jpeg"
    extra = enrich(image, label.get("text")) if use_links else Enrichment()
    if image is not None:
        image, media_type = for_model(image, media_type or "image/jpeg")
    try:
        r = llm.extract(image=image, media_type=media_type or "image/jpeg", text=label.get("text"),
                        captured_on=captured, model=model, effort=effort, context=extra.context)
    except Exception as exc:
        return {"id": label["id"], "error": f"{type(exc).__name__}: {exc}"}
    events = [normalize(e, captured) for e in r.extraction.events]
    fill_links(events, extra)
    return {
        "id": label["id"],
        "is_event_source": r.extraction.is_event_source,
        "sources": extra.sources(),
        "events": [e.model_dump() for e in events],
        "meta": {"model": r.model, "latency_ms": r.latency_ms, "input_tokens": r.input_tokens,
                 "output_tokens": r.output_tokens, "cost_usd": r.cost_usd},
    }


def write_report(out: Path, m: dict, args, report: Report) -> None:
    fa = m["field_accuracy"]
    lines = [
        f"# Eval run {out.name}",
        "",
        f"Model `{args.model}`, effort `{args.effort}`, QR/link reading {'off' if getattr(args, 'no_links', False) else 'on'}, {m['items']} items, {m['errors']} errors.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Event precision / recall / F1 | {m['events']['precision']} / {m['events']['recall']} / {m['events']['f1']} |",
        f"| Zero-edit rate (title, date, start, building all right) | {m['zero_edit_rate']} |",
        f"| Date accuracy | {fa['date']} |",
        f"| Start time accuracy | {fa['start_time']} |",
        f"| Building accuracy | {fa['building_code']} |",
        f"| Title accuracy | {fa['title']} |",
        f"| End time / room / free food | {fa['end_time']} / {fa['room']} / {fa['free_food']} |",
        f"| Calibration ECE / Brier | {m['calibration']['ece']} / {m['calibration']['brier']} |",
        f"| Review flag precision / recall | {m['review_flags']['precision']} / {m['review_flags']['recall']} |",
        f"| Latency p50 / p95 (ms) | {m['latency_ms']['p50']} / {m['latency_ms']['p95']} |",
        f"| Cost per scan / total (USD) | {m['cost_usd']['per_scan']} / {m['cost_usd']['total']} |",
        "",
        "## Mistakes",
        "",
    ]
    for mk in report.mistakes[:50]:
        detail = "; ".join(f"{f}: got `{v['pred']}`, want `{v['gold']}`" for f, v in mk["fields"].items())
        lines.append(f"- **{mk['id']}** {detail}")
    for e in report.errors:
        lines.append(f"- **{e['id']}** error: {e['error']}")
    (out / "report.md").write_text("\n".join(lines) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Score Polo extraction against labeled posters")
    ap.add_argument("--labels", type=Path, default=EVAL_DIR / "labels" / "posters.jsonl")
    ap.add_argument("--model", default=llm.DEFAULT_MODEL)
    ap.add_argument("--effort", default=llm.DEFAULT_EFFORT)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-links", action="store_true", help="Skip QR/link page reading, to measure what it adds")
    ap.add_argument("--rescore", type=Path, help="Score an existing run's predictions.jsonl without calling the API")
    args = ap.parse_args(argv)

    labels = load_labels(args.labels)[: args.limit]
    if args.rescore:
        out = args.rescore
        by_id = {p["id"]: p for p in map(json.loads, (out / "predictions.jsonl").read_text().splitlines())}
        preds = [by_id[l["id"]] for l in labels if l["id"] in by_id]
        labels = [l for l in labels if l["id"] in by_id]
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        suffix = "-nolinks" if args.no_links else ""
        out = EVAL_DIR / "runs" / f"{stamp}-{args.model.replace(':', '_').replace('/', '_')}-{args.effort}{suffix}"
        out.mkdir(parents=True)
        with ThreadPoolExecutor(args.workers) as pool:
            preds = list(pool.map(lambda l: predict(l, args.model, args.effort, not args.no_links), labels))
        (out / "predictions.jsonl").write_text("".join(json.dumps(p) + "\n" for p in preds))

    report = Report()
    for label, pred in zip(labels, preds):
        report.add(label, pred)
    m = report.metrics()
    (out / "metrics.json").write_text(json.dumps(m, indent=2))
    write_report(out, m, args, report)
    print(json.dumps(m, indent=2))
    print(f"\nWrote {out / 'report.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
