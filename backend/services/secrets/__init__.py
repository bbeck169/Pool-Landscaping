"""Phase I1.7.a · Feb-2026 — Encrypted tenant-secret store.

Public API:
    from services.secrets import (
        put_secret, get_secret, remove_secret,
        list_connections, connection_summary,
    )

All plaintext handling lives inside this package. Nothing outside
this package should ever see a plaintext secret again — callers
receive either the plaintext string (from ``get_secret``, when
they need to sign a request) or a "safe summary" (last-4 + status
flags) via ``list_connections``.
"""
from .store import (  # noqa: F401
    put_secret,
    get_secret,
    remove_secret,
    list_connections,
    connection_summary,
    mark_used,
    log_error,
)
from .models import (  # noqa: F401
    TenantSecret,
    ConnectionStatus,
    ConnectionType,
    ConnectionSummary,
)
