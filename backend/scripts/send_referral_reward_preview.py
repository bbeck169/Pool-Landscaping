"""Phase P53 · Feb-2026 — Dev CLI to send a live BOOM preview email.

Usage::

    python -m scripts.send_referral_reward_preview <email>
    python -m scripts.send_referral_reward_preview <email> --confirm
    python -m scripts.send_referral_reward_preview <email> --tenant <tid>

Sends a real BOOM referral-reward email to ``<email>`` using the
production ``services.email.resend_adapter.send`` path with the
same stub merge context the dev preview route uses. Interactive
"y" confirmation is required unless ``--confirm`` is passed —
matches the safety pattern in
``backend/scripts/purge_demo_data.py`` (this codebase has no
admin-token-guarded scripts to mirror; the interactive prompt is
the closest existing precedent).

The message is dispatched with ``category="transactional"`` and
``audience="internal"`` so the K72 customer-email kill-switch does
NOT short-circuit the send — dev previews are internal QA traffic,
not marketing customer traffic. ``allow_off_allowlist=True`` lets
the send bypass the ``COMMS_TEST_ALLOWLIST_EMAILS`` guard.

Exit codes:
    0 — sent (or dry-run print in ``--dry-run`` mode)
    2 — bad args / user aborted interactive prompt
    3 — provider send failed (details logged to stderr)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any, Dict, Optional


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scripts.send_referral_reward_preview",
        description=(
            "Send a live BOOM referral-reward preview email. Uses the "
            "same render path (body constant + merge-tag renderer + "
            "shell wrap) as the production send path — truthful to "
            "production."
        ),
    )
    p.add_argument("email", help="Recipient email address.")
    p.add_argument(
        "--tenant",
        default=None,
        help=(
            "Optional tenant id — resolves branding for the shell. "
            "Omit to render the shell with default branding."
        ),
    )
    p.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Skip the interactive 'y' prompt. You are about to send "
            "a REAL email — use only in automation."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Render + print the HTML to stdout WITHOUT sending. Handy "
            "for CI checks / visual smoke without touching Resend."
        ),
    )
    return p


async def _do_send(email: str, tenant_id: Optional[str]) -> Dict[str, Any]:
    from config import db
    from services.email.resend_adapter import send as _send_email
    from services.email.theming import wrap_html_in_shell
    from services.marketing.merge_tags import render_template
    from services.referral_watcher import (
        _REFERRAL_EMAIL_BODY,
        _REFERRAL_EMAIL_SUBJECT,
        _absolute_portal_referrals_url,
    )
    from routers.dev_email_preview import _STUB_CTX

    ctx = {**_STUB_CTX,
           "PORTAL_REFERRALS_URL": _absolute_portal_referrals_url()}
    subject, _ = render_template(_REFERRAL_EMAIL_SUBJECT, ctx)
    body, _ = render_template(_REFERRAL_EMAIL_BODY, ctx)

    branding = None
    if tenant_id:
        try:
            from services.tenants.business_settings import (
                get_effective_business_settings,
            )
            branding = await get_effective_business_settings(
                db, tenant_id, absolutize=True,
            )
        except Exception as exc:
            print(f"[p53-cli] branding resolve failed: {exc}",
                   file=sys.stderr)
    html = wrap_html_in_shell(body, branding)

    return await _send_email(
        to=email,
        subject=subject,
        html=html,
        category="transactional",
        tenant_id=tenant_id or None,
        idempotency_key=f"p53-preview:{email}",
        allow_off_allowlist=True,
        audience="internal",
    )


async def _do_dry_run(tenant_id: Optional[str]) -> str:
    from routers.dev_email_preview import render_boom_preview_html
    # ``render_boom_preview_html`` uses default branding; ``--tenant``
    # is only meaningful for the real send path. For dry-run we
    # emit the same HTML the dev preview route emits.
    _ = tenant_id  # unused (dry-run is branding-agnostic)
    return render_boom_preview_html()


def _confirm_or_exit(email: str) -> None:
    try:
        answer = input(
            f"About to send a REAL BOOM preview email to {email!r}. "
            "Continue? [y/N] "
        ).strip().lower()
    except EOFError:
        answer = ""
    if answer not in ("y", "yes"):
        print("Aborted by user.", file=sys.stderr)
        sys.exit(2)


def main(argv: Optional[list] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.dry_run:
        html = asyncio.run(_do_dry_run(args.tenant))
        print(html)
        return 0
    if not args.confirm:
        _confirm_or_exit(args.email)
    try:
        res = asyncio.run(_do_send(args.email, args.tenant))
    except Exception as exc:
        print(f"[p53-cli] send crashed: {exc}", file=sys.stderr)
        return 3
    status = (res or {}).get("provider_status") or "unknown"
    print(f"[p53-cli] send status={status} response={res!r}")
    return 0 if status in ("sent", "queued", "delivered", "accepted") else 3


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
