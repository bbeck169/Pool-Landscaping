"""Phase 42.2 · Feb 2026 — Stripe configuration diagnostic.

Prints the current Stripe env vars (masked to last-4) and confirms
the SDK can hit ``stripe.Balance.retrieve()`` with the loaded key.

NOT wired into CI. Operator invokes manually:

    python3 backend/scripts/verify_stripe_config.py

Exit codes:
    0  — everything looks good
    1  — unconfigured (missing key OR balance call failed)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _mask(v: str | None) -> str:
    if not v:
        return "(unset)"
    if len(v) <= 4:
        return "***"
    return f"…{v[-4:]}"


def main() -> int:
    # Add backend/ to sys.path so ``services.*`` imports resolve when
    # this script is run from any cwd.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    print("Phase 42.2 · Stripe config diagnostic")
    print("=" * 44)
    mode = (os.environ.get("STRIPE_MODE") or "test").lower()
    env_vars = [
        ("STRIPE_MODE",                    os.environ.get("STRIPE_MODE") or "test (default)"),
        ("STRIPE_SECRET_KEY_LIVE",         _mask(os.environ.get("STRIPE_SECRET_KEY_LIVE"))),
        ("STRIPE_SECRET_KEY_TEST",         _mask(os.environ.get("STRIPE_SECRET_KEY_TEST"))),
        ("STRIPE_API_KEY",                 _mask(os.environ.get("STRIPE_API_KEY"))),
        ("STRIPE_WEBHOOK_SECRET_LIVE",     _mask(os.environ.get("STRIPE_WEBHOOK_SECRET_LIVE"))),
        ("STRIPE_WEBHOOK_SECRET_TEST",     _mask(os.environ.get("STRIPE_WEBHOOK_SECRET_TEST"))),
        ("STRIPE_WEBHOOK_SECRET",          _mask(os.environ.get("STRIPE_WEBHOOK_SECRET"))),
        ("STRIPE_PUBLISHABLE_KEY_LIVE",    _mask(os.environ.get("STRIPE_PUBLISHABLE_KEY_LIVE"))),
        ("STRIPE_PUBLISHABLE_KEY_TEST",    _mask(os.environ.get("STRIPE_PUBLISHABLE_KEY_TEST"))),
    ]
    for name, val in env_vars:
        print(f"  {name:<32} {val}")
    print()

    try:
        from services.payments import stripe_charge
        stripe_charge._init_api_key()
    except stripe_charge._UnconfiguredStripeError as e:
        print(f"[FAIL] {e}")
        return 1
    print(f"api_version pinned  → {stripe_charge.STRIPE_API_VERSION}")
    print(f"mode                → {mode}")

    print()
    print("Testing stripe.Balance.retrieve() …")
    try:
        import stripe
        bal = stripe.Balance.retrieve()
        available = getattr(bal, "available", None) or bal.get("available", []) if isinstance(bal, dict) else []
        if isinstance(available, list) and available:
            first = available[0]
            amt = first.get("amount") if isinstance(first, dict) else getattr(first, "amount", None)
            cur = first.get("currency") if isinstance(first, dict) else getattr(first, "currency", "")
            print(f"[OK] Balance available = {amt} {cur}")
        else:
            print("[OK] Balance call succeeded (no funds).")
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] stripe.Balance.retrieve() → {e}")
        return 1

    print()
    print("Everything looks good. Stripe is wired for the current mode.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
