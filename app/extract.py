"""Turn raw HTML pages into structured, sales-relevant facts.

Everything here is pure (no network), which keeps it fast and easy to test.
"""
from __future__ import annotations

import html as htmllib
import re
from datetime import date
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup

CURRENT_YEAR = date.today().year

EMAIL_RE = re.compile(r"(?<![\w.+-])([a-z0-9][a-z0-9._%+-]{0,63}@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,24})(?![\w-])", re.I)
# "jane [at] acme [dot] com", "jane(at)acme.com"
OBFUSCATED_RE = re.compile(
    r"([a-z0-9._%+-]+)\s*[\[(\{]\s*at\s*[\])\}]\s*([a-z0-9-]+(?:\s*(?:[\[(\{]\s*dot\s*[\])\}]|\.)\s*[a-z0-9-]+)+)", re.I)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?([2-9]\d{2})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})(?!\d)")
YEAR_FOUNDED_RE = re.compile(
    r"\b(?:since|established|est\.?|founded(?:\s+in)?|serving\s+(?:\w+\s+){0,4}since|in\s+business\s+since)\s+(?:in\s+)?((?:18|19|20)\d{2})\b", re.I)
YEARS_IN_BUSINESS_RE = re.compile(r"\b(\d{2,3})\+?\s+years\s+(?:of\s+)?(?:experience|in\s+business|serving)", re.I)
COPYRIGHT_RE = re.compile(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?((?:19|20)\d{2})", re.I)
EMPLOYEES_RE = re.compile(r"\b(?:team\s+of|over|more\s+than)\s+(\d{1,5})\s+(?:employees|staff|professionals|team\s+members|people)", re.I)

JUNK_EMAIL_PARTS = ("example.com", "sentry", "wixpress", "domain.com", "email.com", "yourname", "@2x", ".png", ".jpg",
                    ".jpeg", ".gif", ".svg", ".webp", "u003e", "firstname", "name@", "user@")
ROLE_PREFIXES = {"info", "contact", "sales", "hello", "support", "admin", "office", "team", "help", "service",
                 "inquiries", "enquiries", "billing", "accounts", "marketing", "careers", "jobs", "hr", "media",
                 "press", "webmaster", "noreply", "no-reply", "mail", "general", "orders", "customerservice"}
OWNER_TITLES = re.compile(r"\b(owner|founder|co-founder|president|ceo|principal|managing partner|proprietor)\b", re.I)

SOCIAL_HOSTS = {
    "linkedin": ("linkedin.com",),
    "facebook": ("facebook.com",),
    "x": ("twitter.com", "x.com"),
    "instagram": ("instagram.com",),
    "youtube": ("youtube.com",),
}

# Lightweight keyword taxonomy. Good enough to route and filter leads; an LLM
# classifier is the natural upgrade (see README "Next steps").
INDUSTRIES = {
    "HVAC & Plumbing": ["hvac", "plumbing", "plumber", "heating", "air conditioning", "furnace", "boiler"],
    "Construction & Trades": ["contractor", "construction", "roofing", "electrician", "remodel", "landscaping", "paving"],
    "Manufacturing": ["manufacturing", "manufacturer", "fabrication", "machining", "cnc", "industrial", "assembly"],
    "Distribution & Logistics": ["distribution", "distributor", "wholesale", "logistics", "freight", "warehousing", "trucking"],
    "Healthcare Services": ["clinic", "dental", "medical", "healthcare", "physical therapy", "veterinary", "home health"],
    "Professional Services": ["accounting", "cpa", "bookkeeping", "law firm", "attorney", "consulting", "insurance agency", "staffing"],
    "Software & IT": ["software", "saas", "platform", "it services", "managed services", "cloud", "cybersecurity", "msp"],
    "Marketing & Agencies": ["marketing agency", "digital agency", "seo", "advertising", "branding", "web design"],
    "Food & Hospitality": ["restaurant", "catering", "bakery", "hotel", "brewery", "coffee"],
    "Retail & E-commerce": ["shop now", "add to cart", "online store", "retail", "boutique"],
}

TECH_SIGNATURES = {
    "WordPress": ["wp-content", "wp-includes"],
    "Shopify": ["cdn.shopify.com", "shopify"],
    "Wix": ["wixstatic.com", "wix.com"],
    "Squarespace": ["squarespace"],
    "HubSpot": ["js.hs-scripts.com", "hubspot"],
    "Salesforce": ["salesforce", "pardot"],
    "Google Analytics": ["googletagmanager.com", "google-analytics.com", "gtag("],
    "Intercom": ["intercom"],
    "Stripe": ["js.stripe.com"],
    "Next.js/React": ["__next", "_next/static", "react"],
}

US_STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC "
             "ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY").split()
