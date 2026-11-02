import cv2
import httpx
import pytest

from polo_extract import enrich as enrich_mod
from polo_extract import links
from polo_extract.qr import decode_qr

EVENT_PAGE = """<html><head><title>Board Game Night | UBC Events</title>
<meta property="og:description" content="Games and pizza with the CS Club">
<script type="application/ld+json">{"@context": "https://schema.org", "@graph": [{"@type": "Event",
 "name": "Board Game Night", "startDate": "2026-11-07T18:00:00-07:00", "endDate": "2026-11-07T21:00:00-07:00",
 "location": {"@type": "Place", "name": "ICICS X150"}}]}</script>
<script>var tracking = "ignore me";</script><style>.x{}</style></head>
<body><h1>Board Game Night</h1><p>Room X150. Free pizza.</p></body></html>"""


def qr_png(text: str) -> bytes:
    img = cv2.QRCodeEncoder.create().encode(text)
    img = cv2.resize(img, None, fx=10, fy=10, interpolation=cv2.INTER_NEAREST)
    img = cv2.copyMakeBorder(img, 60, 60, 60, 60, cv2.BORDER_CONSTANT, value=255)
    return cv2.imencode(".png", img)[1].tobytes()


def test_decode_qr():
    assert decode_qr(qr_png("https://events.ubc.ca/event/123")) == ["https://events.ubc.ca/event/123"]
    assert decode_qr(b"not an image") == []


def test_find_urls():
    text = "Sign up at www.ubccs.club/games. More: https://events.ubc.ca/e/1, or @ubccsclub"
    assert links.find_urls(text) == ["https://www.ubccs.club/games", "https://events.ubc.ca/e/1"]


@pytest.mark.parametrize("url,reason", [
    ("https://www.instagram.com/p/abc", "social media"),
    ("https://instagram.com/ubccsclub", "social media"),
    ("ftp://example.com/x", "not a web link"),
    ("https://events.ubc.ca/e/1", None),
])
def test_skip_reason(url, reason):
    got = links.skip_reason(url)
    assert (got is None) if reason is None else reason in got


def test_private_addresses_blocked():
    links._cache.clear()
    assert links.fetch("https://no-such-host.invalid/").skipped == "couldn't find that website"
    assert links.fetch("http://localhost:8000/").skipped == "not a public address"
    assert links.fetch("http://10.0.0.5/admin").skipped == "not a public address"
    assert links.fetch("http://169.254.169.254/latest/meta-data").skipped == "not a public address"


def test_parse_html():
    page = links.parse_html(EVENT_PAGE, "https://e.ubc.ca/1", "https://e.ubc.ca/1")
    assert page.title == "Board Game Night | UBC Events"
    assert page.description == "Games and pizza with the CS Club"
    assert page.events[0]["startDate"].startswith("2026-11-07T18:00")
    assert "Free pizza" in page.text and "ignore me" not in page.text


@pytest.fixture
def fake_web(monkeypatch):
    links._cache.clear()
    monkeypatch.setattr(links, "_host_problem", lambda host: "not a public address" if host == "internal.example" else None)

    def handler(request: httpx.Request):
        if request.url.host == "short.link":
            return httpx.Response(302, headers={"location": "https://events.ubc.ca/e/1"})
        if request.url.host == "evil.link":
            return httpx.Response(302, headers={"location": "http://internal.example/secret"})
        if request.url.host == "big.file":
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=EVENT_PAGE)

    real_client = httpx.Client
    monkeypatch.setattr(links.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))


def test_fetch_follows_redirects(fake_web):
    r = links.fetch("https://short.link/x")
    assert r.page and r.page.final_url == "https://events.ubc.ca/e/1"


def test_fetch_blocks_redirect_to_private(fake_web):
    assert links.fetch("https://evil.link/x").skipped == "not a public address"


def test_fetch_non_html(fake_web):
    assert links.fetch("https://big.file/x.pdf").skipped == "not a web page"


def test_enrich_from_qr(fake_web):
    e = enrich_mod.enrich(qr_png("https://short.link/x"), "also see https://instagram.com/p/1")
    assert e.qr == ["https://short.link/x"]
    assert [s["from"] for s in e.sources()] == ["qr", "text"]
    assert e.sources()[0]["read"] and e.sources()[1]["note"].startswith("social media")
    assert e.best_link == "https://events.ubc.ca/e/1"
    assert '<linked_page url="https://events.ubc.ca/e/1">' in e.context
    assert "startDate" in e.context


def test_enrich_qr_text_and_off_switch(fake_web):
    e = enrich_mod.enrich(qr_png("WIFI:S:UBCvisitor;;"), None)
    assert "QR code text: WIFI" in e.context
    e = enrich_mod.enrich(None, "https://events.ubc.ca/e/1", fetch_links=False)
    assert e.context is None and e.sources()[0]["note"] == "link reading is off"


def test_qr_with_logo_on_large_photo():
    import numpy as np
    from polo_extract.qr import for_model

    params = cv2.QRCodeEncoder.Params()
    params.correction_level = cv2.QRCodeEncoder_CORRECT_LEVEL_H
    q = cv2.QRCodeEncoder.create(params).encode("https://www.showpass.com/icebreaker-2026/")
    q = cv2.resize(q, (150, 150), interpolation=cv2.INTER_NEAREST)
    cv2.rectangle(q, (55, 55), (95, 95), 90, -1)
    page = np.full((2800, 2100), 225, np.uint8)
    page[2400:2550, 1700:1850] = q
    photo = cv2.imencode(".jpg", cv2.GaussianBlur(page, (5, 5), 0.8))[1].tobytes()
    assert decode_qr(photo) == ["https://www.showpass.com/icebreaker-2026/"]

    small, media_type = for_model(photo, "image/png")
    img = cv2.imdecode(np.frombuffer(small, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert max(img.shape) == 1600 and media_type == "image/jpeg"
