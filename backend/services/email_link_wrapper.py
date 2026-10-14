"""P2 #11 · Phase 2 (TD-44) · Feb-2026 — Email link wrapping / UTM injection.

Walks a rendered email HTML string and appends UTM query parameters to
every ``<a href="...">`` whose target is an ordinary ``http(s)``
destination. The pipeline (``_deliver_one`` + preview + test-send)
calls ``wrap_links`` AFTER ``render_email_html`` and BEFORE
``send_email`` so links in the actual outbound HTML carry the
attribution.

Skips (no-op pass-through):

  * ``mailto:`` and ``tel:`` destinations.
  * ``#anchor`` and empty hrefs.
  * Unsubscribe URLs — we detect any href containing
    ``/unsubscribe`` OR ``unsub_token=`` so both the tenant-signed
    HMAC form (``{{unsubscribe_url}}``) and legacy marketing-studio
    paths are preserved verbatim. Appending UTM to an unsubscribe
    link breaks the signature verification at
    ``routers/comms.py:_verify_unsubscribe``.
  * Links that already carry ``utm_source=`` — authored intent
    wins; we never clobber a hand-crafted campaign tag.

Tenant override — ``db.tenants.email_utm_defaults: Dict[str,str]``
replaces the default param set when present (full replace, not
merge).  ``db.tenants.email_link_wrapping_enabled: bool = True`` is
the kill-switch; when ``False`` the function returns ``html``
unchanged.

Defaults when the tenant row carries neither override:

  {"utm_source": "email",
   "utm_medium": "transactional",
   "utm_campaign": "{{template.code}}",
   "utm_content":  "{{template.code}}"}

The default values support the same ``{{token}}`` substitution
syntax as the rest of ``services.comm_tokens`` — ``context`` passes
through the token resolver so e.g. ``utm_campaign`` can embed the
current template code / tenant slug / etc.

Zero-regex pitfalls — the walker uses a single ``re`` pass with a
callback.  No HTML parser is pulled in (no new deps).  URLs are
rebuilt with ``urllib.parse`` so pre-existing query strings merge
cleanly.
"""
from __future__ import annotations

import re as _re
from typing import Any, Dict, Optional
from urllib.parse import (
    urlparse, urlunparse, parse_qsl, urlencode,
)

from .comm_tokens import resolve_tokens


_DEFAULT_UTM = {
    "utm_source": "email",
    "utm_medium": "transactional",
    "utm_campaign": "{{template.code}}",
    "utm_content": "{{template.code}}",
}


# One pass over href values. Case-insensitive on the attribute name;
# the quote char may be single OR double so both forms survive the
# round-trip. Capture groups: 1 = opening quote char, 2 = href value.
_HREF_RE = _re.compile(
    r'''href\s*=\s*(["'])([^"']*)\1''',
    _re.IGNORECASE,
)


def _should_skip(href: str) -> bool:
    """Return True when the href must NOT be UTM-wrapped."""
    if not href:
        return True
    h = href.strip().lower()
    if h.startswith("#"):
        return True
    if h.startswith("mailto:") or h.startswith("tel:"):
        return True
    if h.startswith("{{") and h.endswith("}}"):
        # Unresolved token — leave alone; it means token resolution
        # failed upstream.  Wrapping would corrupt the token.
        return True
    # Unsubscribe-link heuristics — tenant-signed HMAC path OR
    # legacy marketing-studio path.  Appending UTM breaks the
    # signature verification at ``routers/comms.py``.
    if "/unsubscribe" in h or "unsub_token=" in h or "unsubscribe_token=" in h:
        return True
    # Already-UTM'd links: respect authored intent.
    if "utm_source=" in h:
        return True
    # Non-http(s) schemes (sms:, javascript:, data:, ftp:, etc.).
    if not (h.startswith("http://") or h.startswith("https://")):
        return True
    return False


def _append_utm_to_url(url: str, params: Dict[str, str]) -> str:
    """Merge ``params`` into ``url``'s query string.

    Pre-existing query params survive untouched; new UTM params are
    appended at the end so clients that read in order don't see a
    reshuffle.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    existing = parse_qsl(parsed.query or "", keep_blank_values=True)
    existing_keys = {k for k, _ in existing}
    for k, v in params.items():
        if k not in existing_keys and v:
            existing.append((k, v))
    new_q = urlencode(existing, doseq=True, safe=":/{}")
    return urlunparse(parsed._replace(query=new_q))


def wrap_links(
    html: str,
    context: Optional[Dict[str, Any]] = None,
    utm_defaults: Optional[Dict[str, str]] = None,
    enabled: bool = True,
) -> str:
    """Return ``html`` with UTM params appended to eligible <a href>s.

    Pass ``enabled=False`` for the tenant kill-switch (just returns
    ``html`` unchanged).  ``utm_defaults`` overrides the module-level
    defaults; falsy → use ``_DEFAULT_UTM``.  ``context`` is the token
    context used to resolve ``{{template.code}}`` etc inside the UTM
    values themselves.
    """
    if not enabled or not html:
        return html
    base_defaults = dict(utm_defaults or _DEFAULT_UTM)
    ctx = context or {}
    # Resolve tokens inside the UTM VALUES up-front so each matched
    # href gets the same resolved param set (and ``resolve_tokens``
    # only runs once per send).
    resolved_defaults: Dict[str, str] = {}
    for k, v in base_defaults.items():
        if not isinstance(v, str):
            continue
        rv = resolve_tokens(v, ctx) if ("{{" in v) else v
        if rv:
            resolved_defaults[k] = rv
    if not resolved_defaults:
        return html

    def _sub(match):
        quote = match.group(1)
        href = match.group(2)
        if _should_skip(href):
            return match.group(0)
        new_href = _append_utm_to_url(href, resolved_defaults)
        return f'href={quote}{new_href}{quote}'
    return _HREF_RE.sub(_sub, html)
