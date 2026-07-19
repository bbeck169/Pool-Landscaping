"""Emergent object storage adapter — Phase 5A (Feb 2026, Video Uploads).

First blob-storage integration in this codebase. Follows the verified
``integration_playbook_expert_v2`` playbook: session-scoped ``storage_key``
initialised once via ``POST /init``, subsequent ``PUT`` / ``GET`` calls carry
that key in an ``X-Storage-Key`` header.

The module is designed to fail *gracefully*:

* If ``EMERGENT_LLM_KEY`` is missing → ``init_storage()`` logs and no-ops,
  ``is_ready()`` returns False, and downstream upload endpoints return 503.
* If the ``/init`` call errors → same handling. Endpoints stay reachable but
  refuse new writes.
* If a subsequent ``PUT`` / ``GET`` gets a 403 (expired ``storage_key``) →
  the wrapper transparently re-inits and retries once.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
APP_NAME = "poolcrm"

# Session-scoped, module-level. Reused by every put/get call.
_storage_key: Optional[str] = None
_initialized: bool = False


def _emergent_key() -> str:
    return (os.environ.get("EMERGENT_LLM_KEY") or "").strip()


def init_storage(force: bool = False) -> Optional[str]:
    """Initialise the storage session key. Idempotent.

    * ``force=True`` re-issues even if we already have a key (used when a
      subsequent request gets a 403 with an expired key).
    * Returns the storage key on success, ``None`` on failure.
    * NEVER raises — callers see the ``None`` and disable the feature.
    """
    global _storage_key, _initialized

    key = _emergent_key()
    if not key:
        _initialized = True  # we've *decided*; feature is disabled
        _storage_key = None
        logger.warning("[object_storage] EMERGENT_LLM_KEY missing — video uploads disabled")
        return None

    if _storage_key and not force:
        return _storage_key

    try:
        resp = requests.post(
            f"{STORAGE_URL}/init", json={"emergent_key": key}, timeout=30,
        )
        resp.raise_for_status()
        _storage_key = resp.json().get("storage_key")
        _initialized = True
        if not _storage_key:
            logger.error("[object_storage] /init returned no storage_key — disabling")
            return None
        logger.info("[object_storage] Storage session key initialised")
        return _storage_key
    except Exception as e:
        _initialized = True  # tried, failed — do not retry on every request
        _storage_key = None
        logger.error(f"[object_storage] init failed: {e}")
        return None


def is_ready() -> bool:
    """True if a valid storage_key is cached. Endpoints gate on this."""
    return bool(_storage_key)


def build_path(tenant_id: str, entity_kind: str, entity_id: str, filename: str) -> str:
    """Canonical storage path. UUID-based filename component prevents
    collisions. Path is app-prefixed to avoid bucket-wide clashes with
    other Emergent-hosted apps sharing the same account.
    """
    ext = (filename.rsplit(".", 1)[-1] if "." in (filename or "") else "bin").lower()
    ext = "".join(c for c in ext if c.isalnum())[:8] or "bin"
    # NOTE: caller supplies the UUID in `filename` (e.g., "abcd...mp4") so
    # this helper only worries about the enclosing directory. Kept as a
    # separate helper so the router can log the canonical path pre-put.
    return f"{APP_NAME}/{tenant_id}/{entity_kind}/{entity_id}/{filename}"


def _headers_for(content_type: Optional[str] = None) -> dict:
    h = {"X-Storage-Key": _storage_key or ""}
    if content_type:
        h["Content-Type"] = content_type
    return h


def put_object(path: str, data: bytes, content_type: str) -> dict:
    """Upload bytes at ``path``. Returns Emergent's response dict
    (contains at least ``path``, ``size``, and optionally ``etag``).

    Raises ``RuntimeError`` on failure. Callers should surface a 5xx.
    """
    if not is_ready():
        init_storage()
        if not is_ready():
            raise RuntimeError("Object storage not initialised")

    def _do_put():
        return requests.put(
            f"{STORAGE_URL}/objects/{path}",
            headers=_headers_for(content_type),
            data=data, timeout=180,
        )

    resp = _do_put()
    if resp.status_code == 403:
        # Storage key expired — re-init and retry once.
        logger.info("[object_storage] PUT got 403; re-initialising and retrying")
        init_storage(force=True)
        resp = _do_put()
    if resp.status_code >= 400:
        raise RuntimeError(
            f"put_object failed [{resp.status_code}]: {resp.text[:400]}"
        )
    try:
        body = resp.json()
    except Exception:
        body = {}
    body.setdefault("path", path)
    body.setdefault("size", len(data))
    return body


def get_object(path: str) -> tuple[bytes, str]:
    """Download bytes for ``path``. Returns ``(content, content_type)``.

    Raises ``RuntimeError`` on failure. Emergent storage does not
    document ``Range`` support — this wrapper always returns the full
    object. HTML5 ``<video>`` scrubbing will still work; it just
    re-fetches on each seek.
    """
    if not is_ready():
        init_storage()
        if not is_ready():
            raise RuntimeError("Object storage not initialised")

    def _do_get():
        return requests.get(
            f"{STORAGE_URL}/objects/{path}",
            headers=_headers_for(), timeout=180,
        )

    resp = _do_get()
    if resp.status_code == 403:
        logger.info("[object_storage] GET got 403; re-initialising and retrying")
        init_storage(force=True)
        resp = _do_get()
    if resp.status_code >= 400:
        raise RuntimeError(
            f"get_object failed [{resp.status_code}]: {resp.text[:400]}"
        )
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")
