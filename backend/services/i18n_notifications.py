"""Phase D5 · Feb-2026 — i18n loader for email + SMS notification bodies.

Resolves a locale-scoped notification body (subject + HTML + plain
text for email; body_text for SMS) from disk-backed template files.

Locale fallback contract::

    requested locale → "en" → TemplateNotFoundError

Merge variables use Python ``str.format``-compatible ``{placeholder}``
tokens. Missing tokens raise :class:`MissingMergeVarError` — never
render a literal ``{customer_name}`` into a real inbox.

Template directory layout::

    backend/services/notification_templates/
        en/
            job_completed.subject.txt          # email subject line
            job_completed.html                  # email HTML body
            job_completed.txt                   # email plain-text body
            visit_reminder.sms.txt              # SMS body (single file)
        es/
            (mirror of en/, gender-neutral formal `usted`)
        fr/
            (mirror of en/, formal `vous`)

Public API::

    resolve_notification_body(template_key, locale, context)
        → dict with keys ``{"subject", "body_html", "body_text"}`` for
          email templates or ``{"body_text"}`` for SMS templates.

    resolve_recipient_locale(...)
        → normalised locale string ("en" | "es" | "fr").

    SUPPORTED_LOCALES / FALLBACK_LOCALE
        Module-level constants used by callers + tests.
"""
from __future__ import annotations

import logging
import re
import string
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Set

logger = logging.getLogger("i18n_notifications")

# Locale whitelist. Any locale not in this set is silently coerced to
# ``FALLBACK_LOCALE`` (``en``) on both the resolver and loader paths.
SUPPORTED_LOCALES: Set[str] = {"en", "es", "fr"}
FALLBACK_LOCALE: str = "en"

# GSM-7 per-segment limit. Bodies over this are still SENT (multi-
# segment), but the send-site helper emits a WARNING so translators
# can tighten copy proactively.
SMS_GSM7_SEGMENT_CHARS: int = 160

# Repository-relative template root. Resolved once at import time.
_TEMPLATE_ROOT = Path(__file__).parent / "notification_templates"

# Cache of loaded (template_key, locale) → raw string files so a hot
# path notification send doesn't hit the filesystem on every call.
# Keyed by the physical file path so a template edit under
# ``notification_templates/`` requires a process restart to pick up —
# matches the semantics of the marketing_templates DB seed.
_FILE_CACHE: Dict[Path, str] = {}


class TemplateNotFoundError(FileNotFoundError):
    """Raised when neither the requested locale nor the ``en``
    fallback has a file for a given ``template_key`` + kind."""


class MissingMergeVarError(KeyError):
    """Raised when a template references a ``{placeholder}`` that the
    caller did NOT supply in ``context``. Never let a literal
    ``{customer_name}`` reach a real inbox."""


def _normalise_locale(raw: Any) -> str:
    """Coerce any input to a supported locale. Unknown → ``en``."""
    if not raw:
        return FALLBACK_LOCALE
    s = str(raw).strip().lower()
    # Trim BCP-47 region suffix (``es-MX`` → ``es``).
    if "-" in s:
        s = s.split("-", 1)[0]
    if "_" in s:
        s = s.split("_", 1)[0]
    return s if s in SUPPORTED_LOCALES else FALLBACK_LOCALE


def resolve_recipient_locale(
    *,
    customer: Optional[Mapping[str, Any]] = None,
    tenant: Optional[Mapping[str, Any]] = None,
    user: Optional[Mapping[str, Any]] = None,
    audience: str = "customer",
) -> str:
    """Resolve the outbound locale for a notification recipient.

    Priority order per Phase D5 spec:

        customer.locale → tenant.default_locale → "en"

    For techs (``audience="tech"``) the ``user.locale`` overrides
    ``customer.locale`` since the recipient IS the tech.

    For admin recipients (``audience="admin"``) ALWAYS return ``en``.
    Admin operational messages stay English in D5 — this is a locked
    product decision, not a code oversight.
    """
    if audience == "admin":
        return FALLBACK_LOCALE
    if audience == "tech":
        if user and user.get("locale"):
            return _normalise_locale(user["locale"])
        if tenant and tenant.get("default_locale"):
            return _normalise_locale(tenant["default_locale"])
        return FALLBACK_LOCALE
    # customer audience.
    if customer and customer.get("locale"):
        return _normalise_locale(customer["locale"])
    if tenant and tenant.get("default_locale"):
        return _normalise_locale(tenant["default_locale"])
    return FALLBACK_LOCALE


def _read_file(path: Path) -> str:
    cached = _FILE_CACHE.get(path)
    if cached is not None:
        return cached
    text = path.read_text(encoding="utf-8")
    _FILE_CACHE[path] = text
    return text


