"""Phase I1.7.b · Feb-2026 — Email provider registry."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from services.secrets import connection_summary

from ..models import UnknownMessagingProvider
from .base import EmailProvider
from .mailgun_provider import MailgunEmailProvider
from .postmark_provider import PostmarkEmailProvider
from .resend_provider import ResendEmailProvider
from .sendgrid_provider import SendGridEmailProvider
from .smtp_provider import SmtpEmailProvider


_EMAIL_PROVIDER_CLASSES: Dict[str, Type[EmailProvider]] = {
    ResendEmailProvider.provider_key: ResendEmailProvider,
    SendGridEmailProvider.provider_key: SendGridEmailProvider,
    PostmarkEmailProvider.provider_key: PostmarkEmailProvider,
    MailgunEmailProvider.provider_key: MailgunEmailProvider,
    SmtpEmailProvider.provider_key: SmtpEmailProvider,
}
_EMAIL_PROVIDER_CACHE: Dict[str, EmailProvider] = {}


def register_email_provider(key: str, cls: Type[EmailProvider]) -> None:
    _EMAIL_PROVIDER_CLASSES[key] = cls
    _EMAIL_PROVIDER_CACHE.pop(key, None)


def get_email_provider(key: str) -> EmailProvider:
    if key in _EMAIL_PROVIDER_CACHE:
        return _EMAIL_PROVIDER_CACHE[key]
    cls = _EMAIL_PROVIDER_CLASSES.get(key)
    if not cls:
        raise UnknownMessagingProvider(f"unknown email provider: {key}")
    inst = cls()
    _EMAIL_PROVIDER_CACHE[key] = inst
    return inst


def list_registered_email_provider_keys() -> List[str]:
    return list(_EMAIL_PROVIDER_CLASSES.keys())


async def get_tenant_email_provider(
    tenant_id: str, *, db=None,
) -> Optional[EmailProvider]:
    for key in _EMAIL_PROVIDER_CLASSES.keys():
        summary = await connection_summary(tenant_id, key, db=db)
        if summary and summary.connected:
            return get_email_provider(key)
    return None


def reset_cache_for_tests() -> None:
    _EMAIL_PROVIDER_CACHE.clear()


def get_provider_field_schemas() -> Dict[str, Dict[str, Dict[str, Any]]]:
    return {k: cls.config_fields for k, cls in _EMAIL_PROVIDER_CLASSES.items()}
