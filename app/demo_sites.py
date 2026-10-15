"""Fictional demo companies served on the reserved `.example` TLD.

These let anyone try the full pipeline (and record a demo) without network
access and without scraping real businesses. Requests to every other domain
go to the real internet through the normal transport.
"""
from __future__ import annotations

import os
import ssl
from datetime import date

import httpx

Y = date.today().year

DEMO_DOMAINS = [
    "summitcomfort-hvac.example",
    "https://www.summitcomfort-hvac.example/about",   # duplicate on purpose
    "precisionparts-mfg.example",
    "brightpath-cpa.example",
    "nimbus-cloudops.example",
    "ridgeline-logistics.example",
    "greenleaf-landscaping.example",
    "nomail-bakery.example",
    "privatefirm.example",
    "offline-co.example",
    "not a website",
]


def _page(title: str, body: str, desc: str = "", head_extra: str = "", year: int = Y) -> str:
    return f"""<!doctype html><html><head><title>{title}</title>
<meta name="description" content="{desc}">{head_extra}</head>
<body><nav><a href="/">Home</a> <a href="/about">About Us</a> <a href="/contact">Contact</a></nav>
{body}<footer>&copy; {year} {title.split('|')[0].strip()}</footer></body></html>"""


GA = '<script async src="https://www.googletagmanager.com/gtag/js?id=G-X"></script>'
HUBSPOT = '<script src="//js.hs-scripts.com/123.js"></script>'

SITES: dict[str, dict] = {
    "summitcomfort-hvac.example": {
        "https": False,
        "pages": {
            "/": _page("Summit Comfort Heating & Air | Denver HVAC",
                       "<h1>Family-owned heating, air conditioning and plumbing since 1984</h1>"
                       "<p>Furnace repair, boiler service and HVAC installs across the Front Range.</p>"
                       "<p>Call (303) 555-0142</p>",
                       "Family-owned Denver HVAC and plumbing company serving homes since 1984.", year=2019),
            "/about": _page("About | Summit Comfort Heating & Air",
                            "<p>Mike Delgado, Owner, took over the family HVAC business from his father.</p>"
                            "<p>Our team of 22 employees serves Denver, CO 80202.</p>", year=2019),
            "/contact": _page("Contact | Summit Comfort Heating & Air",
                              "<p>Reach Mike: <a href='mailto:mike.delgado@summitcomfort-hvac.example'>email</a></p>"
                              "<p>Office: info@summitcomfort-hvac.example</p>"
                              "<a href='https://www.linkedin.com/company/summit-comfort'>LinkedIn</a>", year=2019),
        },
    },
    "precisionparts-mfg.example": {
        "pages": {
            "/": _page("Precision Parts Manufacturing",
                       "<h1>CNC machining and metal fabrication, established 1972</h1>"
                       "<p>Industrial manufacturing for aerospace and assembly partners. Over 45 employees.</p>",
                       "Precision CNC machining and fabrication manufacturer since 1972.", year=2016),
            "/contact": _page("Contact Precision Parts",
                              "<p>Jane Whitfield, President: jane.whitfield (at) precisionparts-mfg.example</p>"
                              "<p>Quotes: sales@precisionparts-mfg.example | 1-614-555-0199</p>"
                              "<p>Columbus, OH 43215</p>"
                              "<a href='https://linkedin.com/company/precision-parts'>LinkedIn</a>", year=2016),
        },
    },
    "brightpath-cpa.example": {
        "pages": {
            "/": _page("BrightPath CPA | Accounting & Bookkeeping",
                       "<h1>Owner-operated accounting firm since 2001</h1>"
                       "<p>Tax, bookkeeping and CPA advisory for small businesses. We're hiring! See careers.</p>",
                       "Tax, accounting and bookkeeping for small businesses in Austin.", head_extra=GA),
            "/about": _page("About BrightPath CPA",
                            "<p>Founder Priya Raman, CPA, leads a team of 12 professionals in Austin, TX 78701.</p>"
                            "<p>Email priya.raman@brightpath-cpa.example or call (512) 555-0117.</p>",
                            head_extra=GA),
        },
    },
    "nimbus-cloudops.example": {
        "pages": {
            "/": _page("Nimbus CloudOps - Managed Cloud & Cybersecurity",
                       "<div id='__next'><h1>Managed services and cloud platform operations</h1>"
                       "<p>Software, cybersecurity and IT services for mid-market teams. Founded in 2021.</p>"
                       "<p>Join our team: open positions in careers.</p>"
                       "<p>hello@nimbus-cloudops.example</p>"
                       "<a href='https://www.linkedin.com/company/nimbus-cloudops'>in</a>"
                       "<a href='https://x.com/nimbuscloud'>x</a></div>",
                       "Managed cloud operations and cybersecurity for growing companies.",
                       head_extra=HUBSPOT + GA),
        },
    },
    "ridgeline-logistics.example": {
        "pages": {
            "/": _page("Ridgeline Logistics | Freight & Warehousing",
                       "<h1>35 years in business moving freight</h1>"
                       "<p>Trucking, warehousing and wholesale distribution logistics.</p>"
                       "<p>Dispatch: <a href='tel:+19185550173'>918.555.0173</a></p>",
                       "Regional freight, trucking and warehousing logistics.", year=2018),
            "/contact": _page("Contact Ridgeline",
                              "<form><input type='text' name='n'><textarea name='m'></textarea></form>"
                              "<p>Tulsa, OK 74103</p>", year=2018),
        },
    },
    "greenleaf-landscaping.example": {
        "pages": {
            "/": _page("Greenleaf Landscaping",
                       "<h1>Family owned landscaping and paving contractor since 1995</h1>"
                       "<p>Owner: Tom Greer. Email greenleaf.tom@gmail.com, call (470) 555-0110.</p>"
                       "<a href='https://facebook.com/greenleafland'>Facebook</a>",
                       "Landscaping, hardscape and paving contractor serving Atlanta since 1995.", year=2020),
        },
    },
    "nomail-bakery.example": {
        "pages": {
            "/": _page("Nomail Bakery & Coffee",
                       "<h1>Neighborhood bakery and coffee since 2012</h1>"
                       "<p>Catering orders: orders@nomail-bakery.example</p>",
                       "Fresh bread, pastries and coffee.", year=Y - 1),
        },
    },
    "privatefirm.example": {
        "robots": "User-agent: *\nDisallow: /\n",
        "pages": {"/": _page("Private Firm", "<p>private</p>")},
    },
    # offline-co.example is intentionally absent: it simulates a dead site.
}


