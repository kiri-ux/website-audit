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
