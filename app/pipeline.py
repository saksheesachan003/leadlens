"""Job pipeline: normalize -> dedupe -> fetch (cached) -> extract -> validate -> score."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
import uuid
from urllib.parse import urlparse

from . import db
from .demo_sites import RoutingTransport
from .extract import extract_company
from .scoring import score_lead
from .scraper import Scraper, SiteResult, normalize_domain
from .validate import validate_email

log = logging.getLogger("leadlens")
MAX_DOMAINS_PER_JOB = 200
URL_COLUMN_HINTS = ("website", "domain", "url", "site", "web", "homepage", "company website", "email")


def parse_inputs(raw_items: list[str]) -> tuple[list[str], int, list[str]]:
    """Returns (unique domains, duplicates removed, invalid inputs)."""
    seen: list[str] = []
    dupes = 0
    invalid: list[str] = []
    for item in raw_items:
        item = item.strip()
        if not item:
            continue
        d = normalize_domain(item)
        if d is None:
            invalid.append(item[:80])
        elif d in seen:
            dupes += 1
        else:
            seen.append(d)
    return seen, dupes, invalid


def items_from_text(text: str) -> list[str]:
    return [t for t in re.split(r"[\n,;\t]+", text) if t.strip()]


def items_from_csv(content: bytes) -> list[str]:
    """Pick the column that looks like websites; fall back to any domain-like cell."""
    text = content.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]
    for hint in URL_COLUMN_HINTS:
        for i, h in enumerate(header):
            if hint == h or hint in h:
                return [r[i] for r in rows[1:] if i < len(r) and r[i].strip()]
    # No recognizable header: take the first domain-like value in each row.
    out = []
    for r in rows:
        for cell in r:
            if normalize_domain(cell):
                out.append(cell)
                break
    return out


def start_job(raw_items: list[str], lens: str, industries: list[str]) -> dict:
    domains, dupes, invalid = parse_inputs(raw_items)
    if len(domains) > MAX_DOMAINS_PER_JOB:
        raise ValueError(f"Please submit at most {MAX_DOMAINS_PER_JOB} websites per run (got {len(domains)}).")
    if not domains:
        raise ValueError("No valid websites found. Paste domains like acme.com, one per line.")
    job_id = uuid.uuid4().hex[:12]
    db.create_job(job_id, len(domains), dupes, invalid, {"lens": lens, "industries": industries, "domains": domains})
    return {"id": job_id, "domains": domains}


async def _enrich_one(scraper: Scraper, domain: str) -> dict:
    cached = db.get_site_cache(domain)
    site = SiteResult.from_dict(cached) if cached else await scraper.fetch_site(domain)
    if not cached and site.pages:
        db.set_site_cache(domain, site.to_dict())

    lead: dict = {"domain": domain, "website": site.final_url or f"https://{domain}", "https": site.https,
                  "error": site.error, "from_cache": bool(cached)}
    if site.pages:
        lead.update(extract_company([{"url": p.url, "html": p.html} for p in site.pages], domain))
        lead["emails"] = list(await asyncio.gather(*(validate_email(e) for e in lead["emails"])))
    else:
        lead.update({"company_name": domain, "emails": [], "phones": [], "socials": {}, "industry": None,
                     "tech_stack": [], "pages_scanned": []})
    return lead


def apply_score(lead: dict, lens: str, industries: list[str]) -> dict:
    lead.update(score_lead(lead, lens, industries))
    best = next((e for e in lead.get("emails", []) if e.get("status") in ("valid", "unverified", "risky")), None)
    lead["best_email"] = best["email"] if best else None
    lead["best_email_status"] = best["status"] if best else None
    lead["contact_name"] = best.get("name") if best else None
    lead["contact_title"] = best.get("title") if best else None
    return lead


async def run_job(job_id: str) -> None:
    job = db.get_job(job_id)
    if job is None:
        return
    params = job["params"]
    db.update_job(job_id, status="running")
    scraper = Scraper(transport=RoutingTransport())
    final_hosts: dict[str, str] = {}
    try:
        async def work(domain: str) -> None:
            try:
                lead = await _enrich_one(scraper, domain)
            except Exception as exc:  # one bad site must never kill the job
                log.exception("enrich failed for %s", domain)
                lead = {"domain": domain, "website": f"https://{domain}", "error": f"Processing error: {type(exc).__name__}",
                        "emails": [], "phones": [], "socials": {}, "company_name": domain, "tech_stack": []}
            # Second dedupe pass: two inputs that redirect to the same site.
            host = (urlparse(lead.get("website") or "").hostname or domain).removeprefix("www.")
            if host in final_hosts and final_hosts[host] != domain:
                db.execute("UPDATE jobs SET duplicates_removed = duplicates_removed + 1, total = total - 1 WHERE id=?",
                           (job_id,))
                return
            final_hosts[host] = domain
            db.save_lead(job_id, apply_score(lead, params["lens"], params["industries"]))
            db.increment_done(job_id)

        await asyncio.gather(*(work(d) for d in params["domains"]))
        db.update_job(job_id, status="done")
    except Exception:
        log.exception("job %s failed", job_id)
        db.update_job(job_id, status="failed")
    finally:
        await scraper.close()


def rescore_job(job_id: str, lens: str, industries: list[str]) -> None:
    """Re-rank existing results instantly when the user changes lens or targets: no re-scraping."""
    job = db.get_job(job_id)
    params = {**job["params"], "lens": lens, "industries": industries}
    db.update_job(job_id, params=json.dumps(params))
    for lead in db.get_leads(job_id):
        db.save_lead(job_id, apply_score(lead, lens, industries))
