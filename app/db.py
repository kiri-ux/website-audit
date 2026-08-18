"""
Storage layer.

Deliberately thin: raw SQL over a DB-API connection, no ORM. The schema is the
important artifact here — the dev team may well port this to their own stack,
and a schema plus plain SQL ports cleanly where an ORM does not.

SQLite and Postgres are both supported. The only dialect differences are the
placeholder style and a couple of column types, handled by `_q()` and DDL below.
"""
from __future__ import annotations
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager

from .config import cfg

# ---------------------------------------------------------------- DDL
# partner_id is present in internal mode too, populated with the default
# tenant. That is the whole multi-tenancy migration: flip APP_MODE, start
# writing real partner_ids. No schema change, no backfill of a missing column.
SCHEMA = """
CREATE TABLE IF NOT EXISTS partners (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  api_key       TEXT UNIQUE,
  branding      TEXT,           -- JSON: logo, colours, footer
  created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS audits (
  id             TEXT PRIMARY KEY,
  partner_id     TEXT NOT NULL,
  client_name    TEXT NOT NULL,
  target_url     TEXT NOT NULL,
  vertical       TEXT,
  business_model TEXT,
  status         TEXT NOT NULL,      -- queued|crawling|checking|scoring|ready|failed
  progress       TEXT,               -- human-readable current step
  error          TEXT,
  overall_score  INTEGER,
  overall_rating TEXT,
  pages_crawled  INTEGER,
  coverage       TEXT,
  crawl_blocked  INTEGER DEFAULT 0,  -- crawler could not see the real page
  crawl_note     TEXT,
  crawl_truncated TEXT,
  capture_method TEXT,
  extras         TEXT,               -- JSON: rankings table, screenshots — report
                                     -- material that is not a checkpoint finding
  options        TEXT,               -- JSON: crawl overrides
  created_at     REAL NOT NULL,
  started_at     REAL,
  completed_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_audits_partner ON audits(partner_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audits_status  ON audits(status);

CREATE TABLE IF NOT EXISTS findings (
  audit_id       TEXT NOT NULL,
  checkpoint_id  TEXT NOT NULL,
  status         TEXT NOT NULL,
  value          TEXT,               -- JSON
  evidence       TEXT,
  affected_pages TEXT,               -- JSON array
  severity       TEXT,
  recommendation TEXT,
  source         TEXT,
  confidence     REAL,
  collected_at   REAL,
  PRIMARY KEY (audit_id, checkpoint_id)
);

CREATE TABLE IF NOT EXISTS section_scores (
  audit_id     TEXT NOT NULL,
  section_code TEXT NOT NULL,
  score        INTEGER,
  rating       TEXT,
  checked      INTEGER,
  total        INTEGER,
  failing      INTEGER,
  need_access  INTEGER,
  PRIMARY KEY (audit_id, section_code)
);

-- Static catalogue, seeded from seed/checkpoints.csv
CREATE TABLE IF NOT EXISTS checkpoints (
  id            TEXT PRIMARY KEY,
  prefix        TEXT,
  section       TEXT,
  checkpoint    TEXT,
  template_tool TEXT,
  tier          TEXT,
  collector     TEXT
);

-- DB-backed queue. Used when REDIS_URL is unset; harmless when it is.
CREATE TABLE IF NOT EXISTS jobs (
  id           TEXT PRIMARY KEY,
  audit_id     TEXT NOT NULL,      -- audit_id OR ai_run id, per job_type
  job_type     TEXT NOT NULL DEFAULT 'audit',   -- audit | ai_monitor
  state        TEXT NOT NULL,      -- pending|leased|done|failed
  attempts     INTEGER NOT NULL DEFAULT 0,
  leased_until REAL,
  last_error   TEXT,
  created_at   REAL NOT NULL
);

-- ============================ AI VISIBILITY ============================
-- The monitor is a TIME SERIES, not a one-shot check. A single run answers
-- "are we cited"; the series answers "is our work moving the number", which is
-- what a retainer is actually sold on. Hence a stable panel_version: if the
-- questions change, older runs are no longer comparable and must not be
-- silently plotted on the same line.
CREATE TABLE IF NOT EXISTS ai_profiles (
  id            TEXT PRIMARY KEY,
  partner_id    TEXT NOT NULL,
  client_name   TEXT NOT NULL,
  brand         TEXT NOT NULL,
  domain        TEXT NOT NULL,
  profile       TEXT NOT NULL,     -- JSON ClientProfile
  panel         TEXT,              -- JSON frozen query panel
  panel_version INTEGER NOT NULL DEFAULT 1,
  created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_aiprof_partner ON ai_profiles(partner_id);

CREATE TABLE IF NOT EXISTS ai_runs (
  id               TEXT PRIMARY KEY,
  partner_id       TEXT NOT NULL,
  profile_id       TEXT NOT NULL,
  audit_id         TEXT,
  panel_version    INTEGER,
  status           TEXT NOT NULL,
  progress         TEXT,
  repeats          INTEGER,
  platforms        TEXT,
  skipped          TEXT,
  mention_rate     REAL,
  citation_rate    REAL,
  unprompted_citation_rate REAL,
  client_citations INTEGER,
  top_competitor_domain    TEXT,
  citation_gap     INTEGER,
  answers_ok       INTEGER,
  answers_error    INTEGER,
  headline         TEXT,
  error            TEXT,
  created_at       REAL NOT NULL,
  completed_at     REAL
);
CREATE INDEX IF NOT EXISTS idx_airuns_profile ON ai_runs(profile_id, created_at);

CREATE TABLE IF NOT EXISTS ai_results (
  run_id         TEXT NOT NULL,
  query_id       TEXT NOT NULL,
  platform       TEXT NOT NULL,
  repeat_idx     INTEGER NOT NULL,
  intent         TEXT,
  prompted       INTEGER,
  ok             INTEGER,
  mentioned      INTEGER,
  cited          INTEGER,
  prominence     REAL,
  citation_count INTEGER,
  cited_domains  TEXT,
  error          TEXT,
  PRIMARY KEY (run_id, query_id, platform, repeat_idx)
);

CREATE TABLE IF NOT EXISTS ai_sov (
  run_id     TEXT NOT NULL,
  domain     TEXT NOT NULL,
  citations  INTEGER,
  share      REAL,
  is_client  INTEGER,
  PRIMARY KEY (run_id, domain)
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, created_at);
"""


