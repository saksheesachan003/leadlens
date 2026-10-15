"""End-to-end through the HTTP API, using the offline demo sites."""
import csv
import io
import time

from fastapi.testclient import TestClient

from app.demo_sites import DEMO_DOMAINS
from app.main import app


def _run(client, **body):
    r = client.post("/api/jobs", json=body)
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] == "done":
            return job_id, job
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_full_flow_dedupe_validation_scoring_export():
    with TestClient(app) as client:
        job_id, job = _run(client, text="\n".join(DEMO_DOMAINS), lens="acquisition", industries=["HVAC & Plumbing"])
        leads = {l["domain"]: l for l in job["leads"]}

        assert job["duplicates_removed"] == 1
        assert job["invalid_inputs"] == ["not a website"]
        assert len(leads) == 9

        top = job["leads"][0]
        assert top["domain"] == "summitcomfort-hvac.example" and top["tier"] == "Hot"
        assert top["best_email"] == "mike.delgado@summitcomfort-hvac.example"
        assert top["contact_title"] == "Owner"

        assert leads["precisionparts-mfg.example"]["best_email"] == "jane.whitfield@precisionparts-mfg.example"
        assert leads["privatefirm.example"]["error"] == "Disallowed by robots.txt"
        assert leads["offline-co.example"]["tier"] == "Unreachable"
        bakery = leads["nomail-bakery.example"]
        assert bakery["emails"][0]["status"] == "invalid" and bakery["best_email"] is None

        # Switching lens re-ranks without re-scraping.
        rescored = client.post(f"/api/jobs/{job_id}/rescore", json={"lens": "sales", "industries": []}).json()
        assert rescored["lens"] == "sales"
        assert rescored["leads"][0]["domain"] == "brightpath-cpa.example"

        r = client.get(f"/api/jobs/{job_id}/export.csv", params={"verified_only": True})
        rows = list(csv.DictReader(io.StringIO(r.text)))
        assert r.headers["content-type"].startswith("text/csv")
        assert {row["Email Status"] for row in rows} == {"valid"}
        assert rows[0]["First Name"] == "Priya" and rows[0]["Last Name"] == "Raman"


def test_csv_upload_finds_website_column():
    content = b"Company,Owner,Website\nSummit,Mike,summitcomfort-hvac.example\nBright,Priya,https://brightpath-cpa.example\n"
    with TestClient(app) as client:
        r = client.post("/api/jobs/upload", files={"file": ("leads.csv", content, "text/csv")}, data={"lens": "sales"})
        assert r.status_code == 200 and r.json()["count"] == 2


def test_bad_input_is_explained():
    with TestClient(app) as client:
        r = client.post("/api/jobs", json={"text": "hello world"})
        assert r.status_code == 400 and "No valid websites" in r.json()["detail"]
        r = client.post("/api/jobs", json={"text": "acme.com", "industries": ["Spaceships"]})
        assert r.status_code == 400
