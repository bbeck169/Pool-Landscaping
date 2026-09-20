"""Phase D6 · Feb-2026 — canonical email-locale resolver.

Every dynamic email composer must resolve the recipient locale
through this helper so the priority order is consistent everywhere.

Priority order (per the D6 spec):

    override → recipient.locale → tenant.default_locale → "en"

Where ``recipient`` is either a ``customer`` doc (send-to-customer
paths) or a ``user`` doc (send-to-tech / send-to-admin paths). Only
the ``locale`` field on the doc is inspected — the caller is
responsible for passing the right doc.

The heavy lifting (BCP-47 region trim, unknown-locale coercion) is
delegated to :func:`services.i18n_notifications.resolve_recipient_locale`
so the coercion contract stays identical to the D5 SMS + email
template pipeline.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from services.i18n_notifications import (
    FALLBACK_LOCALE,
    SUPPORTED_LOCALES,
    _normalise_locale,
    resolve_recipient_locale,
)

__all__ = [
    "FALLBACK_LOCALE",
    "SUPPORTED_LOCALES",
    "resolve_email_locale",
]


def resolve_email_locale(
    *,
    recipient: Optional[Mapping[str, Any]] = None,
    tenant: Optional[Mapping[str, Any]] = None,
    override: Any = None,
) -> str:
    """Return the outbound locale for an email recipient.

    :param recipient: A customer / user document with an optional
        ``locale`` field. May be ``None`` (system emails, no
        addressable recipient — falls through to ``tenant`` then
        ``en``).
    :param tenant: A tenant doc with an optional
        ``default_locale`` field. May be ``None``.
    :param override: An explicit locale override (e.g. an admin
        preview endpoint choosing the render language). Wins over
        everything else when non-empty and supported. Unknown
        overrides silently coerce to ``en`` per the shared D5
        contract.
    :returns: One of the supported locales (currently ``en`` /
        ``es`` / ``fr``). Never raises.
    """
    if override:
        return _normalise_locale(override)
    # Delegate to the D5 resolver for the recipient → tenant → en
    # chain. Pass the recipient as ``customer`` — the audience-based
    # branching in the D5 helper only matters for the tech override
    # semantics which D6 email flows don't need (a tech email flow
    # will pass its user doc as ``recipient`` and it lands in the
    # same locale slot). Explicit ``audience="customer"`` keeps the
    # fallback chain uniform for all D6 callers.
    return resolve_recipient_locale(
        customer=recipient, tenant=tenant, audience="customer",
    )
