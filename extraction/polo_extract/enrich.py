import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import links
from .qr import decode_qr

FETCH_LINKS = os.environ.get("POLO_FETCH_LINKS", "1") == "1"
MAX_LINKS = 2


@dataclass
class Enrichment:
    qr: list[str] = field(default_factory=list)
    results: list[links.LinkResult] = field(default_factory=list)
    origin: dict[str, str] = field(default_factory=dict)
    ms: int = 0

    @property
    def context(self) -> str | None:
        parts = []
        qr_text = [q for q in self.qr if not links.find_urls(q)]
        if qr_text:
            parts.append("QR code text: " + " | ".join(qr_text))
        if pages := links.as_context(self.results):
            parts.append(pages)
        return "\n\n".join(parts) or None

    @property
    def best_link(self) -> str | None:
        for r in self.results:
            if r.page:
                return r.page.final_url
        for q in self.qr:
            if urls := links.find_urls(q):
                return urls[0]
        return None

    def sources(self) -> list[dict]:
        out = [{"url": r.url, "from": self.origin.get(r.url, "text"), "read": r.page is not None,
                "title": r.page.title if r.page else None, "note": r.skipped} for r in self.results]
        seen = {r.url for r in self.results}
        for q in self.qr:
            if q not in seen and not links.find_urls(q):
                out.append({"url": None, "from": "qr", "read": False, "title": q[:80], "note": "QR text"})
        return out


def enrich(image: bytes | None, text: str | None, fetch_links: bool = FETCH_LINKS) -> Enrichment:
    start = time.perf_counter()
    e = Enrichment()
    if image is not None:
        e.qr = decode_qr(image)

    urls: list[str] = []
    for source, candidates in (("qr", [u for q in e.qr for u in links.find_urls(q)]), ("text", links.find_urls(text))):
        for u in candidates:
            if u not in urls:
                urls.append(u)
                e.origin[u] = source

    if fetch_links and urls:
        todo = urls[:MAX_LINKS]
        with ThreadPoolExecutor(len(todo)) as pool:
            e.results = list(pool.map(links.fetch, todo))
    else:
        e.results = [links.LinkResult(u, skipped="link reading is off") for u in urls[:MAX_LINKS]]
    e.ms = int((time.perf_counter() - start) * 1000)
    return e


def fill_links(events: list, e: Enrichment) -> None:
    if not (link := e.best_link):
        return
    for ev in events:
        if not (ev.link or "").startswith("http"):
            ev.link = link
