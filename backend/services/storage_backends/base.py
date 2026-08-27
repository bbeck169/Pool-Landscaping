"""Feb 2026 · Storage backend abstract interface.

Every storage backend (Emergent Object Storage today, AWS S3 tomorrow
as overflow) implements the same small API so ``services.storage_router``
can swap them without every caller learning about backend types.

The interface is deliberately narrow — the 5 methods every current
caller uses — plus ``get_capacity_info`` for the overflow decision.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple


class StorageBackendError(RuntimeError):
    """Base error type for anything a backend intentionally raises."""


class StorageBackendUnavailable(StorageBackendError):
    """Raised when the backend can't be reached at all (network down,
    creds missing, service disabled). The router uses this signal to
    decide whether to fail hard or fall back to another backend."""


@dataclass(frozen=True)
class CapacityInfo:
    """Snapshot of how full a backend is right now.

    * ``used_bytes`` — bytes we've written to this backend that we
      still count as "resident" (deletes decrement; failures don't
      count).
    * ``quota_bytes`` — plan limit. ``None`` when the backend has no
      quota (e.g. S3 unbounded on paid tiers).
    * ``percent_used`` — 0-100 float. When ``quota_bytes`` is
      ``None``, returned as ``0.0`` (never triggers overflow).
    * ``source`` — which mechanism produced the numbers ("api",
      "counter", "unavailable"). Debugging aid.
    """
    used_bytes: int
    quota_bytes: Optional[int]
    percent_used: float
    source: str = "counter"


class StorageBackend(ABC):
    """Abstract storage backend. Sync API — every current caller is
    sync (``routers/*.py`` mostly), and Motor/asyncio-friendly wrappers
    live one layer up (the router facade)."""

    name: str = "abstract"

    # ── Introspection ─────────────────────────────────────────────
    @abstractmethod
    def is_ready(self) -> bool:
        """True when this backend can accept writes right now. False
        for the S3 placeholder when creds are missing, for example."""

    @abstractmethod
    def get_capacity_info(self) -> CapacityInfo:
        """Return current usage/quota. Cheap — the router caches for
        60s so implementations don't need to."""

    # ── Path helpers ──────────────────────────────────────────────
    def build_path(self, tenant_id: str, entity_kind: str,
                     entity_id: str, filename: str) -> str:
        """Default path shape — Emergent-inspired, but callers can
        override. Backends usually accept whatever we hand them."""
        return f"poolcrm/{tenant_id}/{entity_kind}/{entity_id}/{filename}"

    # ── Object CRUD ───────────────────────────────────────────────
    @abstractmethod
    def put_object(self, path: str, data: bytes,
                     content_type: str) -> str:
        """Persist ``data`` under ``path``. Returns the canonical URL
        that should be stored in the DB (usually ``/api/objects/{path}``
        for the retrieval router in ``routers/objects.py``)."""

    @abstractmethod
    def get_object(self, path: str) -> Tuple[bytes, str]:
        """Return ``(bytes, content_type)`` for ``path``. Raises when
        missing / permission-denied."""

    @abstractmethod
    def delete_object(self, path: str) -> bool:
        """Delete ``path``. Returns True on success, False when the
        object didn't exist. Never raises for missing objects."""

    # ── Optional: signed URLs ─────────────────────────────────────
    def sign_url(self, path: str, ttl_seconds: int = 3600) -> str:
        """Return a time-limited signed URL to ``path``. Backends
        without signed-URL support may return the plain retrieval
        URL; that's fine for our internal ``/api/objects`` router."""
        return f"/api/objects/{path}"
