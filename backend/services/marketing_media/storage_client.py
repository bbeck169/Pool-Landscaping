"""Phase 9C · Feb 2026 — Emergent Object Storage client.

Session-scoped ``storage_key`` initialised once at process boot. All
paths are prefixed with ``pool-crm/tenants/{tenant_id}/marketing_media/``
to keep tenants isolated within the shared bucket.

Downloads never expose a direct storage URL to the frontend — every
image is served via the backend proxy at
``GET /api/marketing/media/{id}/download`` so tenant boundaries are
enforced.

Playbook source: Emergent Object Storage integration (Feb 2026).
"""
from __future__ import annotations

import os
import time
from typing import Optional, Tuple

import requests

from config import logger

STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
APP_PREFIX = "pool-crm"

_storage_key: Optional[str] = None


class StorageUnavailable(Exception):
    """Raised when the Emergent Object Storage service is not reachable
    or the ``EMERGENT_LLM_KEY`` is unset. Callers should surface a 503
    rather than fall back to any local-disk / base64 store."""


def _emergent_key() -> str:
    k = os.environ.get("EMERGENT_LLM_KEY") or ""
    if not k:
        raise StorageUnavailable(
            "EMERGENT_LLM_KEY not configured — media library disabled"
        )
    return k


def init_storage(force: bool = False) -> str:
    """Idempotent init. Returns the session-scoped ``storage_key``.
    Re-called (with ``force=True``) after a 403 (expired key)."""
    global _storage_key
    if _storage_key and not force:
        return _storage_key
    key = _emergent_key()
    try:
        r = requests.post(f"{STORAGE_URL}/init",
                            json={"emergent_key": key}, timeout=30)
    except Exception as exc:
        raise StorageUnavailable(f"storage init failed: {exc}")
    if r.status_code != 200:
        raise StorageUnavailable(
            f"storage init returned {r.status_code}: {r.text[:200]}"
        )
    _storage_key = r.json().get("storage_key")
    if not _storage_key:
        raise StorageUnavailable("storage init returned no storage_key")
    logger.info("[phase9c] Emergent Object Storage initialised")
    return _storage_key


def put_object(path: str, data: bytes, content_type: str,
                 max_retries: int = 3) -> dict:
    """Upload bytes at ``path``. Retries on 403 (fresh storage_key) and
    429 (exponential backoff). Returns the storage server's response
    dict — the canonical ``path`` is what came back, always."""
    for attempt in range(1, max_retries + 1):
        key = init_storage(force=(attempt > 1))
        try:
            r = requests.put(
                f"{STORAGE_URL}/objects/{path}",
                headers={"X-Storage-Key": key,
                          "Content-Type": content_type},
                data=data, timeout=120,
            )
        except Exception as exc:
            if attempt == max_retries:
                raise StorageUnavailable(f"put failed: {exc}")
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 403 and attempt < max_retries:
            continue  # will force-refresh storage_key next iteration
        if r.status_code == 429 and attempt < max_retries:
            time.sleep(2 ** attempt)
            continue
        raise StorageUnavailable(f"put returned {r.status_code}: {r.text[:200]}")
    raise StorageUnavailable("put exhausted retries")


def get_object(path: str, max_retries: int = 3) -> Tuple[bytes, str]:
    """Download bytes at ``path``. Returns (bytes, content_type)."""
    for attempt in range(1, max_retries + 1):
        key = init_storage(force=(attempt > 1))
        try:
            r = requests.get(
                f"{STORAGE_URL}/objects/{path}",
                headers={"X-Storage-Key": key}, timeout=60,
            )
        except Exception as exc:
            if attempt == max_retries:
                raise StorageUnavailable(f"get failed: {exc}")
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            return r.content, r.headers.get("Content-Type",
                                                "application/octet-stream")
        if r.status_code == 404:
            raise StorageUnavailable("object not found")
        if r.status_code == 403 and attempt < max_retries:
            continue
        raise StorageUnavailable(f"get returned {r.status_code}: {r.text[:200]}")
    raise StorageUnavailable("get exhausted retries")


def build_path(tenant_id: str, uuid_ext: str) -> str:
    """Compose the canonical object path. Never has a leading slash;
    always tenant-scoped."""
    return f"{APP_PREFIX}/tenants/{tenant_id}/marketing_media/{uuid_ext}"
