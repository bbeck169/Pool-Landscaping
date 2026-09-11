"""Feb-2026 · Photos-in-S3 Phase 1 · S3 service module.

Wraps ``boto3`` to keep every AWS surface behind ``PHOTOS_S3_ENABLED``.
When the flag is off, or when creds/bucket are missing, every helper
becomes a no-op that returns ``None`` / ``False`` — the caller MUST
treat those returns as "S3 unavailable, use the DB fallback".

Contract used by the dual-write photo upload:

  * ``upload_photo`` returns the S3 key on success, ``None`` on
    disabled/failure.
  * ``generate_signed_url`` returns a presigned GET URL on success,
    ``None`` on disabled/failure.
  * ``delete_photo`` returns ``True`` on success, ``False`` on
    disabled/failure. NEVER raises.
  * ``check_object_exists`` returns ``True`` if the key is present
    in the bucket, ``False`` otherwise (or on disabled/failure).
  * ``health_check`` returns a dict describing the config state and
    a tiny write-then-delete self-test result. Used by the admin
    ``GET /api/admin/s3/health`` endpoint.

Every function is safe to call regardless of environment state.
Callers should never wrap these in ``try/except`` — this module
does that internally and reports failures via return-value.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Env-driven config — read once at process boot. If the operator
# rotates creds via ``.env`` + supervisor restart, this module will
# pick up new values on the next boot.
# ─────────────────────────────────────────────────────────────────
def _cfg() -> Dict[str, Any]:
    """Load env config lazily so tests can monkeypatch environ."""
    return {
        "enabled": (os.environ.get("PHOTOS_S3_ENABLED", "false")
                    or "false").strip().lower() == "true",
        "access_key": (os.environ.get("AWS_ACCESS_KEY_ID") or "").strip(),
        "secret_key": (os.environ.get("AWS_SECRET_ACCESS_KEY") or "").strip(),
        "region":     (os.environ.get("AWS_REGION") or "us-east-1").strip(),
        "bucket":     (os.environ.get("AWS_S3_BUCKET") or "").strip(),
        "prefix":     (os.environ.get("AWS_S3_PREFIX") or "job-photos/").strip(),
        "ttl":        _int_or_default(os.environ.get("AWS_S3_SIGNED_URL_TTL"),
                                        default=3600, minimum=60, maximum=86400),
    }


def _int_or_default(raw: Optional[str], *, default: int,
                     minimum: int, maximum: int) -> int:
    try:
        v = int(str(raw or "").strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, v))


def _is_configured(cfg: Dict[str, Any]) -> bool:
    """S3 is USABLE only when flag ON + bucket + access/secret set."""
    return bool(cfg["enabled"] and cfg["bucket"]
                and cfg["access_key"] and cfg["secret_key"])


def _client(cfg: Optional[Dict[str, Any]] = None):
    """Build a boto3 S3 client. Returns ``None`` if boto3 isn't
    importable OR config isn't complete. Never raises."""
    cfg = cfg or _cfg()
    if not _is_configured(cfg):
        return None
    try:
        import boto3  # noqa: local import so this module loads without boto3.
        from botocore.config import Config as _BotoConfig
    except Exception as exc:
        logger.warning("[photos-s3] boto3 import failed: %s", exc)
        return None
    try:
        # Feb-2026 · Force SigV4 + virtual-host addressing so presigned
        # URLs point at the region-specific vhost
        # (``<bucket>.s3.<region>.amazonaws.com``). Without this,
        # boto3 defaults for us-east-* can emit a legacy
        # ``<bucket>.s3.amazonaws.com`` URL — the sig is scoped to
        # the correct region but the host mismatches, so S3 returns
        # a 307 PermanentRedirect, and following it (Host header
        # changes) invalidates the signature → 403.
        return boto3.client(
            "s3",
            region_name=cfg["region"],
            aws_access_key_id=cfg["access_key"],
            aws_secret_access_key=cfg["secret_key"],
            config=_BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
            ),
        )
    except Exception as exc:
        logger.warning("[photos-s3] boto3 client build failed: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────
# Key format — deterministic + tenant-scoped so the migration
# script (Phase 2) can dry-run against the same shape.
#
# Full key: ``{PREFIX}{tenant_id}/{job_id}/{photo_id}``
#
# Path-traversal / slash-injection resistant: every component
# is validated against a strict [A-Za-z0-9_.-] charset.
# ─────────────────────────────────────────────────────────────────
_SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _safe_component(name: str, kind: str) -> str:
    if not isinstance(name, str) or not _SAFE.match(name):
        raise ValueError(f"[photos-s3] unsafe {kind}: {name!r}")
    return name


def build_key(tenant_id: str, job_id: str, photo_id: str,
              *, prefix: Optional[str] = None) -> str:
    """Compose the canonical S3 key. Path-traversal-safe."""
    cfg = _cfg()
    p = (prefix if prefix is not None else cfg["prefix"]) or ""
    if p and not p.endswith("/"):
        p = p + "/"
    return (f"{p}"
            f"{_safe_component(tenant_id, 'tenant_id')}/"
            f"{_safe_component(job_id, 'job_id')}/"
            f"{_safe_component(photo_id, 'photo_id')}")


# ─────────────────────────────────────────────────────────────────
# Data-URL helpers — the current photo write path stamps
# ``photos[].data`` as ``"data:image/jpeg;base64,<blob>"``. We
# decode + reconstruct MIME so the S3 object carries the right
# ``ContentType``.
# ─────────────────────────────────────────────────────────────────
def decode_data_url(data_url: str) -> tuple[bytes, str]:
    """Decode a ``data:<mime>;base64,<b64>`` URL. Returns ``(bytes,
    mime)``. Falls back to ``image/jpeg`` if the header is missing.
    Raises ``ValueError`` if the base64 payload is invalid."""
    if not isinstance(data_url, str) or not data_url:
        raise ValueError("empty data URL")
    if "," in data_url:
        header, b64 = data_url.split(",", 1)
        mime = "image/jpeg"
        if header.startswith("data:"):
            mime_part = header[len("data:"):].split(";", 1)[0]
            if mime_part:
                mime = mime_part
    else:
        b64, mime = data_url, "image/jpeg"
    return base64.b64decode(b64), mime


# ─────────────────────────────────────────────────────────────────
# Public API — every function returns a fallback value on failure,
# NEVER raises. Callers guard on the return value.
# ─────────────────────────────────────────────────────────────────
def upload_photo(tenant_id: str, job_id: str, photo_id: str,
                  blob: bytes, mime: str) -> Optional[str]:
    """Upload ``blob`` to S3 with SSE-S3 + correct ContentType.
    Returns the S3 key on success, ``None`` if S3 is disabled or
    the upload fails. Never raises.
    """
    cfg = _cfg()
    client = _client(cfg)
    if client is None:
        return None
    try:
        key = build_key(tenant_id, job_id, photo_id)
    except ValueError as exc:
        logger.warning("[photos-s3] key build failed: %s", exc)
        return None
    try:
        client.put_object(
            Bucket=cfg["bucket"],
            Key=key,
            Body=blob,
            ContentType=(mime or "image/jpeg"),
            ServerSideEncryption="AES256",
        )
    except Exception as exc:
        logger.warning(
            "[photos-s3] put_object failed tenant=%s job=%s photo=%s err=%s",
            tenant_id, job_id, photo_id, exc,
        )
        return None
    return key


def generate_signed_url(s3_key: str,
                         ttl_seconds: Optional[int] = None) -> Optional[str]:
    """Return a presigned GET URL for ``s3_key``. TTL is clamped
    to [60, 86400] seconds regardless of caller value."""
    cfg = _cfg()
    client = _client(cfg)
    if client is None or not s3_key:
        return None
    ttl = _int_or_default(str(ttl_seconds) if ttl_seconds is not None else None,
                          default=cfg["ttl"], minimum=60, maximum=86400)
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": cfg["bucket"], "Key": s3_key},
            ExpiresIn=ttl,
        )
    except Exception as exc:
        logger.warning("[photos-s3] presign failed key=%s err=%s",
                        s3_key, exc)
        return None


