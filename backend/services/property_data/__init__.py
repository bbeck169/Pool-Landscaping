"""Task TT · Feb 2026 — Property data adapters.

Currently ships the RapidAPI-Zillow adapter (dry-scaffold) with a
7-day Mongo cache, test-scope guardrails, 429 throttle memo, and a
graceful ``{unavailable: True, reason}`` fallback so no page crashes
when keys are missing.
"""
from services.property_data.zillow_adapter import (  # noqa: F401
    ZillowClient,
    keys_configured,
    startup_log_line,
    REASON_KEYS_NOT_CONFIGURED,
    REASON_QUOTA_EXHAUSTED,
    REASON_TEST_SCOPE_REFUSED,
    REASON_PROVIDER_ERROR,
    REASON_NOT_FOUND,
)
