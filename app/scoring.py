"""Explainable lead scoring.

Every point comes with a human-readable reason, so a rep (or a deal team)
can see *why* a lead is Hot instead of trusting a black box. Two lenses
reflect Caprae's two uses of lead data:

* sales       - outbound selling: can we reach a decision-maker, and do they fit?
* acquisition - ETA / search-fund sourcing: is this an established,
                owner-run business with room for post-acquisition upside?
"""
from __future__ import annotations

from datetime import date

CURRENT_YEAR = date.today().year
MARKETING_TECH = {"HubSpot", "Salesforce", "Google Analytics", "Intercom"}

TIERS = [(70, "Hot"), (45, "Warm"), (0, "Cold")]


def _best_email(lead: dict) -> dict | None:
    usable = [e for e in lead.get("emails", []) if e.get("status") in ("valid", "risky", "unverified")]
    rank = {"valid": 0, "unverified": 1, "risky": 2}
    usable.sort(key=lambda e: (e["type"] != "personal", not e.get("on_domain"), rank[e["status"]]))
    return usable[0] if usable else None


def _reach_points(lead: dict, email_max: int, phone_max: int, other_max: int, reasons: list) -> int:
    pts = 0
    best = _best_email(lead)
    if best:
        if best["type"] == "personal" and best["status"] == "valid":
            p, why = email_max, f"Verified direct email ({best['email']})"
        elif best["status"] == "valid":
            p, why = round(email_max * 0.6), f"Verified shared inbox ({best['email']})"
        else:
            p, why = round(email_max * 0.3), f"Email found but not verified ({best['email']})"
        pts += p
        reasons.append((p, why))
    else:
        reasons.append((0, "No usable email found"))
    if lead.get("phones"):
        pts += phone_max
        reasons.append((phone_max, "Phone number listed"))
    other = 0
    if "linkedin" in lead.get("socials", {}):
        other += other_max // 2 + other_max % 2
    if lead.get("has_contact_form"):
        other += other_max // 2
    if other:
        pts += min(other, other_max)
        reasons.append((min(other, other_max), "LinkedIn page / contact form available"))
    return pts


def _industry_points(lead: dict, targets: list[str], match_pts: int, reasons: list) -> int:
    ind = lead.get("industry")
    if targets:
        if ind in targets:
            reasons.append((match_pts, f"Matches target industry: {ind}"))
            return match_pts
        reasons.append((0, f"Outside target industries ({ind})"))
        return 0
    if ind and not ind.startswith("Other"):
        p = match_pts // 2
        reasons.append((p, f"Industry identified: {ind}"))
        return p
    return 0


def score_lead(lead: dict, lens: str = "sales", target_industries: list[str] | None = None) -> dict:
    targets = target_industries or []
    reasons: list[tuple[int, str]] = []

    if lead.get("error"):
        return {"score": 0, "tier": "Unreachable", "reasons": [{"points": 0, "text": lead["error"]}],
                "next_action": "Skip, or check the website address"}

    score = 0
    yrs = lead.get("years_in_business")
    updated = lead.get("last_site_update_year")

    if lens == "acquisition":
        # Established & owner-run (50)
        if yrs is not None:
            p = 20 if yrs >= 20 else 12 if yrs >= 10 else 5 if yrs >= 5 else 0
            score += p
            reasons.append((p, f"{yrs} years in business"))
        if lead.get("family_or_owner_operated"):
            score += 10
            reasons.append((10, "Family / owner-operated"))
        if lead.get("owner_mentioned"):
            score += 5
            reasons.append((5, "Owner or founder named on site"))
        score += _industry_points(lead, targets, 15, reasons)
        # Reachability (30)
        score += _reach_points(lead, email_max=15, phone_max=10, other_max=5, reasons=reasons)
        # Post-acquisition upside: digital modernization (20)
        if updated and updated <= CURRENT_YEAR - 3:
            score += 10
            reasons.append((10, f"Website not updated since {updated}: modernization upside"))
        if not (set(lead.get("tech_stack", [])) & MARKETING_TECH):
            score += 5
            reasons.append((5, "No marketing/CRM tooling detected: AI & ops upside"))
        if not lead.get("https"):
            score += 5
            reasons.append((5, "No HTTPS: underinvested web presence"))
    else:
        # Reachability (45)
        score += _reach_points(lead, email_max=25, phone_max=10, other_max=10, reasons=reasons)
        # Fit (35)
        score += _industry_points(lead, targets, 20, reasons)
        if lead.get("hiring"):
            score += 5
            reasons.append((5, "Hiring: growth signal"))
        if lead.get("employee_hint"):
            score += 5
            reasons.append((5, f"Team size mentioned (~{lead['employee_hint']})"))
        if lead.get("location"):
            score += 5
            reasons.append((5, f"Located in {lead['location']}"))
        # Data quality / activity (20)
        if lead.get("https"):
            score += 5
            reasons.append((5, "Secure, maintained website"))
        if lead.get("description"):
            score += 5
            reasons.append((5, "Clear company description"))
        if updated and updated >= CURRENT_YEAR - 1:
            score += 10
            reasons.append((10, "Website active this year"))

    score = max(0, min(100, score))
    tier = next(t for cutoff, t in TIERS if score >= cutoff)
    reasons.sort(key=lambda r: -r[0])
    return {
        "score": score,
        "tier": tier,
        "reasons": [{"points": p, "text": t} for p, t in reasons],
        "next_action": next_action(lead),
    }


def next_action(lead: dict) -> str:
    best = _best_email(lead)
    if best and best["type"] == "personal":
        who = best.get("name") or best["email"]
        title = f" ({best['title']})" if best.get("title") else ""
        return f"Email {who}{title} directly"
    if lead.get("phones"):
        return f"Call {lead['phones'][0]} and ask for the owner"
    if best:
        return f"Email {best['email']}; ask to be routed to the owner"
    if lead.get("has_contact_form"):
        return "Submit the website contact form"
    if "linkedin" in lead.get("socials", {}):
        return "Find the owner via the company LinkedIn page"
    return "Research further: no direct contact found"
