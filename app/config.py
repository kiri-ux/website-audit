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
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    # ---- storage -------------------------------------------------------
    # sqlite:///path  (local, default)  |  postgres://...  (production)
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///data/vici.db")

    # ---- queue ---------------------------------------------------------
    # Absent  -> DB-backed queue (SKIP LOCKED semantics emulated). Fine for
    #            single-worker internal use and for the POC.
    # Present -> Redis list queue, for multi-worker production.
    redis_url: str | None = os.getenv("REDIS_URL") or None

    # ---- artifact storage ----------------------------------------------
    # local://dir  (default)  |  s3://bucket  (production)
    artifact_store: str = os.getenv("ARTIFACT_STORE", "local://data/artifacts")

    # ---- tenancy -------------------------------------------------------
    # "internal": single implicit tenant, no auth, everything visible.
    # "partner":  every row scoped by partner_id, API-key auth enforced.
    # The schema carries partner_id in BOTH modes so the switch is a config
    # change, never a migration. See app/tenancy.py.
    mode: str = os.getenv("APP_MODE", "internal")
    default_partner: str = os.getenv("DEFAULT_PARTNER", "vici-internal")

    # ---- crawl defaults -------------------------------------------------
    max_pages: int = int(os.getenv("CRAWL_MAX_PAGES", "150"))
    max_depth: int = int(os.getenv("CRAWL_MAX_DEPTH", "4"))
    crawl_delay: float = float(os.getenv("CRAWL_DELAY", "0.25"))
    render_js: bool = _b("CRAWL_RENDER_JS", False)
    user_agent: str = os.getenv(
        "CRAWL_USER_AGENT",
        "ViciAuditBot/1.0 (+https://vicimediainc.com/bot; SEO audit crawler)")

    # ---- collectors ------------------------------------------------------
    psi_key: str | None = os.getenv("PSI_API_KEY") or None
    skip_psi: bool = _b("SKIP_PSI", False)

    # ---- worker ----------------------------------------------------------
    worker_concurrency: int = int(os.getenv("WORKER_CONCURRENCY", "1"))
    job_timeout_s: int = int(os.getenv("JOB_TIMEOUT_S", "3600"))
    poll_interval_s: float = float(os.getenv("POLL_INTERVAL_S", "2"))

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
