"""Task TT / TT.5 · Feb 2026 — Property data adapters.

Currently ships the OpenWebNinja-Zillow adapter (dry-scaffold) with a
7-day Mongo cache, test-scope guardrails, 429 throttle memo, and a
graceful ``{unavailable: True, reason}`` fallback so no page crashes
when the key is missing.
"""
from services.property_data.zillow_adapter import (  # noqa: F401
    ZillowClient,
    keys_configured,
    startup_log_line,
    PROVIDER_NAME,
    PROVIDER_BASE_URL,
    REASON_KEYS_NOT_CONFIGURED,
    REASON_QUOTA_EXHAUSTED,
    REASON_TEST_SCOPE_REFUSED,
    REASON_PROVIDER_ERROR,
    REASON_NOT_FOUND,
)
