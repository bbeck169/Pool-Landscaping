"""WINGMAN-ESCALATION-EMAIL-FIX · Feb-2026.

Canonical absolute-URL helper for email templates.

Problem history (Feb-2026):
  The admin-notification fan-out at
  ``backend/services/notifications.py:496`` emitted an
  ``<a href="{href}">Open</a>`` link whose ``href`` was a RELATIVE
  path (e.g. ``/communication/<customer_id>``).  Resend-rendered
  mail clients that have no base URL in context fell back to the
  ``file:///`` scheme, so the recipient's "Open" button landed on
  a broken ``file:///communication/<cid>`` URI.  The silent-failure
  behaviour is being replaced here with a loud fail: a shared
  helper that logs an ERROR + emits an obviously-broken placeholder
  when the configuration is missing, instead of letting mail
  clients paper over it.

Design principles:
  • Single source of truth for the public base URL — reads
    ``config.APP_PUBLIC_URL`` which is the dominant pattern across
    ``backend/emailer.py`` and the other emailer modules.
  • Absolute passthrough — if the caller already provided a fully-
    qualified URL (``http://`` or ``https://``), the helper returns
    it unchanged.
  • Fail-loud on misconfiguration — if ``APP_PUBLIC_URL`` is empty
    and the caller passed a relative path, log an ERROR naming the
    template and emit a VISIBLE placeholder host so the broken link
    is obvious in the recipient's inbox rather than silently
    producing ``file:///...``.
  • Reusable — the four other relative-``href`` email surfaces
    flagged in the P0 grep sweep (see commit body) can adopt this
    helper in a future hardening ticket without changing the API.
"""
from __future__ import annotations

from typing import Optional

from config import APP_PUBLIC_URL, logger


# Deliberate placeholder host: the string is impossible to resolve
# (no public DNS) and the uppercase token names the broken env var
# so the ops recipient can act on it directly.
_CONFIG_MISSING_PLACEHOLDER_HOST = (
    "https://CONFIGURATION_MISSING_APP_PUBLIC_URL"
)


def absolute_portal_url(
    path: Optional[str],
    *,
    template_name: str,
) -> Optional[str]:
    """Return an absolute URL suitable for an email ``<a href>``.

    * ``path is None`` or empty → returns ``None`` so the caller can
      drop the link element entirely.
    * ``path`` already absolute (``http://`` / ``https://``) → passed
      through unchanged.
    * ``path`` relative + ``APP_PUBLIC_URL`` configured → joined.
    * ``path`` relative + ``APP_PUBLIC_URL`` empty → ERROR logged
      with ``template_name`` + visible placeholder returned (NOT
      ``file:///``).

    ``template_name`` is required for grep-friendly error attribution
    in ops logs.  Example values: ``"admin_notification_fanout"``,
    ``"quote_sent_customer"``.
    """
    if not path:
        return None
    text = str(path).strip()
    if not text:
        return None
    # Absolute URL passthrough (http/https).  Anything else — even
    # mailto:, tel:, etc. — is treated as a bug caller-side; join
    # unchanged so the loud-fail path can surface it.
    lower = text.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        return text
    base = (APP_PUBLIC_URL or "").rstrip("/")
    rel = text if text.startswith("/") else f"/{text}"
    if not base:
        logger.error(
            "[email-urls] APP_PUBLIC_URL is not configured — "
            "emitting a visible placeholder host for template=%r "
            "path=%r.  Set APP_PUBLIC_URL in the backend env to "
            "fix.  (This replaces the pre-Feb-2026 silent "
            "``file:///...`` failure mode.)",
            template_name, rel,
        )
        return f"{_CONFIG_MISSING_PLACEHOLDER_HOST}{rel}"
    return f"{base}{rel}"
