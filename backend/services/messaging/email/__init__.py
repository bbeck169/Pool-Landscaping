"""Phase I1.7.b · Feb-2026 — Email providers package."""
from .base import EmailProvider  # noqa: F401
from .registry import (  # noqa: F401
    get_email_provider,
    get_tenant_email_provider,
    list_registered_email_provider_keys,
    register_email_provider,
    reset_cache_for_tests,
)