ADDRESS_RE = re.compile(r"\b([A-Z][a-z]+(?:[ .'-][A-Z][a-z]+){0,3}),\s*(" + "|".join(US_STATES) + r")\s+(\d{5})(?:-\d{4})?\b")
# Words that sit before a city in page text (nav links, labels) and are never part of it.
NOT_CITY = {"home", "about", "us", "contact", "our", "services", "call", "visit", "located", "in", "address",
            "office", "headquarters", "hq", "serving", "team", "careers", "blog", "the", "at", "and", "map"}


def _city(raw: str) -> str:
    words = raw.split()
    while len(words) > 1 and words[0].lower() in NOT_CITY:
        words.pop(0)
    return " ".join(words)


def _clean_email(e: str) -> str | None:
    e = unquote(e).strip().strip(".").lower()
    e = e.split("?")[0]
    if any(j in e for j in JUNK_EMAIL_PARTS) or len(e) > 100 or e.count("@") != 1:
        return None
    return e


def extract_emails(html: str, text: str) -> list[str]:
    found: list[str] = []
    soup_mailtos = re.findall(r'href=["\']mailto:([^"\'>\s]+)', html, re.I)
    for raw in soup_mailtos + EMAIL_RE.findall(htmllib.unescape(text)):
        e = _clean_email(raw)
        if e and e not in found:
            found.append(e)
    for user, dom in OBFUSCATED_RE.findall(text):
        dom = re.sub(r"\s*[\[(\{]\s*dot\s*[\])\}]\s*|\s*\.\s*", ".", dom, flags=re.I)
        e = _clean_email(f"{user}@{dom}")
        if e and EMAIL_RE.fullmatch(e) and e not in found:
            found.append(e)
    return found


def extract_phones(html: str, text: str) -> list[str]:
    out: list[str] = []
    candidates = re.findall(r'href=["\']tel:([^"\'>]+)', html, re.I) + [m.group(0) for m in PHONE_RE.finditer(text)]
    for c in candidates:
        m = PHONE_RE.search(unquote(c))
        if not m:
            continue
        formatted = f"({m.group(1)}) {m.group(2)}-{m.group(3)}"
        if formatted not in out and not re.fullmatch(r"\((\d)\1\1\) \1\1\1-\1\1\1\1", formatted):
            out.append(formatted)
    return out[:5]


def classify_email(email: str, site_domain: str) -> dict:
    local, dom = email.split("@", 1)
    is_role = local in ROLE_PREFIXES or local.split(".")[0] in ROLE_PREFIXES
    on_domain = dom == site_domain or dom.endswith("." + site_domain)
    return {"email": email, "type": "role" if is_role else "personal", "on_domain": on_domain}


def guess_name_for_email(email: str, text: str) -> dict | None:
    """Find 'Jane Smith, Owner' on the page for a first.last style email.

    Only returns a name that actually appears in the page text, never one
    invented from the email address alone.
    """
    parts = [p for p in re.split(r"[._-]", email.split("@")[0]) if p.isalpha() and len(p) > 1]
    if len(parts) < 2:
        return None
    for first, last in ((parts[0], parts[1]), (parts[1], parts[0])):
        m = re.search(rf"\b{re.escape(first)}\s+{re.escape(last)}\b", text, re.I)
        if m:
            window = text[max(0, m.start() - 80): m.end() + 80]
            t = OWNER_TITLES.search(window)
            return {"name": f"{first.capitalize()} {last.capitalize()}", "title": t.group(1).title() if t else None}
    return None


