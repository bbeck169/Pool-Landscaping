"""Phase 44 · Comms Template Sweep (demo-only safety test) · Feb 2026.

Fires ONE representative message per template class through the
existing Resend / email pipeline to verify all templates render
correctly after the Phase 42 Stripe config refresh.

Guardrails
==========

* **Hard allowlist.** Every recipient is validated against
  ``_COMMS_SWEEP_ALLOWED_EMAILS``. Any address outside the set
  raises ``_AllowlistViolation`` and aborts the whole sweep — no
  partial send.
* **Never resolves recipients from the DB.** All recipient sets are
  literal constants in this script.
* **Every message carries** ``X-Emergent-Sweep: phase-44-demo`` so
  downstream systems can filter, inspect, and — if this ever fires
  by mistake — post-hoc detect + quarantine.
* **In-memory fixtures only.** No DB writes to ``quotes``,
  ``stripe_charges``, or ``payment_events``. No live Stripe calls.

Usage
=====

    # DRY RUN (default — nothing is sent):
    python3 backend/scripts/phase44_comms_sweep.py

    # LIVE — actually invokes send_email() for each allowlist recipient:
    python3 backend/scripts/phase44_comms_sweep.py --live

Live mode still requires:
  * RESEND_API_KEY in the process env (else the adapter no-ops).
  * The tenant's ``comms_env`` allow-listing must include the
    recipient (independent guard from ``services.comms_env_guard``).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List

# ── Allowlist ──────────────────────────────────────────────────────────
# Sourced from `/app/memory/test_credentials.md`. Update this constant
# if you add another demo/seed account; do NOT resolve at runtime from
# DB collections — that's the exact footgun this guardrail exists to
# prevent.
_COMMS_SWEEP_ALLOWED_EMAILS = frozenset({
    "customer@aquaterra.com",
    "manager@aquaterra.com",
    "super@aquaterra.com",
    "admin@aquaterra.com",
    "landscaper@aquaterra.com",
})

_SWEEP_HEADER = {"X-Emergent-Sweep": "phase-44-demo"}
_TENANT_ID = "aquaterra"


class _AllowlistViolation(RuntimeError):
    """Raised the instant a non-allowlist recipient is proposed."""


def _assert_allowlist(email: str) -> None:
    if email not in _COMMS_SWEEP_ALLOWED_EMAILS:
        raise _AllowlistViolation(
            f"Address {email!r} is NOT in _COMMS_SWEEP_ALLOWED_EMAILS. "
            "Add it explicitly if this is intentional, or fix the caller."
        )


# ── Template inventory ─────────────────────────────────────────────────
@dataclass
class Template:
    key: str
    subject: str
    html: str


# Fixture context — deterministic + obvious "demo" branding so any
# accidental live send is spotted immediately.
_FIXT = {
    "customer_name": "Demo Customer (Phase 44 sweep)",
    "invoice_number": "INV-DEMO-99999",
    "amount": "$1,234.56",
    "due_date": "2026-02-28",
    "next_service": "2026-03-05",
    "review_link": "https://example.test/r/demo-token",
    "reset_link": "https://example.test/reset/demo-token",
}


def _html(body: str) -> str:
    return (
        f"<html><body><p>{body}</p>"
        f"<p style='color:#888;font-size:11px'>Phase 44 sweep · "
        f"Feb 2026 · fixture message · not a real notification.</p>"
        f"</body></html>"
    )


TEMPLATES: List[Template] = [
    Template("invoice_sent",
             f"[Phase 44 sweep] Invoice {_FIXT['invoice_number']} — {_FIXT['amount']}",
             _html(f"Hi {_FIXT['customer_name']}, your invoice {_FIXT['invoice_number']} for {_FIXT['amount']} is ready.")),
    Template("invoice_reminder",
             f"[Phase 44 sweep] Reminder — {_FIXT['invoice_number']} due {_FIXT['due_date']}",
             _html(f"Reminder — {_FIXT['invoice_number']} is due {_FIXT['due_date']}.")),
    Template("payment_receipt",
             f"[Phase 44 sweep] Payment received — {_FIXT['amount']}",
             _html(f"We received {_FIXT['amount']} for {_FIXT['invoice_number']}. Thank you!")),
    Template("payment_failed",
             f"[Phase 44 sweep] Payment failed — {_FIXT['invoice_number']}",
             _html(f"Your payment for {_FIXT['invoice_number']} failed. Please update your card.")),
    Template("job_scheduled",
             f"[Phase 44 sweep] Next service {_FIXT['next_service']}",
             _html(f"Your next service is scheduled for {_FIXT['next_service']}.")),
    Template("job_completed",
             "[Phase 44 sweep] Service complete",
             _html("Your service is complete — please review below.")),
    Template("review_request",
             "[Phase 44 sweep] How did we do?",
             _html(f"Rate today's service: {_FIXT['review_link']}")),
    Template("password_reset",
             "[Phase 44 sweep] Password reset",
             _html(f"Reset your password: {_FIXT['reset_link']}")),
    Template("welcome",
             "[Phase 44 sweep] Welcome to Aqua Terra",
             _html(f"Welcome {_FIXT['customer_name']} — your portal is ready.")),
    Template("estimate_sent",
             "[Phase 44 sweep] Estimate ready",
             _html(f"Your estimate for {_FIXT['amount']} is attached.")),
]


# ── Send helpers ───────────────────────────────────────────────────────
async def _send_one(send_fn: Callable, template: Template, to_email: str) -> Dict:
    _assert_allowlist(to_email)
    start = time.monotonic()
    result = await send_fn(
        tenant_id=_TENANT_ID,
        to_email=to_email,
        subject=template.subject,
        html=template.html,
        from_name="Phase 44 sweep",
        headers=dict(_SWEEP_HEADER),
    )
    latency_ms = int((time.monotonic() - start) * 1000)
    return {"template": template.key, "to": to_email, "result": result, "ms": latency_ms}


async def run_sweep(*, live: bool, send_fn: Callable | None = None) -> List[Dict]:
    """Return the list of send attempts. In dry-run mode ``send_fn`` is
    a no-op stub; in live mode the real Resend adapter is invoked."""
    if send_fn is None:
        if live:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from services.comms_email_adapter import send_email as send_fn  # type: ignore
        else:
            async def send_fn(**kwargs):  # noqa: E306
                headers = kwargs.get("headers") or {}
                assert headers.get("X-Emergent-Sweep") == "phase-44-demo", \
                    "sweep header missing"
                return {"status": "dry_run"}

    log: List[Dict] = []
    for tpl in TEMPLATES:
        for addr in sorted(_COMMS_SWEEP_ALLOWED_EMAILS):
            entry = await _send_one(send_fn, tpl, addr)
            log.append(entry)
    return log


# ── CLI ────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 44 · comms sweep")
    parser.add_argument("--live", action="store_true",
                        help="Actually send. Default is dry-run.")
    args = parser.parse_args()

    if args.live:
        print("⚠️  LIVE MODE — invoking Resend adapter for real.")
    else:
        print("DRY RUN — no messages will be delivered.")
    print(f"Allowlist ({len(_COMMS_SWEEP_ALLOWED_EMAILS)}): "
          f"{sorted(_COMMS_SWEEP_ALLOWED_EMAILS)}")
    print(f"Templates ({len(TEMPLATES)}): {[t.key for t in TEMPLATES]}")
    print()

    try:
        results = asyncio.run(run_sweep(live=args.live))
    except _AllowlistViolation as e:
        print(f"[ABORT] {e}")
        return 2

    for r in results:
        prefix = "[LIVE]" if args.live else "[DRY RUN]"
        status = (r["result"] or {}).get("status", "unknown")
        print(f"{prefix} {r['template']:<20} → {r['to']:<30} "
              f"status={status:<20} {r['ms']}ms")

    print()
    print(f"Total attempts: {len(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