def _load_with_fallback(template_key: str, locale: str,
                          extension: str) -> Optional[str]:
    """Try ``{locale}/{template_key}.{extension}``, then ``en/…``.

    Returns None if neither exists — the caller decides whether that's
    a hard error (e.g. missing SMS body) or expected (e.g. HTML
    template optional for an SMS-only key).
    """
    for candidate_locale in (locale, FALLBACK_LOCALE):
        fp = _TEMPLATE_ROOT / candidate_locale / f"{template_key}.{extension}"
        if fp.exists():
            return _read_file(fp)
    return None


# Python's str.format on a template with a `{tag}` and no matching key
# raises KeyError. That's the primitive we want, but the KeyError's
# message is just the missing key — we want it to name the template
# key and the missing placeholder for greppable diagnostics.
_FORMATTER = string.Formatter()


def _apply_merge_vars(template_key: str, raw: str,
                        context: Mapping[str, Any]) -> str:
    """Substitute ``{placeholder}`` tokens. Raises
    :class:`MissingMergeVarError` if any referenced token is not in
    ``context`` — never let a literal marker reach the recipient.
    """
    try:
        return _FORMATTER.vformat(raw, (), dict(context))
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "?"
        raise MissingMergeVarError(
            f"template={template_key!r} missing merge var "
            f"{missing!r} in context"
        ) from exc
    except IndexError as exc:  # positional {0} references — not allowed
        raise MissingMergeVarError(
            f"template={template_key!r} uses positional format token; "
            f"only named {{placeholder}} tokens are supported"
        ) from exc


_TAG_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def extract_placeholders(raw: str) -> Set[str]:
    """Return the set of ``{name}`` placeholder tokens in ``raw``.

    Used by the drift-guard test suite to enforce that every locale
    variant of a template uses the identical placeholder set — a
    translator who accidentally localises ``{customer_name}`` to
    ``{nombre_del_cliente}`` will fail placeholder-parity in CI.
    """
    return set(_TAG_RE.findall(raw or ""))


def resolve_notification_body(
    template_key: str,
    locale: str,
    context: Mapping[str, Any],
) -> Dict[str, str]:
    """Return the rendered notification body for a given template.

    * For EMAIL templates, expects the triplet
      ``{key}.subject.txt`` + ``{key}.html`` + ``{key}.txt`` to exist
      under either ``{locale}/`` or ``en/``. Returns
      ``{"subject", "body_html", "body_text"}``.

    * For SMS templates, expects a single ``{key}.sms.txt`` file.
      Returns ``{"body_text"}``.

    * Kind is auto-detected from which files exist.

    Locale fallback chain: requested locale → ``en`` → raise.
    """
    if not template_key:
        raise TemplateNotFoundError("template_key is required")
    loc = _normalise_locale(locale)

    # SMS detection first — a template is SMS if a ``.sms.txt`` file
    # exists under either the requested locale OR the fallback. Email
    # templates NEVER own a ``.sms.txt`` file so this is unambiguous.
    sms_body = _load_with_fallback(template_key, loc, "sms.txt")
    if sms_body is not None:
        return {"body_text": _apply_merge_vars(template_key, sms_body, context)}

    subject = _load_with_fallback(template_key, loc, "subject.txt")
    html = _load_with_fallback(template_key, loc, "html")
    text = _load_with_fallback(template_key, loc, "txt")
    if subject is None and html is None and text is None:
        raise TemplateNotFoundError(
            f"template={template_key!r} has no files under "
            f"{loc}/ or {FALLBACK_LOCALE}/ (checked .sms.txt, "
            ".subject.txt, .html, .txt)"
        )
    if subject is None or html is None or text is None:
        raise TemplateNotFoundError(
            f"template={template_key!r} is incomplete for locale={loc!r} "
            f"(subject={subject is not None}, html={html is not None}, "
            f"text={text is not None}) — the en fallback must supply "
            "all three"
        )
    return {
        "subject": _apply_merge_vars(template_key, subject, context).strip(),
        "body_html": _apply_merge_vars(template_key, html, context),
        "body_text": _apply_merge_vars(template_key, text, context),
    }


def sms_segment_count(body: str) -> int:
    """Return the approximate GSM-7 SMS segment count for ``body``.

    Naive character count — the real segment math also accounts for
    UCS-2 escapes, but for the D5 length-monitoring guard rail an
    approximate count is enough (we only care about "is this going to
    fragment into 3+ segments"). Empty / None → 1 segment (the
    minimum an SMS can be).
    """
    n = len(body or "")
    if n <= SMS_GSM7_SEGMENT_CHARS:
        return 1
    # After the first 153 chars in a concatenated SMS, each segment
    # holds 153 chars. Use 160 for the first segment though — matches
    # what carriers charge.
    remaining = max(0, n - SMS_GSM7_SEGMENT_CHARS)
    return 1 + (remaining + 152) // 153


def clear_cache() -> None:
    """Test-only helper — forces the next load to hit disk again.
    Called from fixtures that write ad-hoc templates into the tree."""
    _FILE_CACHE.clear()
