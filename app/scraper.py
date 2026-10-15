"""Polite async website fetcher.

For each company domain it fetches the homepage, then follows up to a few
high-value internal links (contact / about / team). It respects robots.txt,
identifies itself with a clear User-Agent, caps page size, and limits
concurrency both globally and per domain.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

USER_AGENT = "LeadLensBot/1.0 (+lead enrichment; respects robots.txt)"
TIMEOUT = httpx.Timeout(10.0, connect=6.0)
MAX_BYTES = 1_500_000
MAX_EXTRA_PAGES = 3
GLOBAL_CONCURRENCY = 8
PER_DOMAIN_DELAY = 0.5  # seconds between requests to the same site

# Links worth following, ordered by how often they hold contact data.
PRIORITY_LINK_PATTERNS = [
    (re.compile(r"contact", re.I), 0),
    (re.compile(r"about|company|who-we-are|our-story", re.I), 1),
    (re.compile(r"team|leadership|staff|people|owner", re.I), 2),
]

DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")


def normalize_domain(raw: str) -> str | None:
    """Turn 'https://www.Acme.com/about?x=1' or 'acme.com' into 'acme.com'."""
    s = (raw or "").strip().strip('"\'').lower()
    if not s:
        return None
    if "@" in s and "/" not in s:  # an email address: use its domain
        s = s.split("@", 1)[1]
    if "://" not in s:
        s = "http://" + s
    host = urlparse(s).hostname or ""
    host = host.rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host if DOMAIN_RE.match(host) else None


@dataclass
class Fetched:
    status: int
    url: str
    text: str
    ok: bool


@dataclass
class Page:
    url: str
    html: str


@dataclass
class SiteResult:
    domain: str
    final_url: str | None = None
    https: bool = False
    pages: list[Page] = field(default_factory=list)
    error: str | None = None
    blocked_by_robots: bool = False

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "final_url": self.final_url,
            "https": self.https,
            "pages": [{"url": p.url, "html": p.html} for p in self.pages],
            "error": self.error,
            "blocked_by_robots": self.blocked_by_robots,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SiteResult":
        r = cls(domain=d["domain"], final_url=d.get("final_url"), https=d.get("https", False),
                error=d.get("error"), blocked_by_robots=d.get("blocked_by_robots", False))
        r.pages = [Page(**p) for p in d.get("pages", [])]
        return r


class Scraper:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._sem = asyncio.Semaphore(GLOBAL_CONCURRENCY)
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            max_redirects=5,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, url: str) -> "Fetched | None":
        """GET a page, reading at most MAX_BYTES. Returns None on network errors."""
        try:
            async with self._client.stream("GET", url) as resp:
                ctype = resp.headers.get("content-type", "").lower()
                is_text = (not ctype) or "html" in ctype or "text" in ctype
                body = b""
                if resp.status_code < 400 and is_text:
                    async for chunk in resp.aiter_bytes():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            break
                text = body.decode(resp.encoding or "utf-8", errors="replace")
                return Fetched(status=resp.status_code, url=str(resp.url), text=text,
                               ok=resp.status_code < 400 and is_text and bool(body))
        except (httpx.HTTPError, UnicodeError, ValueError, LookupError):
            return None

    async def _robots(self, base: str) -> RobotFileParser:
        rp = RobotFileParser()
        f = await self._get(urljoin(base, "/robots.txt"))
        rp.parse(f.text.splitlines() if f is not None and f.ok else [])  # missing = allow all
        return rp

    async def fetch_site(self, domain: str) -> SiteResult:
        result = SiteResult(domain=domain)
        async with self._sem:
            home = None
            for scheme in ("https", "http"):
                f = await self._get(f"{scheme}://{domain}/")
                if f is not None and f.ok:
                    home = f
                    break
            if home is None:
                result.error = "Site unreachable"
                return result

            final = home.url
            result.final_url = final
            result.https = final.startswith("https://")
            base = f"{urlparse(final).scheme}://{urlparse(final).netloc}"

            robots = await self._robots(base)
            if not robots.can_fetch(USER_AGENT, final):
                result.blocked_by_robots = True
                result.error = "Disallowed by robots.txt"
                return result

            result.pages.append(Page(url=final, html=home.text))

            for link in self._pick_links(home.text, final)[:MAX_EXTRA_PAGES]:
                if not robots.can_fetch(USER_AGENT, link):
                    continue
                await asyncio.sleep(PER_DOMAIN_DELAY)
                f = await self._get(link)
                if f is not None and f.ok:
                    result.pages.append(Page(url=f.url, html=f.text))
        return result

    @staticmethod
    def _pick_links(html: str, page_url: str) -> list[str]:
        """Rank same-site links by how likely they are to hold contact info."""
        soup = BeautifulSoup(html, "html.parser")
        host = urlparse(page_url).netloc.lower().removeprefix("www.")
        ranked: dict[str, int] = {}
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            url = urljoin(page_url, href).split("#")[0]
            p = urlparse(url)
            if p.scheme not in ("http", "https") or p.netloc.lower().removeprefix("www.") != host:
                continue
            if url.rstrip("/") == page_url.rstrip("/"):
                continue
            label = f"{p.path} {a.get_text(' ', strip=True)}"
            for pattern, rank in PRIORITY_LINK_PATTERNS:
                if pattern.search(label):
                    ranked[url] = min(rank, ranked.get(url, 99))
                    break
        return [u for u, _ in sorted(ranked.items(), key=lambda kv: kv[1])]
