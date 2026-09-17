"""Feb 2026 · Email CTA i18n helper.

Small, self-contained i18n lookup for the customer-facing email CTA
button labels that link to the invoice viewer. Introduced as part of
the "Invoice Email CTA Label" ticket so all five invoice-URL CTA
templates (payment reminder, initial invoice, overdue nudge, past-due
7d win-back sequence, admin email preview) resolve the same label per
recipient locale.

Locale contract mirrors the notification pipeline in
:mod:`services.i18n_notifications`:

    supported: "en" | "es" | "fr"
    fallback:  "en"

The helper is intentionally pure — it does NOT resolve locale from a
tenant/customer document itself; callers thread the already-resolved
locale in. This keeps the helper trivially unit-testable and avoids
duplicating the priority-order logic that
``resolve_recipient_locale`` already owns.

Usage::

    from services.email_cta_i18n import t_email_cta
    label = t_email_cta(locale="es", key="view_invoice")  # "Ver factura"
"""
from __future__ import annotations

from typing import Dict


SUPPORTED_LOCALES = ("en", "es", "fr")
FALLBACK_LOCALE = "en"


# Nested dict keyed by locale → key → label. Adding a new CTA key is
# an O(1) three-line edit under each locale block.
LABELS: Dict[str, Dict[str, str]] = {
    "en": {
        "view_invoice": "View Invoice",
    },
    "es": {
        "view_invoice": "Ver factura",
    },
    "fr": {
        "view_invoice": "Voir la facture",
    },
}


def _normalise_locale(raw: object) -> str:
    """Coerce any input to a supported locale. Unknown → ``en``.

    Trims BCP-47 region suffixes (``es-MX`` → ``es``) so callers can
    pass through the raw ``tenant.default_locale`` without pre-parsing.
    """
    if not raw:
        return FALLBACK_LOCALE
    s = str(raw).strip().lower()
    if "-" in s:
        s = s.split("-", 1)[0]
    if "_" in s:
        s = s.split("_", 1)[0]
    return s if s in SUPPORTED_LOCALES else FALLBACK_LOCALE


def t_email_cta(locale: object, key: str) -> str:
    """Return the localised email-CTA label for ``key`` in ``locale``.

    Falls back to English when the requested locale is unsupported OR
    the ``key`` is missing under the requested locale. Raises
    ``KeyError`` only when the key is missing under English too (i.e.
    a programming error, not a translation gap).
    """
    if not key:
        raise KeyError("email_cta key is required")
    loc = _normalise_locale(locale)
    labels_for_loc = LABELS.get(loc) or {}
    label = labels_for_loc.get(key)
    if label:
        return label
    # Locale exists but the key is missing under it → English fallback.
    en_label = LABELS[FALLBACK_LOCALE].get(key)
    if en_label:
        return en_label
    raise KeyError(f"unknown email_cta key: {key!r}")
