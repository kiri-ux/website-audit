"""
Artifact storage — crawl artifacts and generated reports.

local://dir  → filesystem (local dev, and fine for a single-box internal deploy)
s3://bucket  → S3 or any S3-compatible store (Cloudflare R2, Backblaze B2)

Deliberately NOT a Render persistent disk: disks pin a service to a single
instance and block zero-downtime deploys. Artifacts are write-once blobs, which
is exactly what object storage is for.
"""
from __future__ import annotations
import os
from urllib.parse import urlparse

from .config import cfg


def _backend():
    u = urlparse(cfg.artifact_store)
    return u.scheme, (u.netloc + u.path).rstrip("/")


def put_artifact(audit_id: str, name: str, data: bytes) -> str:
    scheme, loc = _backend()
    key = f"{audit_id}/{name}"
    if scheme == "s3":
        import boto3
        boto3.client("s3").put_object(Bucket=loc, Key=key, Body=data)
        return f"s3://{loc}/{key}"
    path = os.path.join(loc, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def get_artifact(audit_id: str, name: str) -> bytes | None:
    scheme, loc = _backend()
    key = f"{audit_id}/{name}"
    if scheme == "s3":
        import boto3
        try:
            return boto3.client("s3").get_object(Bucket=loc, Key=key)["Body"].read()
        except Exception:
            return None
    path = os.path.join(loc, key)
    return open(path, "rb").read() if os.path.exists(path) else None


def delete_artifacts(audit_id: str) -> int:
    """
    Remove every blob for an audit. Returns how many were deleted.

    Best-effort by design: a storage failure must not block deleting the audit
    row, or the dashboard ends up showing rows nobody can clear. An orphaned
    blob costs pennies; a row you cannot delete costs trust in the tool.
    """
    scheme, loc = _backend()
    n = 0
    try:
        if scheme == "s3":
            import boto3
            s3 = boto3.client("s3")
            pages = s3.get_paginator("list_objects_v2").paginate(
                Bucket=loc, Prefix=f"{audit_id}/")
            keys = [{"Key": o["Key"]} for p in pages for o in p.get("Contents", [])]
            for i in range(0, len(keys), 1000):
                s3.delete_objects(Bucket=loc, Delete={"Objects": keys[i:i + 1000]})
            n = len(keys)
        else:
            import shutil
            d = os.path.join(loc, audit_id)
            if os.path.isdir(d):
                n = sum(len(fs) for _, _, fs in os.walk(d))
                shutil.rmtree(d, ignore_errors=True)
    except Exception as e:
        print(f"[artifacts] delete skipped for {audit_id}: "
              f"{type(e).__name__}: {e}", flush=True)
    return n
