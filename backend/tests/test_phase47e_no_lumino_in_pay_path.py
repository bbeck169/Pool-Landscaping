"""Phase 47e · Feb-2026 — regression sweep for the pay-path Lumino/Zapier bypass.

Guards against a future rewrite dragging a Lumino dispatcher call or a
Zapier catch-hook back into any of the routes/services that live on the
customer-facing pay flow. If someone adds a ``dispatch_invoice_link_request``
call or a ``requests.post(ZAPIER_...)`` to any of these files, this test
trips.

Scope:
    * ``backend/routers/lumino_link_request.py``  — Phase-47 rewritten
    * ``backend/routers/customer_portal.py``      — Phase-47d ACH restored
    * ``backend/routers/customers.py`` (public add-card token routes)
    * ``backend/routers/stripe_router.py``        — direct Stripe surface
    * ``backend/services/payments/stripe_charge.py``

The dark modules (``services.lumino_zapier_dispatcher``,
``services.payments.lumino_provider``, ``routers.lumino_backfill``,
``routers.lumino_invoice_link_callback``) are NOT in the scan — they
still live in-tree as an operator-only rollback path (see
``services.payments.provider_mode``).
"""
from __future__ import annotations

import inspect
import re
from typing import Iterable

# ── Files that MUST NOT touch Lumino/Zapier at runtime ────────────
_PAY_PATH_MODULES = [
    "routers.lumino_link_request",
    "routers.customer_portal",
    "routers.customers",
    "routers.stripe_router",
    "services.payments.stripe_charge",
]

# Patterns whose presence in a pay-path module body is a defect.
# Regex-matched CASE-INSENSITIVELY against the module source with
# comments/docstrings stripped so migration explanations don't false-
# positive.
_FORBIDDEN = [
    "dispatch_invoice_link_request",
    "lumino_zapier_dispatcher",
    "lumino_provider",
    "zapier_invoice_link_webhook_url",
    "zapier_catch_hook",
]


def _strip_docstrings_and_comments(src: str) -> str:
    """Return the module source with triple-quoted docstrings and
    ``#``-comments removed. Enough surface area for grep-style guards."""
    # Triple-quoted strings.
    out = re.sub(r'"""[\s\S]*?"""', "", src)
    out = re.sub(r"'''[\s\S]*?'''", "", out)
    # Line comments.
    out = re.sub(r"#.*$", "", out, flags=re.MULTILINE)
    return out


def _iter_module_bodies() -> Iterable[tuple[str, str]]:
    import importlib
    for dotted in _PAY_PATH_MODULES:
        mod = importlib.import_module(dotted)
        yield dotted, _strip_docstrings_and_comments(inspect.getsource(mod))


def test_no_lumino_or_zapier_call_sites_in_pay_path_modules():
    """Grep — CI-friendly regression sweep."""
    found: list[tuple[str, str]] = []
    for mod, body in _iter_module_bodies():
        low = body.lower()
        for token in _FORBIDDEN:
            if token in low:
                found.append((mod, token))
    assert not found, (
        "Phase 47e regression — the following pay-path modules "
        "contain a Lumino/Zapier reference at runtime (comments "
        "already stripped): " + ", ".join(f"{m}::{t}" for m, t in found)
        + ". If you INTENDED to route through the dark rollback path, "
        "gate it behind ``services.payments.provider_mode.is_stripe_direct()`` "
        "instead of a direct call."
    )


def test_provider_mode_defaults_to_stripe_direct(monkeypatch):
    monkeypatch.delenv("PAYMENTS_PROVIDER_MODE", raising=False)
    from services.payments.provider_mode import payments_provider_mode, is_stripe_direct
    assert payments_provider_mode() == "stripe_direct"
    assert is_stripe_direct() is True


def test_provider_mode_typo_falls_back_to_stripe_direct(monkeypatch):
    """Guards against a stray "stripedirect" / "zaper" typo silently
    routing customers to a dark path."""
    from services.payments.provider_mode import payments_provider_mode
    for bad in ("stripedirect", "zaper", "LUMINO_BROKEN", ""):
        monkeypatch.setenv("PAYMENTS_PROVIDER_MODE", bad)
        assert payments_provider_mode() == "stripe_direct", (
            f"typo {bad!r} must fall back to stripe_direct — got a live "
            f"dark-provider routing instead"
        )


def test_provider_mode_accepts_documented_dark_values(monkeypatch):
    from services.payments.provider_mode import payments_provider_mode, is_dark_provider_mode
    for good in ("lumino", "Zapier", "LUMINO"):
        monkeypatch.setenv("PAYMENTS_PROVIDER_MODE", good)
        assert payments_provider_mode() == good.lower()
        assert is_dark_provider_mode() is True


def test_dark_modules_still_importable_for_rollback():
    """Phase 47e mandate: the Lumino/Zapier modules stay in-tree so an
    operator can flip ``PAYMENTS_PROVIDER_MODE=lumino`` if Stripe is
    down. If any of these fail to import, the rollback path is broken."""
    import importlib
    for dotted in [
        "services.lumino_zapier_dispatcher",
        "services.payments.lumino_provider",
        "routers.lumino_backfill",
        "routers.lumino_invoice_link_callback",
    ]:
        importlib.import_module(dotted)