def _q(sql: str) -> str:
    """SQLite uses ?, Postgres uses %s."""
    return sql.replace("?", "%s") if cfg.is_postgres else sql


@contextmanager
def conn():
    if cfg.is_postgres:
        import psycopg2  # imported lazily so local dev needs no driver
        c = psycopg2.connect(cfg.database_url)
        try:
            yield c
            c.commit()
        finally:
            c.close()
    else:
        os.makedirs(os.path.dirname(cfg.sqlite_path) or ".", exist_ok=True)
        c = sqlite3.connect(cfg.sqlite_path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")       # concurrent reader + writer
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
            c.commit()
        finally:
            c.close()


def _statements(ddl: str):
    """
    Split DDL into statements. Strips `--` comments FIRST, because a semicolon
    inside a comment would otherwise split a statement in half.
    """
    lines = [l for l in ddl.splitlines() if not l.strip().startswith("--")]
    for stmt in "\n".join(lines).split(";"):
        if stmt.strip():
            yield stmt


# Additive migrations. CREATE TABLE IF NOT EXISTS does NOTHING to a table that
# already exists, so a column added to SCHEMA never reaches a deployed database.
# Every new column must ALSO be listed here or production breaks on first write
# with "column does not exist" — while local dev, which starts from an empty
# file, looks perfectly healthy.
#
# Append-only. Never edit or remove a line.
MIGRATIONS = [
    ("audits", "crawl_blocked", "INTEGER DEFAULT 0"),
    ("audits", "crawl_note", "TEXT"),
    ("audits", "crawl_truncated", "TEXT"),
    ("jobs", "job_type", "TEXT DEFAULT 'audit'"),
    ("audits", "capture_method", "TEXT"),
    ("audits", "extras", "TEXT"),
]


def _apply_migrations(cur):
    for table, column, coltype in MIGRATIONS:
        try:
            if cfg.is_postgres:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
                            f"{column} {coltype}")
            else:
                cur.execute(f"PRAGMA table_info({table})")
                if column not in {r[1] for r in cur.fetchall()}:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        except Exception as e:
            # A migration failing must not take the service down; log and move on.
            print(f"[db] migration {table}.{column} skipped: "
                  f"{type(e).__name__}: {e}", flush=True)