def delete_photo(s3_key: str) -> bool:
    """Delete an object. Returns ``True`` on success, ``False`` on
    disabled/failure. Never raises."""
    cfg = _cfg()
    client = _client(cfg)
    if client is None or not s3_key:
        return False
    try:
        client.delete_object(Bucket=cfg["bucket"], Key=s3_key)
        return True
    except Exception as exc:
        logger.warning("[photos-s3] delete_object failed key=%s err=%s",
                        s3_key, exc)
        return False


def check_object_exists(s3_key: str) -> bool:
    """HEAD-check an object. Returns ``True`` if present. Used by
    the Phase 2 migration for idempotent re-runs."""
    cfg = _cfg()
    client = _client(cfg)
    if client is None or not s3_key:
        return False
    try:
        client.head_object(Bucket=cfg["bucket"], Key=s3_key)
        return True
    except Exception:
        return False


def health_check() -> Dict[str, Any]:
    """Report config state + tiny write-then-delete self-test.
    Used by ``GET /api/admin/s3/health``. Never raises."""
    cfg = _cfg()
    result: Dict[str, Any] = {
        "enabled":        cfg["enabled"],
        "bucket_set":     bool(cfg["bucket"]),
        "creds_set":      bool(cfg["access_key"] and cfg["secret_key"]),
        "region":         cfg["region"],
        "prefix":         cfg["prefix"],
        "signed_ttl":     cfg["ttl"],
        "status":         "disabled",  # overwritten below if applicable
        "self_test":      None,
    }
    if not cfg["enabled"]:
        result["status"] = "disabled"
        return result
    if not _is_configured(cfg):
        result["status"] = "misconfigured"
        return result
    client = _client(cfg)
    if client is None:
        result["status"] = "client_unavailable"
        return result
    # Self-test — write a tiny sentinel object, verify HEAD, delete.
    probe_key = f"{cfg['prefix']}_healthcheck/{uuid.uuid4().hex}.txt"
    t0 = time.time()
    try:
        client.put_object(
            Bucket=cfg["bucket"], Key=probe_key,
            Body=b"ok", ContentType="text/plain",
            ServerSideEncryption="AES256",
        )
        client.head_object(Bucket=cfg["bucket"], Key=probe_key)
        client.delete_object(Bucket=cfg["bucket"], Key=probe_key)
        result["status"] = "healthy"
        result["self_test"] = {
            "ok": True,
            "roundtrip_ms": int((time.time() - t0) * 1000),
            "probe_key":    probe_key,
        }
    except Exception as exc:
        result["status"] = "unhealthy"
        result["self_test"] = {"ok": False, "error": str(exc)}
    return result
