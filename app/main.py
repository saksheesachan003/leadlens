"""LeadLens API + static UI."""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, pipeline
from .demo_sites import DEMO_DOMAINS
from .extract import INDUSTRIES

logging.basicConfig(level=logging.INFO)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")

app = FastAPI(title="LeadLens", version="1.0.0",
              description="Turn a list of company websites into verified, scored, CRM-ready leads.")
_tasks: set[asyncio.Task] = set()

Lens = Literal["sales", "acquisition"]


class JobRequest(BaseModel):
    text: str = Field(..., description="Websites or domains, separated by new lines or commas")
    lens: Lens = "sales"
    industries: list[str] = []


class RescoreRequest(BaseModel):
    lens: Lens
    industries: list[str] = []


def _launch(raw_items: list[str], lens: str, industries: list[str]) -> dict:
    bad = [i for i in industries if i not in INDUSTRIES]
    if bad:
        raise HTTPException(400, f"Unknown industries: {', '.join(bad)}")
    try:
        job = pipeline.start_job(raw_items, lens, industries)
    except ValueError as e:
        raise HTTPException(400, str(e))
    task = asyncio.create_task(pipeline.run_job(job["id"]))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"job_id": job["id"], "count": len(job["domains"])}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/config")
def config() -> dict:
    return {"industries": list(INDUSTRIES), "lenses": ["sales", "acquisition"], "demo_domains": DEMO_DOMAINS,
            "max_per_job": pipeline.MAX_DOMAINS_PER_JOB}


@app.post("/api/jobs")
async def create_job(req: JobRequest) -> dict:
    return _launch(pipeline.items_from_text(req.text), req.lens, req.industries)


@app.post("/api/jobs/upload")
async def create_job_from_csv(file: UploadFile = File(...), lens: Lens = Form("sales"),
                              industries: str = Form("")) -> dict:
    content = await file.read()
    if len(content) > 2_000_000:
        raise HTTPException(400, "CSV too large (max 2 MB).")
    items = pipeline.items_from_csv(content)
    inds = [i for i in industries.split("|") if i]
    return _launch(items, lens, inds)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    leads = db.get_leads(job_id)
    params = job.pop("params")
    return {**job, "lens": params["lens"], "industries": params["industries"], "leads": leads}


@app.post("/api/jobs/{job_id}/rescore")
def rescore(job_id: str, req: RescoreRequest) -> dict:
    if db.get_job(job_id) is None:
        raise HTTPException(404, "Job not found")
    pipeline.rescore_job(job_id, req.lens, req.industries)
    return get_job(job_id)


def filter_leads(leads: list[dict], tier: str | None, min_score: int, verified_only: bool, q: str | None) -> list[dict]:
    out = []
    for lead in leads:
        if tier and lead.get("tier") != tier:
            continue
        if lead.get("score", 0) < min_score:
            continue
        if verified_only and lead.get("best_email_status") != "valid":
            continue
        if q:
            hay = " ".join(str(lead.get(k) or "") for k in ("company_name", "domain", "industry", "location",
                                                             "best_email", "contact_name")).lower()
            if q.lower() not in hay:
                continue
        out.append(lead)
    return out


EXPORT_COLUMNS = ["Company Name", "Website", "Lead Score", "Tier", "First Name", "Last Name", "Job Title", "Email",
                  "Email Status", "Phone Number", "Industry", "City/State", "Years in Business", "LinkedIn",
                  "Next Action", "Why This Score", "Other Emails"]


def lead_to_row(lead: dict) -> list:
    name = (lead.get("contact_name") or "").split(" ", 1)
    other = [e["email"] for e in lead.get("emails", []) if e["email"] != lead.get("best_email")]
    why = "; ".join(r["text"] for r in lead.get("reasons", []) if r["points"] > 0)
    return [lead.get("company_name"), lead.get("website"), lead.get("score"), lead.get("tier"),
            name[0] if name[0] else "", name[1] if len(name) > 1 else "", lead.get("contact_title") or "",
            lead.get("best_email") or "", lead.get("best_email_status") or "",
            (lead.get("phones") or [""])[0], lead.get("industry") or "", lead.get("location") or "",
            lead.get("years_in_business") or "", lead.get("socials", {}).get("linkedin", ""),
            lead.get("next_action") or "", why, ", ".join(other)]


@app.get("/api/jobs/{job_id}/export.csv")
def export_csv(job_id: str, tier: str | None = None, min_score: int = Query(0, ge=0, le=100),
               verified_only: bool = False, q: str | None = None, exclude_unreachable: bool = True):
    if db.get_job(job_id) is None:
        raise HTTPException(404, "Job not found")
    leads = filter_leads(db.get_leads(job_id), tier, min_score, verified_only, q)
    if exclude_unreachable:
        leads = [l for l in leads if l.get("tier") != "Unreachable"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(EXPORT_COLUMNS)
    for lead in leads:
        w.writerow(lead_to_row(lead))
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="leadlens-{job_id}.csv"'})


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