def init_db(seed_catalog: str = "seed/checkpoints.csv"):
    with conn() as c:
        cur = c.cursor()
        for stmt in _statements(SCHEMA):
            cur.execute(stmt if not cfg.is_postgres
                        else stmt.replace("REAL", "DOUBLE PRECISION"))
        _apply_migrations(cur)
        # default tenant — exists in internal mode so every row has an owner
        cur.execute(_q("SELECT 1 FROM partners WHERE id=?"), (cfg.default_partner,))
        if not cur.fetchone():
            cur.execute(_q("INSERT INTO partners (id,name,api_key,branding,created_at) "
                           "VALUES (?,?,?,?,?)"),
                        (cfg.default_partner, "Vici Media (internal)",
                         "internal-no-auth", "{}", time.time()))
    seed_checkpoints(seed_catalog)


def seed_checkpoints(path: str):
    import csv
    if not os.path.exists(path):
        return 0
    rows = list(csv.DictReader(open(path)))
    with conn() as c:
        cur = c.cursor()
        cur.execute("SELECT COUNT(*) FROM checkpoints")
        if (cur.fetchone()[0] or 0) == len(rows):
            return len(rows)
        for r in rows:
            cur.execute(_q(
                "INSERT INTO checkpoints (id,prefix,section,checkpoint,template_tool,tier,collector) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT (id) DO NOTHING"),
                (r["id"], r["prefix"], r["section"], r["checkpoint"],
                 r["template_tool"], r["tier"], r["collector"]))
    return len(rows)


def catalog() -> dict:
    with conn() as c:
        cur = c.cursor()
        cur.execute("SELECT id,prefix,section,checkpoint,template_tool,tier,collector "
                    "FROM checkpoints")
        cols = ["id", "prefix", "section", "checkpoint", "template_tool", "tier", "collector"]
        return {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}


# ---------------------------------------------------------------- audits
def create_audit(partner_id, client_name, target_url, vertical=None,
                 business_model=None, options=None) -> str:
    aid = uuid.uuid4().hex[:16]
    with conn() as c:
        c.cursor().execute(_q(
            "INSERT INTO audits (id,partner_id,client_name,target_url,vertical,"
            "business_model,status,progress,options,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)"),
            (aid, partner_id, client_name, target_url, vertical, business_model,
             "queued", "waiting for a worker", json.dumps(options or {}), time.time()))
    return aid


def update_audit(audit_id, **fields):
    if not fields:
        return
    sets = ",".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.cursor().execute(_q(f"UPDATE audits SET {sets} WHERE id=?"),
                           (*fields.values(), audit_id))


def get_audit(audit_id, partner_id=None) -> dict | None:
    sql = "SELECT * FROM audits WHERE id=?"
    args = [audit_id]
    if partner_id:                      # tenant scoping — see tenancy.py
        sql += " AND partner_id=?"
        args.append(partner_id)
    with conn() as c:
        cur = c.cursor()
        cur.execute(_q(sql), tuple(args))
        r = cur.fetchone()
        if not r:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, r))


def list_audits(partner_id=None, limit=100) -> list:
    sql = "SELECT * FROM audits"
    args = []
    if partner_id:
        sql += " WHERE partner_id=?"
        args.append(partner_id)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with conn() as c:
        cur = c.cursor()
        cur.execute(_q(sql), tuple(args))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


