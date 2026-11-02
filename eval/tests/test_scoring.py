from polo_eval.scoring import Report, ece, match_events, title_sim


def gold(**kw):
    base = {"title": "Board Game Night", "date": "2026-11-07", "start_time": "18:00", "end_time": "21:00",
            "building_code": "ICCS", "room": "X150", "free_food": True}
    return {**base, **kw}


def pred(**kw):
    conf = kw.pop("confidence", {"title": 0.9, "date": 0.9, "start_time": 0.9, "end_time": 0.9, "location": 0.9})
    return {**gold(), "confidence": conf, "needs_review": kw.pop("needs_review", []), **kw}


META = {"latency_ms": 1000, "cost_usd": 0.01}


def test_title_sim():
    assert title_sim("CS Club Board Game Night", "Board Game Night") >= 0.9
    assert title_sim("Hiking meeting", "Diwali Night") < 0.5


def test_match_events_greedy():
    preds = [pred(title="Review", date="2026-11-11"), pred(title="Review", date="2026-11-09")]
    golds = [gold(title="Review", date="2026-11-09"), gold(title="Review", date="2026-11-11")]
    assert sorted(match_events(preds, golds)) == [(0, 1), (1, 0)]


def test_ece():
    assert ece([(0.9, True)] * 9 + [(0.9, False)]) == 0.0
    assert ece([(1.0, False)]) == 1.0


def test_report_perfect_and_errors():
    r = Report()
    r.add({"id": "a", "events": [gold()]}, {"events": [pred()], "is_event_source": True, "meta": META})
    r.add({"id": "b", "events": [gold()]}, {"events": [pred(date="2026-11-08", needs_review=["date"])],
                                            "is_event_source": True, "meta": META})
    r.add({"id": "c", "events": []}, {"events": [], "is_event_source": False, "meta": META})
    r.add({"id": "d", "events": [gold()]}, {"error": "boom"})
    m = r.metrics()
    assert m["events"]["tp"] == 2 and m["events"]["fn"] == 1 and m["events"]["fp"] == 0
    assert m["field_accuracy"]["date"] == 0.5
    assert m["zero_edit_rate"] == 0.5
    assert m["review_flags"]["recall"] == 1.0
    assert m["is_event_source_accuracy"] == 1.0
    assert m["errors"] == 1
    assert r.mistakes[0]["id"] == "b"


def test_false_positive_event():
    r = Report()
    r.add({"id": "x", "events": []}, {"events": [pred()], "is_event_source": True, "meta": META})
    m = r.metrics()
    assert m["events"]["fp"] == 1 and m["is_event_source_accuracy"] == 0.0
