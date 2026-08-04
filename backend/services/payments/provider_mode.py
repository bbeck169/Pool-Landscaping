"""Phase 47e · Feb-2026 — payments provider gating + regression sweep.

This module owns the tiny amount of runtime code needed for the
``PAYMENTS_PROVIDER_MODE`` kill switch that Phase 47 introduced. The
default is ``"stripe_direct"`` — every pay-button, add-card, ACH and
quote-share surface routes through the Stripe SDK.

Setting the env to ``"lumino"`` or ``"zapier"`` is documented as an
**operator-only rollback path** — the Lumino / Zapier modules are still
in the tree (dark) so an operator can restore them if a Stripe outage
requires falling back to the hosted-link workflow. No frontend UX
depends on the env value.

Regression tests scan the pay path for stray Lumino / Zapier calls;
see :mod:`tests.test_phase47e_no_lumino_in_pay_path`.
"""
from __future__ import annotations

import os
from typing import Literal, Optional

_MODE = Literal["stripe_direct", "lumino", "zapier"]


def payments_provider_mode() -> str:
    """Return the currently configured payments provider mode.

    Env: ``PAYMENTS_PROVIDER_MODE``. Values other than the three
    listed above are normalised to ``"stripe_direct"`` so a typo
    can't accidentally route real customers to a dark provider.
    """
    val = (os.environ.get("PAYMENTS_PROVIDER_MODE") or "").strip().lower()
    if val in ("lumino", "zapier"):
        return val
    return "stripe_direct"


def is_stripe_direct() -> bool:
    return payments_provider_mode() == "stripe_direct"


def is_dark_provider_mode() -> bool:
    """True when an operator has explicitly requested the dark fallback."""
    return payments_provider_mode() in ("lumino", "zapier")
