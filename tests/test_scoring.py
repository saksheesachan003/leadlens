from app.scoring import score_lead

BASE = {
    "emails": [{"email": "jane@acme.com", "type": "personal", "on_domain": True, "status": "valid", "name": "Jane Doe", "title": "Owner"}],
    "phones": ["(303) 555-0142"], "socials": {"linkedin": "x"}, "has_contact_form": True,
    "industry": "HVAC & Plumbing", "https": True, "description": "d", "location": "Denver, CO",
    "years_in_business": 40, "family_or_owner_operated": True, "owner_mentioned": True,
    "last_site_update_year": 2015, "tech_stack": [], "hiring": False, "employee_hint": None,
}


def test_scores_are_bounded_and_explained():
    for lens in ("sales", "acquisition"):
        r = score_lead(BASE, lens)
        assert 0 <= r["score"] <= 100
        assert sum(x["points"] for x in r["reasons"]) == r["score"]
        assert r["next_action"] == "Email Jane Doe (Owner) directly"


def test_acquisition_lens_rewards_established_owner_run():
    r = score_lead(BASE, "acquisition", ["HVAC & Plumbing"])
    assert r["tier"] == "Hot"
    young = {**BASE, "years_in_business": 2, "family_or_owner_operated": False, "owner_mentioned": False}
    assert score_lead(young, "acquisition")["score"] < r["score"] - 25


def test_target_industry_mismatch_costs_points():
    hit = score_lead(BASE, "sales", ["HVAC & Plumbing"])["score"]
    miss = score_lead(BASE, "sales", ["Software & IT"])["score"]
    assert hit - miss == 20


def test_unreachable_site():
    r = score_lead({"error": "Site unreachable"}, "sales")
    assert r == {"score": 0, "tier": "Unreachable", "reasons": [{"points": 0, "text": "Site unreachable"}],
                 "next_action": "Skip, or check the website address"}


def test_no_contact_next_action():
    lead = {**BASE, "emails": [], "phones": [], "socials": {}, "has_contact_form": False}
    assert score_lead(lead)["next_action"] == "Research further: no direct contact found"
