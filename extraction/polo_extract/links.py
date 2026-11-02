import ipaddress
import json
import re
import socket
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

SKIP_DOMAINS = ("instagram.com", "facebook.com", "fb.me", "tiktok.com", "threads.net", "x.com", "twitter.com")
MAX_BYTES = 1_500_000
MAX_TEXT = 4000
TIMEOUT = 6.0
URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]+", re.I)
HEADERS = {"User-Agent": "PoloBot/0.1 (event link preview; UBC student project)"}


@dataclass
class LinkedPage:
    url: str
    final_url: str
    title: str | None = None
    description: str | None = None
    events: list[dict] = field(default_factory=list)
    text: str = ""


@dataclass
class LinkResult:
    url: str
    page: LinkedPage | None = None
    skipped: str | None = None


def find_urls(text: str | None) -> list[str]:
    if not text:
        return []
    out = []
    for m in URL_RE.findall(text):
        url = m.rstrip(".,;:!?")
        if url.lower().startswith("www."):
            url = "https://" + url
        if url not in out:
            out.append(url)
    return out


def skip_reason(url: str) -> str | None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return "not a web link"
    host = p.hostname.lower()
    if any(host == d or host.endswith("." + d) for d in SKIP_DOMAINS):
        return "social media pages aren't read"
    return None


def _host_problem(host: str) -> str | None:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return "couldn't find that website"
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            return "not a public address"
    return None


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self.jsonld: list[str] = []
        self.chunks: list[str] = []
        self._stack: list[str] = []
        self._jsonld = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta[key] = a["content"]
        if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._jsonld = True
            self.jsonld.append("")
        if tag not in ("meta", "link", "br", "img", "input", "hr"):
            self._stack.append(tag)

    def handle_endtag(self, tag):
        if tag == "script":
            self._jsonld = False
        if tag in self._stack:
            while self._stack and self._stack.pop() != tag:
                pass

    def handle_data(self, data):
        if self._jsonld:
            self.jsonld[-1] += data
            return
        current = self._stack[-1] if self._stack else ""
        if current == "title":
            self.title += data
        elif current not in ("script", "style", "noscript", "svg", "template") and data.strip():
            self.chunks.append(data.strip())


def _event_objects(node) -> list[dict]:
    found = []
    if isinstance(node, list):
        for n in node:
            found += _event_objects(n)
    elif isinstance(node, dict):
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        if any(isinstance(t, str) and t.endswith("Event") for t in types):
            keep = ("name", "startDate", "endDate", "location", "description", "organizer", "offers", "url", "eventStatus")
            found.append({k: node[k] for k in keep if k in node})
        for key in ("@graph", "mainEntity", "itemListElement", "item"):
            if key in node:
                found += _event_objects(node[key])
    return found


def parse_html(html: str, url: str, final_url: str) -> LinkedPage:
    p = _Parser()
    try:
        p.feed(html)
    except Exception:
        pass
    events = []
    for raw in p.jsonld:
        try:
            events += _event_objects(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue
    text = re.sub(r"\s+", " ", " ".join(p.chunks))[:MAX_TEXT]
    return LinkedPage(
        url=url,
        final_url=final_url,
        title=(p.meta.get("og:title") or p.title or "").strip() or None,
        description=(p.meta.get("og:description") or p.meta.get("description") or "").strip() or None,
        events=events[:5],
        text=text,
    )


_cache: dict[str, tuple[float, "LinkResult"]] = {}
CACHE_SECONDS = 600


def fetch(url: str) -> LinkResult:
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    result = _fetch(url)
    _cache[url] = (time.time(), result)
    return result


def _fetch(url: str) -> LinkResult:
    if reason := skip_reason(url):
        return LinkResult(url, skipped=reason)
    current = url
    with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=False) as client:
        for _ in range(5):
            if reason := skip_reason(current):
                return LinkResult(url, skipped=reason)
            if problem := _host_problem(urlparse(current).hostname):
                return LinkResult(url, skipped=problem)
            try:
                with client.stream("GET", current) as r:
                    if r.is_redirect and "location" in r.headers:
                        current = urljoin(current, r.headers["location"])
                        continue
                    if r.status_code >= 400:
                        return LinkResult(url, skipped=f"page returned {r.status_code}")
                    ctype = r.headers.get("content-type", "")
                    if "html" not in ctype:
                        return LinkResult(url, skipped="not a web page")
                    body = b""
                    for chunk in r.iter_bytes():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            break
                    html = body.decode(r.encoding or "utf-8", errors="replace")
                    return LinkResult(url, page=parse_html(html, url, current))
            except httpx.HTTPError as exc:
                return LinkResult(url, skipped=f"couldn't load ({type(exc).__name__})")
    return LinkResult(url, skipped="too many redirects")


def as_context(results: list[LinkResult]) -> str | None:
    blocks = []
    for r in results:
        if not r.page:
            continue
        p = r.page
        parts = [f'<linked_page url="{p.final_url}">']
        if p.title:
            parts.append(f"Title: {p.title}")
        if p.description:
            parts.append(f"Description: {p.description}")
        if p.events:
            parts.append("Structured event data: " + json.dumps(p.events, ensure_ascii=False)[:3000])
        if p.text:
            parts.append(f"Page text: {p.text}")
        parts.append("</linked_page>")
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks) or None


if __name__ == "__main__":
    import sys

    for u in sys.argv[1:]:
        r = fetch(u)
        print(f"\n{u}")
        if not r.page:
            print(f"  not read: {r.skipped}")
            continue
        print(f"  final url:   {r.page.final_url}")
        print(f"  title:       {r.page.title}")
        print(f"  description: {r.page.description}")
        print(f"  event data:  {json.dumps(r.page.events, indent=2) if r.page.events else 'none'}")
        print(f"  text ({len(r.page.text)} chars): {r.page.text[:500]}")
