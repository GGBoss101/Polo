"""Summarize prototype pilot logs against the validation pass bar."""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

PASS_CAPTURES = 3


def read(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []


def main(log_dir: str = "extraction/logs") -> None:
    d = Path(log_dir)
    captures, activity = read(d / "captures.jsonl"), read(d / "activity.jsonl")
    saves = [a for a in activity if a["type"] == "save"]

    per_session = Counter(c["session"] for c in captures if c.get("n_events"))
    saved_by_session = defaultdict(set)
    for s in saves:
        saved_by_session[s["session"]].add(s["capture_id"])
    sessions = set(per_session) | set(saved_by_session)
    passing = [s for s in sessions if len(saved_by_session[s]) >= PASS_CAPTURES]

    vis = Counter(s["data"].get("visibility", "private") for s in saves)
    edited = Counter(f for s in saves for f in s["data"].get("edited", []))
    zero_edit = sum(1 for s in saves if not s["data"].get("edited"))
    by_source = Counter(c["source"] for c in captures)
    costs = [c["cost_usd"] for c in captures if c.get("cost_usd") is not None]

    print(f"Sessions: {len(sessions)}")
    print(f"Captures with events: {sum(per_session.values())}  by source: {dict(by_source)}")
    print(f"Saved events: {len(saves)}  ({zero_edit} saved with no edits)")
    print(f"Sessions with {PASS_CAPTURES}+ saved captures: {len(passing)}/{len(sessions)}"
          f" ({len(passing) / len(sessions):.0%})" if sessions else "")
    if saves:
        print(f"Saved as public: {vis['public']}/{len(saves)} ({vis['public'] / len(saves):.0%})")
    print(f"Most edited fields: {edited.most_common(5)}")
    if costs:
        print(f"Model cost: ${sum(costs):.2f} total, ${sum(costs) / len(costs):.4f} per capture")


if __name__ == "__main__":
    main(*sys.argv[1:])
