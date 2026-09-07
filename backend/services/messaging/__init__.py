"""Phase I1.7.b · Feb-2026 — Tenant-scoped messaging providers.

Sibling of ``services.payments`` — provides tenant-aware SMS + Email
adapters so each tenant can bring their own Twilio / SendGrid / etc.
credentials. All plaintext lives inside ``services.secrets``; every
adapter re-reads the tenant's credential on every call so revocations
take effect immediately.

Public entry points (imported here for convenience):

    from services.messaging import (
        dispatch_sms, dispatch_email,
        get_tenant_sms_provider, get_tenant_email_provider,
    )

The ``dispatch_*`` helpers are the tenant-first entry points: they
route through the tenant's provider when one is configured, else
fall back to the legacy platform default (``comms_sms_adapter`` /
``comms_email_adapter``) and log the fallback to
``platform_messaging_fallback_log``.
"""
from .dispatch import (  # noqa: F401
    dispatch_sms,
    dispatch_email,
    FALLBACK_LOG_COLLECTION,
)
from .sms.registry import (  # noqa: F401
    get_sms_provider,
    get_tenant_sms_provider,
    list_registered_sms_provider_keys,
)
from .email.registry import (  # noqa: F401
    get_email_provider,
    get_tenant_email_provider,
    list_registered_email_provider_keys,
)
