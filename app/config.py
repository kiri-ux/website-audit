"""
Environment-driven configuration.

One deliberate design choice runs through this file: **every backend has a
zero-dependency local implementation and a production implementation, chosen by
env var.** Local dev needs no Postgres, no Redis, no Docker — `python3 -m app.dev`
just works. Production swaps both by setting DATABASE_URL and REDIS_URL.

That is what keeps the POC runnable by any dev in under a minute while the
production topology stays honest.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field


def _b(name: str, default: bool = False) -> bool:
    return _s(name, str(default)).lower() in ("1", "true", "yes", "on")


def _s(name: str, default: str = "") -> str:
    """
    Read an env var, treating EMPTY as unset.

    Render's blueprint UI creates a variable for every `sync: false` key whether
    or not you type a value, so a skipped field arrives as "" rather than being
    absent. Plain os.getenv(name, default) would then hand the rest of the app an
    empty string instead of the default — which silently breaks the artifact
    store and any other var with a meaningful fallback.
    """
    v = os.getenv(name)
    return v.strip() if v and v.strip() else default


@dataclass
class Config:
    # ---- storage -------------------------------------------------------
    # sqlite:///path  (local, default)  |  postgres://...  (production)
    database_url: str = _s("DATABASE_URL", "sqlite:///data/vici.db")

    # ---- queue ---------------------------------------------------------
    # Absent  -> DB-backed queue (SKIP LOCKED semantics emulated). Fine for
    #            single-worker internal use and for the POC.
    # Present -> Redis list queue, for multi-worker production.
    redis_url: str | None = _s("REDIS_URL") or None

    # ---- artifact storage ----------------------------------------------
    # local://dir  (default)  |  s3://bucket  (production)
    artifact_store: str = _s("ARTIFACT_STORE", "local://data/artifacts")

    # ---- tenancy -------------------------------------------------------
    # "internal": single implicit tenant, no auth, everything visible.
    # "partner":  every row scoped by partner_id, API-key auth enforced.
    # The schema carries partner_id in BOTH modes so the switch is a config
    # change, never a migration. See app/tenancy.py.
    mode: str = _s("APP_MODE", "internal")
    default_partner: str = _s("DEFAULT_PARTNER", "vici-internal")

    # ---- crawl defaults -------------------------------------------------
    max_pages: int = int(_s("CRAWL_MAX_PAGES", "150"))
    max_depth: int = int(_s("CRAWL_MAX_DEPTH", "4"))
    crawl_delay: float = float(_s("CRAWL_DELAY", "0.25"))
    # Wall-clock ceiling for one crawl. A worker held for 45 minutes by a slow
    # or hostile host is indistinguishable from a hang.
    crawl_max_seconds: int = int(_s("CRAWL_MAX_SECONDS", "600"))
    render_js: bool = _b("CRAWL_RENDER_JS", False)
    # Honest bot identification is the right default. Some WAFs answer it with an
    # empty shell, which the crawl-quality gate now detects; BROWSER_UA is the
    # documented remedy for sites you have permission to audit.
    user_agent: str = _s(
        "CRAWL_USER_AGENT",
        "ViciAuditBot/1.0 (+https://vicimediainc.com/bot; SEO audit crawler)")

    # ---- report authorship -----------------------------------------------
    # A report with a name on it reads as work someone did; an unsigned one
    # reads as output something produced. This costs nothing and changes how
    # the deliverable is received, so it is first-class config rather than a
    # template string buried in the renderer.
    analyst_name: str = _s("ANALYST_NAME")
    analyst_title: str = _s("ANALYST_TITLE", "SEO & GEO Analyst")
    analyst_email: str = _s("ANALYST_EMAIL")
    firm_name: str = _s("FIRM_NAME", "Vici Media")

    # ---- collectors ------------------------------------------------------
    psi_key: str | None = _s("PSI_API_KEY") or None
    skip_psi: bool = _b("SKIP_PSI", False)

    # ---- worker ----------------------------------------------------------
    worker_concurrency: int = int(_s("WORKER_CONCURRENCY", "1"))
    job_timeout_s: int = int(_s("JOB_TIMEOUT_S", "3600"))
    poll_interval_s: float = float(_s("POLL_INTERVAL_S", "2"))

    @property
    def is_partner_mode(self) -> bool:
        return self.mode == "partner"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgres://", "postgresql://"))

    @property
    def sqlite_path(self) -> str:
        return self.database_url.replace("sqlite:///", "", 1)

    def summary(self) -> str:
        return (f"mode={self.mode} db={'postgres' if self.is_postgres else 'sqlite'} "
                f"queue={'redis' if self.redis_url else 'db'} "
                f"artifacts={self.artifact_store.split('://')[0]}")


cfg = Config()