def extract_company(pages: list[dict], domain: str) -> dict:
    """Build the structured profile from all fetched pages of one site."""
    all_html = "\n".join(p["html"] for p in pages)
    texts, socials = [], {}
    name = description = None
    has_contact_form = False

    for i, p in enumerate(pages):
        soup = BeautifulSoup(p["html"], "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        if i == 0:
            og_name = soup.find("meta", attrs={"property": "og:site_name"})
            title = soup.title.get_text(strip=True) if soup.title else ""
            name = (og_name.get("content") if og_name else None) or _clean_title(title) or None
            desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
            description = (desc.get("content") or "").strip()[:300] if desc else None
        if soup.find("form") and (soup.find("textarea") or soup.find("input", attrs={"type": "email"})):
            has_contact_form = True
        for a in soup.find_all("a", href=True):
            host = (urlparse(a["href"]).hostname or "").lower().removeprefix("www.")
            for net, hosts in SOCIAL_HOSTS.items():
                if net not in socials and any(host == h or host.endswith("." + h) for h in hosts):
                    socials[net] = a["href"].split("?")[0]
        texts.append(soup.get_text(" ", strip=True))

    text = re.sub(r"\s+", " ", " ".join(texts))
    lower_text = text.lower()

    emails = [classify_email(e, domain) for e in extract_emails(all_html, text)]
    for e in emails:
        if e["type"] == "personal":
            person = guess_name_for_email(e["email"], text)
            if person:
                e.update(person)
    # Personal, on-domain emails first: they're what a rep actually wants.
    emails.sort(key=lambda e: (e["type"] != "personal", not e["on_domain"]))

    founded = None
    m = YEAR_FOUNDED_RE.search(text)
    if m and 1800 <= int(m.group(1)) <= CURRENT_YEAR:
        founded = int(m.group(1))
    else:
        m2 = YEARS_IN_BUSINESS_RE.search(text)
        if m2 and 1 <= int(m2.group(1)) <= 200:
            founded = CURRENT_YEAR - int(m2.group(1))

    copyright_years = [int(y) for y in COPYRIGHT_RE.findall(all_html) if 1990 <= int(y) <= CURRENT_YEAR]
    emp = EMPLOYEES_RE.search(text)
    addr = ADDRESS_RE.search(text)

    industry_hits = {ind: sum(lower_text.count(k) for k in kws) for ind, kws in INDUSTRIES.items()}
    best_industry = max(industry_hits, key=industry_hits.get)
    industry = best_industry if industry_hits[best_industry] >= 2 else "Other / Unclassified"

    html_lower = all_html.lower()
    tech = [t for t, sigs in TECH_SIGNATURES.items() if any(s in html_lower for s in sigs)]

    return {
        "company_name": name or domain,
        "description": description,
        "emails": emails[:8],
        "phones": extract_phones(all_html, text),
        "socials": socials,
        "industry": industry,
        "founded_year": founded,
        "years_in_business": (CURRENT_YEAR - founded) if founded else None,
        "last_site_update_year": max(copyright_years) if copyright_years else None,
        "employee_hint": int(emp.group(1)) if emp else None,
        "location": f"{_city(addr.group(1))}, {addr.group(2)}" if addr else None,
        "family_or_owner_operated": bool(re.search(r"family[- ]owned|family[- ]operated|owner[- ]operated|locally owned", lower_text)),
        "owner_mentioned": bool(OWNER_TITLES.search(text)),
        "hiring": bool(re.search(r"\b(careers|we'?re hiring|join our team|open positions)\b", lower_text)),
        "has_contact_form": has_contact_form,
        "tech_stack": tech,
        "pages_scanned": [p["url"] for p in pages],
    }


def _clean_title(title: str) -> str:
    # "Home | Acme Plumbing - Denver's Best" -> "Acme Plumbing"
    parts = [p.strip() for p in re.split(r"\s[|\-–—:]\s", title) if p.strip()]
    parts = [p for p in parts if p.lower() not in ("home", "homepage", "welcome")]
    return parts[0][:80] if parts else ""