# ---------------------------------------------------------------- findings
def save_findings(audit_id, findings: dict):
    with conn() as c:
        cur = c.cursor()
        cur.execute(_q("DELETE FROM findings WHERE audit_id=?"), (audit_id,))
        for cid, f in findings.items():
            cur.execute(_q(
                "INSERT INTO findings (audit_id,checkpoint_id,status,value,evidence,"
                "affected_pages,severity,recommendation,source,confidence,collected_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)"),
                (audit_id, cid, f["status"], json.dumps(f.get("value") or {}),
                 f.get("evidence", ""), json.dumps(f.get("affected_pages") or []),
                 f.get("severity"), f.get("recommendation", ""), f.get("source", ""),
                 f.get("confidence", 1.0), time.time()))


def get_findings(audit_id) -> dict:
    with conn() as c:
        cur = c.cursor()
        cur.execute(_q("SELECT checkpoint_id,status,value,evidence,affected_pages,"
                       "severity,recommendation,source,confidence "
                       "FROM findings WHERE audit_id=?"), (audit_id,))
        out = {}
        for r in cur.fetchall():
            out[r[0]] = {"status": r[1], "value": json.loads(r[2] or "{}"),
                         "evidence": r[3], "affected_pages": json.loads(r[4] or "[]"),
                         "severity": r[5], "recommendation": r[6],
                         "source": r[7], "confidence": r[8]}
        return out


def save_scores(audit_id, scores: dict):
    with conn() as c:
        cur = c.cursor()
        cur.execute(_q("DELETE FROM section_scores WHERE audit_id=?"), (audit_id,))
        for sec, v in scores["sections"].items():
            cur.execute(_q(
                "INSERT INTO section_scores (audit_id,section_code,score,rating,"
                "checked,total,failing,need_access) VALUES (?,?,?,?,?,?,?,?)"),
                (audit_id, sec, v["score"], v["rating"], v["checked"],
                 v["total"], v["failing"], v.get("need_access", 0)))


def get_scores(audit_id) -> dict:
    with conn() as c:
        cur = c.cursor()
        cur.execute(_q("SELECT section_code,score,rating,checked,total,failing,need_access "
                       "FROM section_scores WHERE audit_id=?"), (audit_id,))
        secs = {r[0]: {"score": r[1], "rating": r[2], "checked": r[3], "total": r[4],
                       "failing": r[5], "need_access": r[6]} for r in cur.fetchall()}
    a = get_audit(audit_id) or {}
    return {"sections": secs,
            "overall": {"score": a.get("overall_score"), "rating": a.get("overall_rating")}}


# ================================================================ AI VISIBILITY
def create_ai_profile(partner_id, client_name, profile_dict, panel_list) -> str:
    pid = uuid.uuid4().hex[:16]
    with conn() as c:
        c.cursor().execute(_q(
            "INSERT INTO ai_profiles (id,partner_id,client_name,brand,domain,profile,"
            "panel,panel_version,created_at) VALUES (?,?,?,?,?,?,?,?,?)"),
            (pid, partner_id, client_name, profile_dict["brand"],
             profile_dict["domain"], json.dumps(profile_dict),
             json.dumps(panel_list), 1, time.time()))
    return pid


def get_ai_profile(profile_id, partner_id=None):
    sql, args = "SELECT * FROM ai_profiles WHERE id=?", [profile_id]
    if partner_id:
        sql += " AND partner_id=?"; args.append(partner_id)
    with conn() as c:
        cur = c.cursor(); cur.execute(_q(sql), tuple(args))
        r = cur.fetchone()
        if not r:
            return None
        return dict(zip([d[0] for d in cur.description], r))


