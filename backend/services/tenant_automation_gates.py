"""P2 #10d · Feb-2026 — Shared tenant-automation gating helper.

A one-liner used at the top of each P2 #10d-gated automation entry
point to short-circuit when the tenant has flipped the kill switch
to False. Default True on unset (opt-out posture).

Reads ``config.db`` lazily at call time so a pytest fixture that
swaps ``config.db`` for a stub is honored without needing an
``importlib.reload`` dance (matches the Phase 34 async-loop
posture).
"""
from __future__ import annotations

import config


_P2_10D_FLAGS = {
    "lead_conversion_welcome_enabled",
    "completion_followup_sms_enabled",
    "invoice_past_due_enabled",
    "estimate_reminder_enabled",
}


def _assert_known_flag(flag: str) -> None:
    if flag not in _P2_10D_FLAGS:
        raise ValueError(
            f"automation_enabled: unknown flag '{flag}' — must be one of "
            f"{sorted(_P2_10D_FLAGS)}"
        )


async def automation_enabled(tenant_id: str, flag: str) -> bool:
    """Return the tenant's current value for ``flag`` with default
    True on unset / absent-tenant. ``flag`` MUST be a P2 #10d flag."""
    _assert_known_flag(flag)
    tenant = await config.db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, flag: 1},
    )
    if tenant is None:
        return True
    return bool(tenant.get(flag, True))