def _handler(request: httpx.Request) -> httpx.Response:
    host = request.url.host.removeprefix("www.")
    site = SITES.get(host)
    if site is None:
        raise httpx.ConnectError("demo: host unreachable", request=request)
    if request.url.scheme == "https" and site.get("https", True) is False:
        raise httpx.ConnectError("demo: no TLS", request=request)
    path = request.url.path or "/"
    if path == "/robots.txt":
        if "robots" in site:
            return httpx.Response(200, text=site["robots"], headers={"content-type": "text/plain"})
        return httpx.Response(404, text="")
    page = site["pages"].get(path.rstrip("/") or "/")
    if page is None:
        return httpx.Response(404, text="not found", headers={"content-type": "text/html"})
    return httpx.Response(200, text=page, headers={"content-type": "text/html; charset=utf-8"})


class RoutingTransport(httpx.AsyncBaseTransport):
    """Send `.example` hosts to the demo fixtures, everything else to the internet."""

    def __init__(self) -> None:
        self._demo = httpx.MockTransport(_handler)
        # Honor HTTPS_PROXY / SSL_CERT_FILE like a normal httpx client would, so the
        # tool also works behind corporate proxies.
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None
        cafile = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
        verify = ssl.create_default_context(cafile=cafile) if cafile else True
        self._real = httpx.AsyncHTTPTransport(retries=1, proxy=proxy, verify=verify)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host.endswith(".example"):
            return await self._demo.handle_async_request(request)
        return await self._real.handle_async_request(request)

    async def aclose(self) -> None:
        await self._real.aclose()