def list_ai_profiles(partner_id=None):
    sql, args = "SELECT * FROM ai_profiles", []
    if partner_id:
        sql += " WHERE partner_id=?"; args.append(partner_id)
    sql += " ORDER BY created_at DESC"
    with conn() as c:
        cur = c.cursor(); cur.execute(_q(sql), tuple(args))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def create_ai_run(partner_id, profile_id, repeats, audit_id=None,
                  panel_version=1) -> str:
    rid = uuid.uuid4().hex[:16]
    with conn() as c:
        c.cursor().execute(_q(
            "INSERT INTO ai_runs (id,partner_id,profile_id,audit_id,panel_version,"
            "status,progress,repeats,created_at) VALUES (?,?,?,?,?,?,?,?,?)"),
            (rid, partner_id, profile_id, audit_id, panel_version,
             "queued", "waiting for a worker", repeats, time.time()))
    return rid


def update_ai_run(run_id, **fields):
    if not fields:
        return
    sets = ",".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.cursor().execute(_q(f"UPDATE ai_runs SET {sets} WHERE id=?"),
                           (*fields.values(), run_id))


def get_ai_run(run_id, partner_id=None):
    sql, args = "SELECT * FROM ai_runs WHERE id=?", [run_id]
    if partner_id:
        sql += " AND partner_id=?"; args.append(partner_id)
    with conn() as c:
        cur = c.cursor(); cur.execute(_q(sql), tuple(args))
        r = cur.fetchone()
        if not r:
            return None
        return dict(zip([d[0] for d in cur.description], r))


def list_ai_runs(profile_id=None, partner_id=None, limit=50):
    sql, args, where = "SELECT * FROM ai_runs", [], []
    if profile_id:
        where.append("profile_id=?"); args.append(profile_id)
    if partner_id:
        where.append("partner_id=?"); args.append(partner_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"; args.append(limit)
    with conn() as c:
        cur = c.cursor(); cur.execute(_q(sql), tuple(args))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def save_ai_results(run_id, results, sov):
    with conn() as c:
        cur = c.cursor()
        cur.execute(_q("DELETE FROM ai_results WHERE run_id=?"), (run_id,))
        cur.execute(_q("DELETE FROM ai_sov WHERE run_id=?"), (run_id,))
        for r in results:
            cur.execute(_q(
                "INSERT INTO ai_results (run_id,query_id,platform,repeat_idx,intent,"
                "prompted,ok,mentioned,cited,prominence,citation_count,cited_domains,"
                "error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"),
                (run_id, r["query_id"], r["platform"], r.get("repeat", 0),
                 r.get("intent"), int(bool(r.get("prompted"))), int(bool(r["ok"])),
                 int(bool(r["mentioned"])), int(bool(r["cited"])), r["prominence"],
                 r["citation_count"], json.dumps(r["cited_domains"]), r.get("error")))
        for s in sov:
            cur.execute(_q("INSERT INTO ai_sov (run_id,domain,citations,share,is_client) "
                           "VALUES (?,?,?,?,?)"),
                        (run_id, s["domain"], s["citations"], s["share"],
                         int(bool(s["is_client"]))))


def get_ai_sov(run_id):
    with conn() as c:
        cur = c.cursor()
        cur.execute(_q("SELECT domain,citations,share,is_client FROM ai_sov "
                       "WHERE run_id=? ORDER BY citations DESC"), (run_id,))
        return [{"domain": r[0], "citations": r[1], "share": r[2],
                 "is_client": bool(r[3])} for r in cur.fetchall()]


def get_ai_platform_stats(run_id):
    """Per-platform rates recomputed from stored rows (no duplicated aggregate)."""
    with conn() as c:
        cur = c.cursor()
        cur.execute(_q(
            "SELECT platform, COUNT(*), SUM(mentioned), SUM(cited), AVG(prominence) "
            "FROM ai_results WHERE run_id=? AND ok=1 GROUP BY platform"), (run_id,))
        out = {}
        for plat, n, m, ct, prom in cur.fetchall():
            out[plat] = {"answers": n,
                         "mention_rate": round(100 * (m or 0) / n, 1) if n else None,
                         "citation_rate": round(100 * (ct or 0) / n, 1) if n else None,
                         "avg_prominence": round(prom or 0, 3)}
        return out
