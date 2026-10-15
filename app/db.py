"""SQLite storage: jobs, leads, and two caches (scraped sites, MX lookups).

SQLite is a deliberate choice for a 5-hour build: zero setup, one file, and
WAL mode handles the concurrent reads from the polling UI. The schema maps
1:1 onto Postgres if the tool needs to scale (see README).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any

DB_PATH = os.environ.get("LEADLENS_DB", os.path.join(os.path.dirname(__file__), "..", "data", "leadlens.db"))

# Scraped pages are cached for 7 days, MX results for 3 days.
SITE_CACHE_TTL = 7 * 24 * 3600
MX_CACHE_TTL = 3 * 24 * 3600

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    status TEXT NOT NULL,              -- queued | running | done | failed
    total INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    duplicates_removed INTEGER NOT NULL DEFAULT 0,
    invalid_inputs TEXT NOT NULL DEFAULT '[]',
    params TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS leads (
    job_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    data TEXT NOT NULL,
    PRIMARY KEY (job_id, domain)
);
CREATE INDEX IF NOT EXISTS idx_leads_job_score ON leads(job_id, score DESC);
CREATE TABLE IF NOT EXISTS site_cache (
    domain TEXT PRIMARY KEY,
    fetched_at REAL NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mx_cache (
    domain TEXT PRIMARY KEY,
    checked_at REAL NOT NULL,
    status TEXT NOT NULL               -- ok | none | unknown
);
"""


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
    return _conn


def execute(sql: str, args: tuple = ()) -> None:
    with _lock:
        c = conn()
        c.execute(sql, args)
        c.commit()


def query(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return conn().execute(sql, args).fetchall()


# ---- jobs ---------------------------------------------------------------

def create_job(job_id: str, total: int, duplicates: int, invalid: list[str], params: dict) -> None:
    execute(
        "INSERT INTO jobs (id, created_at, status, total, duplicates_removed, invalid_inputs, params) VALUES (?,?,?,?,?,?,?)",
        (job_id, time.time(), "queued", total, duplicates, json.dumps(invalid), json.dumps(params)),
    )


def update_job(job_id: str, **fields: Any) -> None:
    cols = ", ".join(f"{k}=?" for k in fields)
    execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))


def increment_done(job_id: str) -> None:
    execute("UPDATE jobs SET done = done + 1 WHERE id=?", (job_id,))


def get_job(job_id: str) -> dict | None:
    rows = query("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not rows:
        return None
    r = dict(rows[0])
    r["invalid_inputs"] = json.loads(r["invalid_inputs"])
    r["params"] = json.loads(r["params"])
    return r


def save_lead(job_id: str, lead: dict) -> None:
    execute(
        "INSERT OR REPLACE INTO leads (job_id, domain, score, data) VALUES (?,?,?,?)",
        (job_id, lead["domain"], lead["score"], json.dumps(lead)),
    )


def get_leads(job_id: str) -> list[dict]:
    rows = query("SELECT data FROM leads WHERE job_id=? ORDER BY score DESC, domain", (job_id,))
    return [json.loads(r["data"]) for r in rows]


# ---- caches -------------------------------------------------------------

def get_site_cache(domain: str) -> dict | None:
    rows = query("SELECT fetched_at, payload FROM site_cache WHERE domain=?", (domain,))
    if rows and time.time() - rows[0]["fetched_at"] < SITE_CACHE_TTL:
        return json.loads(rows[0]["payload"])
    return None


def set_site_cache(domain: str, payload: dict) -> None:
    execute("INSERT OR REPLACE INTO site_cache (domain, fetched_at, payload) VALUES (?,?,?)",
            (domain, time.time(), json.dumps(payload)))


def get_mx_cache(domain: str) -> str | None:
    rows = query("SELECT checked_at, status FROM mx_cache WHERE domain=?", (domain,))
    if rows and time.time() - rows[0]["checked_at"] < MX_CACHE_TTL:
        return rows[0]["status"]
    return None


def set_mx_cache(domain: str, status: str) -> None:
    execute("INSERT OR REPLACE INTO mx_cache (domain, checked_at, status) VALUES (?,?,?)",
            (domain, time.time(), status))
