"""Email validation without sending anything.

Checks: syntax, disposable/free-mail providers, and whether the domain has
MX records (it can actually receive mail). We deliberately do not do SMTP
"RCPT TO" probing: it gets IPs blacklisted and is a grey area ethically.
"""
from __future__ import annotations

import asyncio
import re

import dns.asyncresolver
import dns.exception
import dns.resolver

from . import db

SYNTAX_RE = re.compile(r"^[a-z0-9][a-z0-9._%+-]{0,63}@([a-z0-9-]+\.)+[a-z]{2,24}$")
FREE_PROVIDERS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "live.com",
                  "msn.com", "comcast.net", "att.net", "verizon.net", "protonmail.com", "me.com", "ymail.com"}
DISPOSABLE = {"mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com", "trashmail.com",
              "yopmail.com", "sharklasers.com", "getnada.com", "dispostable.com"}

# Reserved TLD used by the built-in demo sites; never resolvable on the real internet.
DEMO_TLD = ".example"

_resolver = dns.asyncresolver.Resolver()
_resolver.lifetime = 4.0
_mx_locks: dict[str, asyncio.Lock] = {}


async def mx_status(domain: str) -> str:
    """'ok' (has MX or A fallback), 'none' (cannot receive mail), 'unknown' (DNS failed)."""
    if domain.endswith(DEMO_TLD):
        return "none" if domain.startswith("nomail") else "ok"
    if domain in FREE_PROVIDERS:
        return "ok"  # well-known mail providers; no lookup needed
    cached = db.get_mx_cache(domain)
    if cached:
        return cached
    lock = _mx_locks.setdefault(domain, asyncio.Lock())
    async with lock:  # avoid duplicate lookups for the same domain
        cached = db.get_mx_cache(domain)
        if cached:
            return cached
        status = "unknown"
        try:
            answers = await _resolver.resolve(domain, "MX")
            status = "ok" if len(answers) else "none"
        except dns.resolver.NoAnswer:
            # RFC 5321: no MX means mail goes to the A record.
            try:
                await _resolver.resolve(domain, "A")
                status = "ok"
            except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
                status = "none"
            except dns.exception.DNSException:
                status = "unknown"
        except dns.resolver.NXDOMAIN:
            status = "none"
        except dns.exception.DNSException:
            status = "unknown"
        if status != "unknown":
            db.set_mx_cache(domain, status)
        return status


async def validate_email(entry: dict) -> dict:
    """Adds 'status' (valid | risky | invalid | unverified) and 'checks' to an email entry."""
    email = entry["email"]
    checks: list[str] = []
    if not SYNTAX_RE.match(email):
        return {**entry, "status": "invalid", "checks": ["Bad syntax"]}
    domain = email.split("@", 1)[1]
    if domain in DISPOSABLE:
        return {**entry, "status": "invalid", "checks": ["Disposable provider"]}
    mx = await mx_status(domain)
    if mx == "none":
        return {**entry, "status": "invalid", "checks": ["Domain cannot receive mail (no MX)"]}
    status = "valid" if mx == "ok" else "unverified"
    checks.append("MX records found" if mx == "ok" else "DNS check failed; try again later")
    if domain in FREE_PROVIDERS:
        status = "risky" if status == "valid" else status
        checks.append("Free email provider")
    if entry.get("type") == "role":
        checks.append("Role inbox (shared)")
    if not entry.get("on_domain") and domain not in FREE_PROVIDERS:
        checks.append("Different domain than website")
    return {**entry, "status": status, "checks": checks}
