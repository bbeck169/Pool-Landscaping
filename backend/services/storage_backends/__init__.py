"""Feb 2026 · Storage backend adapter package.

Introduces a small abstract interface (``StorageBackend``) plus two
implementations:

* ``EmergentStorageBackend`` — primary backend, wraps the existing
  ``services.object_storage`` module.
* ``S3StorageBackend`` — **overflow placeholder only**. Every method
  raises ``NotImplementedError("s3_backend_not_configured")`` until an
  operator adds ``boto3`` + AWS creds. Kept as scaffolding for the
  ``STORAGE_BACKEND_MODE = auto`` path in ``services.storage_router``.

Callers **do not import from this package directly**. Existing code
continues to call ``services.object_storage.put_object`` (and so on);
the router (``services.storage_router``) is what selects the backend
at runtime for future consumers who want mode-aware routing.
"""
from .base import (
    CapacityInfo,
    StorageBackend,
    StorageBackendError,
    StorageBackendUnavailable,
)
from .emergent import EmergentStorageBackend
from .s3 import S3StorageBackend

__all__ = [
    "CapacityInfo",
    "StorageBackend",
    "StorageBackendError",
    "StorageBackendUnavailable",
    "EmergentStorageBackend",
    "S3StorageBackend",
]
