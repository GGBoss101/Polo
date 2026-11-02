import re
import statistics
from dataclasses import dataclass, field
from difflib import SequenceMatcher

FIELDS = ["title", "date", "start_time", "end_time", "building_code", "room", "free_food"]
CRITICAL = ["title", "date", "start_time", "building_code"]
CONF_FIELD = {"title": "title", "date": "date", "start_time": "start_time",
              "end_time": "end_time", "building_code": "location"}
TITLE_OK = 0.8
MATCH_MIN = 0.5


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()


def title_sim(a: str | None, b: str | None) -> float:
    a, b = _clean(a), _clean(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return max(0.9, SequenceMatcher(None, a, b).ratio())
    return SequenceMatcher(None, a, b).ratio()


def field_correct(f: str, pred: dict, gold: dict) -> bool:
    p, g = pred.get(f), gold.get(f)
    if f == "title":
        return title_sim(p, g) >= TITLE_OK
    if f == "room":
        return (p or "").upper().replace(" ", "") == (g or "").upper().replace(" ", "")
    if f == "free_food":
        return bool(p) == bool(g)
    return (p or None) == (g or None)


def match_events(preds: list[dict], golds: list[dict]) -> list[tuple[int, int]]:
    scored = []
    for i, p in enumerate(preds):
        for j, g in enumerate(golds):
            s = title_sim(p.get("title"), g.get("title"))
            if p.get("date") and p.get("date") == g.get("date"):
                s += 0.25
            if s >= MATCH_MIN:
                scored.append((s, i, j))
    used_p, used_g, pairs = set(), set(), []
    for _, i, j in sorted(scored, reverse=True):
        if i not in used_p and j not in used_g:
            used_p.add(i)
            used_g.add(j)
            pairs.append((i, j))
    return pairs


def ece(points: list[tuple[float, bool]], bins: int = 10) -> float | None:
    if not points:
        return None
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        bucket = [(c, ok) for c, ok in points if lo <= c < hi or (b == bins - 1 and c == 1.0)]
        if bucket:
            conf = sum(c for c, _ in bucket) / len(bucket)
            acc = sum(ok for _, ok in bucket) / len(bucket)
            total += len(bucket) / len(points) * abs(conf - acc)
    return round(total, 4)


def brier(points: list[tuple[float, bool]]) -> float | None:
    if not points:
        return None
    return round(sum((c - ok) ** 2 for c, ok in points) / len(points), 4)


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


@dataclass
class Report:
    n_items: int = 0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    field_hits: dict = field(default_factory=lambda: {f: 0 for f in FIELDS})
    critical_hits: int = 0
    source_correct: int = 0
    calib: dict = field(default_factory=lambda: {f: [] for f in CONF_FIELD})
    review_tp: int = 0
    review_fp: int = 0
    review_fn: int = 0
    latencies: list = field(default_factory=list)
    costs: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    mistakes: list = field(default_factory=list)

    def add(self, label: dict, pred: dict) -> None:
        self.n_items += 1
        if "error" in pred:
            self.errors.append({"id": label["id"], "error": pred["error"]})
            self.fn += len(label["events"])
            return
        golds, preds = label["events"], pred["events"]
        self.source_correct += pred.get("is_event_source", True) == bool(golds)
        self.latencies.append(pred["meta"]["latency_ms"])
        if pred["meta"].get("cost_usd") is not None:
            self.costs.append(pred["meta"]["cost_usd"])

        pairs = match_events(preds, golds)
        self.tp += len(pairs)
        self.fp += len(preds) - len(pairs)
        self.fn += len(golds) - len(pairs)

        for i, j in pairs:
            p, g = preds[i], golds[j]
            ok = {f: field_correct(f, p, g) for f in FIELDS}
            for f, hit in ok.items():
                self.field_hits[f] += hit
            self.critical_hits += all(ok[f] for f in CRITICAL)
            flagged = set(p.get("needs_review", []))
            for f, cf in CONF_FIELD.items():
                c = p.get("confidence", {}).get(cf)
                if c is not None:
                    self.calib[f].append((float(c), ok[f]))
                is_flagged = cf in flagged or f in flagged
                if not ok[f] and is_flagged:
                    self.review_tp += 1
                elif not ok[f]:
                    self.review_fn += 1
                elif is_flagged:
                    self.review_fp += 1
            wrong = [f for f in FIELDS if not ok[f]]
            if wrong:
                self.mistakes.append({"id": label["id"], "fields": {f: {"pred": p.get(f), "gold": g.get(f)} for f in wrong}})

    def metrics(self) -> dict:
        prec, rec = _rate(self.tp, self.tp + self.fp), _rate(self.tp, self.tp + self.fn)
        f1 = round(2 * prec * rec / (prec + rec), 4) if prec and rec else None
        all_points = [pt for pts in self.calib.values() for pt in pts]
        return {
            "items": self.n_items,
            "errors": len(self.errors),
            "events": {"precision": prec, "recall": rec, "f1": f1, "tp": self.tp, "fp": self.fp, "fn": self.fn},
            "is_event_source_accuracy": _rate(self.source_correct, self.n_items - len(self.errors)),
            "field_accuracy": {f: _rate(h, self.tp) for f, h in self.field_hits.items()},
            "zero_edit_rate": _rate(self.critical_hits, self.tp),
            "calibration": {
                "ece": ece(all_points),
                "brier": brier(all_points),
                "per_field_ece": {f: ece(pts) for f, pts in self.calib.items()},
            },
            "review_flags": {
                "precision": _rate(self.review_tp, self.review_tp + self.review_fp),
                "recall": _rate(self.review_tp, self.review_tp + self.review_fn),
            },
            "latency_ms": {
                "p50": _pct(self.latencies, 0.5),
                "p95": _pct(self.latencies, 0.95),
                "mean": round(statistics.mean(self.latencies)) if self.latencies else None,
            },
            "cost_usd": {
                "per_scan": round(statistics.mean(self.costs), 6) if self.costs else None,
                "total": round(sum(self.costs), 4) if self.costs else None,
            },
        }
