"""
One-command local dev: runs the API and a worker in one process.

Production runs them as SEPARATE services (see render.yaml). This module exists
only so a developer can clone the repo and see the whole thing work without
Docker, Postgres or Redis.

    python3 -m app.dev
"""
import threading, time, uvicorn
from .config import cfg
from . import db, worker

def _worker():
    time.sleep(1)
    worker.main()

if __name__ == "__main__":
    db.init_db()
    print(f"[dev] {cfg.summary()}")
    print("[dev] API  http://localhost:8000")
    threading.Thread(target=_worker, daemon=True).start()
    uvicorn.run("app.api:app", host="0.0.0.0", port=8000, log_level="warning")
