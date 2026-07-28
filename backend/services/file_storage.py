"""Phase F0 · Feb 2026 — Poolscape CRM file storage service.

Wraps the Emergent Object Storage integration. Fail-soft on missing
``EMERGENT_LLM_KEY`` — the app boots with file storage *disabled*,
uploads return 503, and every caller can query
``is_storage_configured()`` to render an appropriate UI state.

Design invariants
-----------------
* Session-scoped ``_storage_key`` cached after a successful init.
* On any 403 from a downstream call, the cached key is cleared and
  ``init_storage()`` is called ONCE; the request is retried ONCE.
  Further 403 falls through as an exception.
* All requests library exceptions are re-raised as clean
  ``StorageError`` messages so callers can 4xx/5xx without leaking
  provider internals.

This coexists with — but does NOT replace —
``services/marketing_media/storage_client.py``. That module owns the
``pool-crm/marketing_media/`` namespace under a slightly different
call surface (raises ``StorageUnavailable`` on init failure); this
new module owns the ``poolscape-crm/`` namespace with fail-soft
semantics for arbitrary customer / job / persona / portal uploads.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

import requests

from config import logger

STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
APP_NAME = "poolscape-crm"

_storage_key: Optional[str] = None
_init_failed_reason: Optional[str] = None
_DEFAULT_TIMEOUT_S = 15.0


class StorageError(Exception):
    """Non-recoverable file-storage error. Callers should surface a
    5xx to the client with the message."""


def _emergent_key() -> str:
    return (os.environ.get("EMERGENT_LLM_KEY") or "").strip()


def is_storage_configured() -> bool:
    """True iff init() succeeded and a storage_key is cached."""
    return _storage_key is not None


def _reset_for_tests() -> None:
    """Test-only helper — clears module state so each test starts
    with a fresh init cycle."""
    global _storage_key, _init_failed_reason
    _storage_key = None
    _init_failed_reason = None


def init_storage(force: bool = False) -> Optional[str]:
    """Idempotent one-shot init. Returns the session ``storage_key``
    or ``None`` when file storage stays disabled.

    Called once at server startup; also called under the hood after
    a 403 from a downstream call (with ``force=True``).
    """
    global _storage_key, _init_failed_reason
    if _storage_key and not force:
        return _storage_key

    key = _emergent_key()
    if not key:
        _init_failed_reason = "EMERGENT_LLM_KEY not configured"
        logger.warning(
            "[FILE_STORAGE] EMERGENT_LLM_KEY missing — file storage "
            "disabled (uploads/downloads will return 503 until the "
            "env is populated and the backend is restarted)",
        )
        return None

    try:
        r = requests.post(
            f"{STORAGE_URL}/init",
            json={"emergent_key": key},
            timeout=_DEFAULT_TIMEOUT_S,
        )
    except requests.RequestException as e:
        _init_failed_reason = f"init network error: {e}"
        logger.warning("[FILE_STORAGE] init network error: %s", e)
        return None

    if r.status_code != 200:
        _init_failed_reason = f"init HTTP {r.status_code}: {r.text[:200]}"
        logger.warning("[FILE_STORAGE] init failed: %s", _init_failed_reason)
        return None

    try:
        sk = (r.json() or {}).get("storage_key")
    except Exception as e:
        _init_failed_reason = f"init malformed JSON: {e}"
        logger.warning("[FILE_STORAGE] init malformed response: %s", e)
        return None

    if not sk:
        _init_failed_reason = "init response missing storage_key"
        logger.warning("[FILE_STORAGE] init response missing storage_key")
        return None

    _storage_key = sk
    _init_failed_reason = None
    return sk


def _headers() -> dict:
    if not _storage_key:
        raise StorageError("file storage not configured")
    return {"X-Storage-Key": _storage_key}


def _put_once(path: str, data: bytes, content_type: str) -> requests.Response:
    return requests.put(
        f"{STORAGE_URL}/objects/{path}",
        data=data,
        headers={**_headers(), "Content-Type": content_type},
        timeout=_DEFAULT_TIMEOUT_S,
    )


def _get_once(path: str) -> requests.Response:
    return requests.get(
        f"{STORAGE_URL}/objects/{path}",
        headers=_headers(),
        timeout=_DEFAULT_TIMEOUT_S,
    )


def put_object(path: str, data: bytes, content_type: str) -> dict:
    """Upload bytes to ``path`` (which must ALREADY include the
    ``APP_NAME`` prefix — the router builds the path). Returns
    ``{path, size, etag}``.

    Retries ONCE on 403 (session key expired) after a fresh init.
    """
    if not is_storage_configured():
        raise StorageError("file storage not configured")
    try:
        r = _put_once(path, data, content_type)
    except requests.RequestException as e:
        raise StorageError(f"put_object network error: {e}") from e

    if r.status_code == 403:
        logger.warning("[FILE_STORAGE] 403 on put — clearing key + re-init")
        _reset_key_only()
        init_storage(force=True)
        if not is_storage_configured():
            raise StorageError("file storage re-init failed after 403")
        try:
            r = _put_once(path, data, content_type)
        except requests.RequestException as e:
            raise StorageError(f"put_object retry network error: {e}") from e

    if r.status_code >= 400:
        raise StorageError(f"put_object HTTP {r.status_code}: {r.text[:200]}")

    try:
        body = r.json() or {}
    except Exception:
        body = {}

    return {
        "path": body.get("path") or path,
        "size": int(body.get("size") or len(data)),
        "etag": body.get("etag"),
    }


def get_object(path: str) -> Tuple[bytes, str]:
    """Fetch bytes at ``path``. Returns ``(bytes, content_type)``.

    Retries ONCE on 403 after a fresh init.
    """
    if not is_storage_configured():
        raise StorageError("file storage not configured")
    try:
        r = _get_once(path)
    except requests.RequestException as e:
        raise StorageError(f"get_object network error: {e}") from e

    if r.status_code == 403:
        logger.warning("[FILE_STORAGE] 403 on get — clearing key + re-init")
        _reset_key_only()
        init_storage(force=True)
        if not is_storage_configured():
            raise StorageError("file storage re-init failed after 403")
        try:
            r = _get_once(path)
        except requests.RequestException as e:
            raise StorageError(f"get_object retry network error: {e}") from e

    if r.status_code == 404:
        raise StorageError("object not found")
    if r.status_code >= 400:
        raise StorageError(f"get_object HTTP {r.status_code}: {r.text[:200]}")

    ct = r.headers.get("Content-Type", "application/octet-stream")
    return r.content, ct


def _reset_key_only() -> None:
    """Clear ONLY the cached key (keep the last failed_reason for
    diagnostics)."""
    global _storage_key
    _storage_key = None
