"""K72.b · Apology Dispatch — production one-shot script.

Feb-2026. Sends the user-approved apology email to the 113 real customers
affected by the 2026-08-31 "no-filter" incident (batch
``f0c63d4a-20bb-4dca-9751-470465e1e702``, tenant Pool & Landscaping of
Vistancia · slug ``aquaterra`` · id ``affdfbfa-88b9-4baa-ae45-2ef78531b6e4``).

Design contract (see /app/memory/K72_APOLOGY_RUNBOOK.md for the full
operator brief):

* NEVER runs from preview / staging. Preflight refuses when
  ``APP_ENV != production``.
* Reads the authoritative recipient roster from section 3 of
  ``/app/memory/PHASE_K72_EMERGENCY_NO_FILTER_EMAIL_DIAG.md`` (the
  markdown table checked in with the incident memo). Filters to only
  the 113 real customers (``sent`` rows, excluding the
  ``example.invalid`` / ``example.com`` / ``example.local`` fixtures
  and the seeded ``customer@aquaterra.com`` demo mailbox).
* Per recipient: resolves ``first_name`` from ``db.customers`` by email
  (fallback ``"there"``). Hard-codes ``[SUPPORT_PHONE]`` to
  ``602-887-4400`` (inline + signature — twice).
* Sends via the Resend adapter with ``audience="customer"`` so the K72
  kill switch still governs it (preflight refuses when kill switch is
  ON — a suppressed apology is worse than no apology). Passes
  ``allow_off_allowlist=True`` because these are real customer
  mailboxes, not demo accounts, and the preview allow-list won't
  cover them (a no-op on prod but future-proofs the script).
* Rate-limited to 5 sends / second (200 ms sleep between).
* Idempotent — writes a ``k72_apology_dispatch`` audit row per
  recipient with the Resend message id (or error). Reruns skip any
  address already in the audit table with ``status="sent"``.
* Dry-run default. ``--commit`` is required to actually send. First
  run should always be dry-run to preview.

Usage
-----
    # Preview what would be sent (no DB writes, no Resend calls):
    python /app/scripts/k72_apology_send.py --dry-run

    # Actually send. Requires APP_ENV=production and kill switch OFF.
    python /app/scripts/k72_apology_send.py --commit

    # Retry only failures from a prior --commit run:
    python /app/scripts/k72_apology_send.py --commit --retry-failed
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Make backend imports work when the script is invoked from /app/scripts.
_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv  # noqa: E402

# Load backend env BEFORE importing anything that reads env at import time
# (config.py reads MONGO_URL at module scope).
load_dotenv(_BACKEND / ".env")

from config import db, logger  # noqa: E402
from services.email import resend_adapter  # noqa: E402
from services.comms_env_guard import is_customer_email_kill_switch_on  # noqa: E402
from utils import new_id, now_iso  # noqa: E402


# ── Constants ────────────────────────────────────────────────────────
MEMO_PATH = Path("/app/memory/PHASE_K72_EMERGENCY_NO_FILTER_EMAIL_DIAG.md")
TENANT_SLUG = "aquaterra"
TENANT_ID_EXPECTED = "affdfbfa-88b9-4baa-ae45-2ef78531b6e4"
TENANT_NAME_EXPECTED = "Pool & Landscaping of Vistancia"
BATCH_ID_ORIGINAL = "f0c63d4a-20bb-4dca-9751-470465e1e702"
SUPPORT_PHONE = "602-887-4400"
FROM_NAME = "Pool & Landscaping of Vistancia"
FROM_EMAIL = "cs@plofv.com"
REPLY_TO = "cs@plofv.com"
SUBJECT = "A quick apology from Pool & Landscaping of Vistancia"
AUDIT_COLLECTION = "k72_apology_dispatch"
DISPATCH_ID = "k72.b.apology.2026-02"  # groups all rows from this dispatch
RATE_LIMIT_SLEEP_SEC = 0.2  # 5 sends / second

# Recipients we deliberately drop from the roster (fixtures / placeholders).
EXCLUDE_EMAILS = {"customer@aquaterra.com"}
EXCLUDE_NAMES = {"Deleted User", "UNKNOWN"}
EXCLUDE_DOMAINS = {"example.com", "example.invalid", "example.local"}


# ── Roster parsing ───────────────────────────────────────────────────
_ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|"
    r"\s*(sent|failed)\s*\|\s*([^|]*)\s*\|\s*$"
)


def parse_roster(memo_text: str) -> List[Dict[str, str]]:
    """Extract the recipient rows from section 3 of the K72 memo.

    Returns a list of ``{row, timestamp, customer, email, status}``
    dicts in the order they appear in the memo.
    """
    rows: List[Dict[str, str]] = []
    for line in memo_text.splitlines():
        m = _ROW_RE.match(line)
        if not m:
            continue
        rows.append({
            "row": m.group(1),
            "timestamp": m.group(2).strip(),
            "customer": m.group(3).strip(),
            "email": m.group(4).strip().lower(),
            "status": m.group(5).strip(),
            "error": m.group(6).strip(),
        })
    return rows


def filter_real_recipients(all_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Drop the fixture / placeholder rows so we only email real customers."""
    kept: List[Dict[str, str]] = []
    for r in all_rows:
        if r["status"] != "sent":
            continue
        if r["email"] in EXCLUDE_EMAILS:
            continue
        if r["customer"] in EXCLUDE_NAMES:
            continue
        domain = r["email"].rsplit("@", 1)[-1] if "@" in r["email"] else ""
        if domain in EXCLUDE_DOMAINS:
            continue
        kept.append(r)
    return kept


# ── Templating ───────────────────────────────────────────────────────
def render_body_text(first_name: str) -> str:
    return (
        f"Hi {first_name},\n"
        f"\n"
        f"You recently received an email from us with the subject "
        f"\"no-filter\" \u2014 that message was sent by mistake during "
        f"an internal system test and shouldn\u2019t have reached your "
        f"inbox. There\u2019s nothing you need to do, and your pool "
        f"service is completely unaffected.\n"
        f"\n"
        f"We\u2019re sorry for the confusion, and we\u2019ve already "
        f"put safeguards in place so this doesn\u2019t happen again.\n"
        f"\n"
        f"If you have any questions about your service \u2014 or if "
        f"that \"no filter\" wording made you wonder about something "
        f"specific on your pool \u2014 please reply to this email or "
        f"call us at {SUPPORT_PHONE}. We\u2019re happy to take a look.\n"
        f"\n"
        f"\u2014 The team at Pool & Landscaping of Vistancia\n"
        f"cs@plofv.com \u00b7 {SUPPORT_PHONE}\n"
    )


def render_body_html(first_name: str) -> str:
    return (
        f"<p>Hi {first_name},</p>"
        f"<p>You recently received an email from us with the subject "
        f"&ldquo;no-filter&rdquo; &mdash; that message was sent by "
        f"mistake during an internal system test and shouldn&rsquo;t "
        f"have reached your inbox. There&rsquo;s nothing you need to "
        f"do, and your pool service is completely unaffected.</p>"
        f"<p>We&rsquo;re sorry for the confusion, and we&rsquo;ve "
        f"already put safeguards in place so this doesn&rsquo;t "
        f"happen again.</p>"
        f"<p>If you have any questions about your service &mdash; or "
        f"if that &ldquo;no filter&rdquo; wording made you wonder "
        f"about something specific on your pool &mdash; please reply "
        f"to this email or call us at "
        f"<strong>{SUPPORT_PHONE}</strong>. We&rsquo;re happy to take "
        f"a look.</p>"
        f"<p>&mdash; The team at Pool &amp; Landscaping of Vistancia<br/>"
        f"cs@plofv.com &middot; {SUPPORT_PHONE}</p>"
    )


# ── Preflight ────────────────────────────────────────────────────────
async def preflight(commit: bool) -> Tuple[bool, List[str]]:
    """Return (ok, warnings). ``ok`` is False when a hard-fail check
    fires; warnings are printed but do not block dry-run."""
    warnings: List[str] = []
    errs: List[str] = []

    app_env = (os.environ.get("APP_ENV") or "").strip().lower()
    if commit:
        if app_env != "production":
            errs.append(
                f"APP_ENV={app_env!r} \u2014 refusing to --commit outside "
                f"production. Run this only on the prod pod."
            )
    else:
        if app_env != "production":
            warnings.append(
                f"APP_ENV={app_env!r} (not production) \u2014 dry-run is "
                f"allowed but a real send would refuse here."
            )

    if is_customer_email_kill_switch_on():
        msg = (
            "FEATURE_CUSTOMER_EMAIL_KILL_SWITCH is ON \u2014 the Resend "
            "adapter will short-circuit every customer send to a "
            "dry-run envelope. Flip the switch OFF (backend/.env) and "
            "``sudo supervisorctl restart backend`` before --commit."
        )
        if commit:
            errs.append(msg)
        else:
            warnings.append(msg)

    if commit and not (os.environ.get("RESEND_API_KEY") or "").strip():
        errs.append(
            "RESEND_API_KEY is not set \u2014 the adapter will fall back "
            "to mocked mode and every send will be a no-op."
        )

    tenant = await db.tenants.find_one({"slug": TENANT_SLUG}, {"_id": 0})
    if not tenant:
        errs.append(f"Tenant with slug={TENANT_SLUG!r} not found in this Mongo.")
    else:
        if tenant.get("id") != TENANT_ID_EXPECTED:
            warnings.append(
                f"Tenant id drift: expected {TENANT_ID_EXPECTED} but got "
                f"{tenant.get('id')!r}. Continuing \u2014 the script uses "
                f"the live tenant id from Mongo, not the constant."
            )
        if tenant.get("name") != TENANT_NAME_EXPECTED:
            warnings.append(
                f"Tenant name drift: expected {TENANT_NAME_EXPECTED!r} but "
                f"got {tenant.get('name')!r}."
            )

    if not MEMO_PATH.exists():
        errs.append(f"K72 memo not found at {MEMO_PATH} \u2014 cannot "
                    f"parse recipient roster.")

    return (not errs), (errs + warnings)


# ── DB helpers ───────────────────────────────────────────────────────
async def resolve_tenant_id() -> str:
    t = await db.tenants.find_one({"slug": TENANT_SLUG}, {"_id": 0, "id": 1})
    if not t or not t.get("id"):
        return TENANT_ID_EXPECTED
    return t["id"]


async def resolve_first_name(tenant_id: str, email: str,
                             roster_name: str) -> str:
    """Look up ``customers.first_name`` by email within the tenant.
    Falls back to the first token of the roster ``customer`` column,
    then to ``"there"``."""
    cust = await db.customers.find_one(
        {"tenant_id": tenant_id, "email": email},
        {"_id": 0, "first_name": 1, "name": 1},
    )
    if cust:
        fn = (cust.get("first_name") or "").strip()
        if fn:
            return fn
        # Fall back to first token of the ``name`` field.
        nm = (cust.get("name") or "").strip()
        if nm:
            return nm.split()[0]
    # Fall back to first token of the roster's ``customer`` column.
    if roster_name:
        first_token = roster_name.strip().split()[0]
        if first_token and first_token not in EXCLUDE_NAMES:
            return first_token
    return "there"


async def already_sent(tenant_id: str, email: str) -> Optional[Dict[str, Any]]:
    """Return the existing ``sent`` audit row for this recipient, or None."""
    return await db[AUDIT_COLLECTION].find_one(
        {
            "tenant_id": tenant_id,
            "email": email,
            "dispatch_id": DISPATCH_ID,
            "status": "sent",
        },
        {"_id": 0},
    )


async def audit_failed_row(tenant_id: str, email: str) -> Optional[Dict[str, Any]]:
    """Return the most recent ``failed`` row for a recipient (for
    --retry-failed)."""
    row = await db[AUDIT_COLLECTION].find_one(
        {
            "tenant_id": tenant_id,
            "email": email,
            "dispatch_id": DISPATCH_ID,
            "status": {"$ne": "sent"},
        },
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return row


async def write_audit(*, tenant_id: str, email: str, customer_name: str,
                      first_name: str, status: str,
                      provider_response_id: Optional[str],
                      error: Optional[str]) -> None:
    await db[AUDIT_COLLECTION].insert_one({
        "id": new_id(),
        "dispatch_id": DISPATCH_ID,
        "tenant_id": tenant_id,
        "original_batch_id": BATCH_ID_ORIGINAL,
        "email": email,
        "customer_name": customer_name,
        "first_name": first_name,
        "subject": SUBJECT,
        "status": status,  # sent | failed | suppressed | dry_run | mocked
        "provider": "resend",
        "provider_response_id": provider_response_id,
        "error": error,
        "created_at": now_iso(),
    })


# ── Send loop ────────────────────────────────────────────────────────
async def send_one(tenant_id: str, row: Dict[str, str],
                   *, commit: bool) -> Dict[str, Any]:
    email = row["email"]
    roster_name = row["customer"]
    first_name = await resolve_first_name(tenant_id, email, roster_name)
    text = render_body_text(first_name)
    html = render_body_html(first_name)

    if not commit:
        return {
            "email": email,
            "customer_name": roster_name,
            "first_name": first_name,
            "status": "dry_run",
            "provider_response_id": None,
            "error": None,
        }

    result = await resend_adapter.send(
        to=email,
        subject=SUBJECT,
        html=html,
        text=text,
        category="transactional",
        tenant_id=tenant_id,
        from_name=FROM_NAME,
        from_email=FROM_EMAIL,
        reply_to=REPLY_TO,
        allow_off_allowlist=True,
        audience="customer",
        idempotency_key=f"{DISPATCH_ID}:{email}",
    )
    status = result.get("provider_status") or "failed"
    await write_audit(
        tenant_id=tenant_id,
        email=email,
        customer_name=roster_name,
        first_name=first_name,
        status=status,
        provider_response_id=result.get("provider_response_id"),
        error=result.get("error"),
    )
    return {
        "email": email,
        "customer_name": roster_name,
        "first_name": first_name,
        "status": status,
        "provider_response_id": result.get("provider_response_id"),
        "error": result.get("error"),
    }


async def main_async(args: argparse.Namespace) -> int:
    commit = bool(args.commit)

    ok, notes = await preflight(commit=commit)
    print("PREFLIGHT")
    print("=========")
    for n in notes:
        print(f"  - {n}")
    if not notes:
        print("  - (all checks passed)")
    if not ok:
        print("\nPreflight blocked \u2014 aborting before any send.")
        return 2

    memo_text = MEMO_PATH.read_text(encoding="utf-8")
    all_rows = parse_roster(memo_text)
    real_rows = filter_real_recipients(all_rows)
    print(f"\nParsed {len(all_rows)} roster rows \u2014 "
          f"{len(real_rows)} real recipients after filtering.")
    if not real_rows:
        print("No recipients to send to \u2014 aborting.")
        return 3

    tenant_id = await resolve_tenant_id()
    print(f"Tenant: slug={TENANT_SLUG} id={tenant_id}")
    print(f"Mode:   {'COMMIT (LIVE SEND)' if commit else 'DRY-RUN (no writes)'}")
    if args.retry_failed:
        print("Filter: --retry-failed \u2014 only recipients with a prior "
              "non-sent audit row will be attempted.")

    sent, failed, skipped_dupe, skipped_no_retry, mocked, dry = 0, 0, 0, 0, 0, 0
    failures: List[Dict[str, Any]] = []

    for i, row in enumerate(real_rows, start=1):
        email = row["email"]

        # Idempotency: skip anything already ``sent``.
        prev = await already_sent(tenant_id, email) if commit else None
        if prev:
            skipped_dupe += 1
            print(f"  [{i:>3}/{len(real_rows)}] SKIP already-sent  {email}")
            continue

        # --retry-failed: only proceed if there's a prior non-sent row.
        if args.retry_failed and commit:
            prior_fail = await audit_failed_row(tenant_id, email)
            if not prior_fail:
                skipped_no_retry += 1
                print(f"  [{i:>3}/{len(real_rows)}] SKIP no-prior-fail {email}")
                continue

        outcome = await send_one(tenant_id, row, commit=commit)
        status = outcome["status"]
        rid = outcome.get("provider_response_id") or ""
        first_name = outcome.get("first_name") or ""
        line = (f"  [{i:>3}/{len(real_rows)}] {status.upper():<9} "
                f"{email:<45} first={first_name!r} rid={rid}")
        if outcome.get("error"):
            line += f" err={outcome['error']}"
        print(line)

        if status == "sent":
            sent += 1
        elif status == "dry_run":
            dry += 1
        elif status == "mocked":
            mocked += 1
        else:
            failed += 1
            failures.append(outcome)

        # Rate limit (skip the sleep on dry-run \u2014 no external calls made).
        if commit:
            await asyncio.sleep(RATE_LIMIT_SLEEP_SEC)

    print("\nSUMMARY")
    print("=======")
    print(f"  attempted        : {len(real_rows)}")
    print(f"  sent             : {sent}")
    print(f"  failed           : {failed}")
    print(f"  dry_run          : {dry}")
    print(f"  mocked (no key)  : {mocked}")
    print(f"  skipped duplicate: {skipped_dupe}")
    print(f"  skipped no-retry : {skipped_no_retry}")
    if failures:
        print("\nFAILURES")
        print("--------")
        for f in failures:
            print(f"  {f['email']}  err={f.get('error')}")

    if commit and failed:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="k72_apology_send",
        description=("K72.b apology dispatch \u2014 sends the "
                     "user-approved apology email to the 113 real "
                     "customers affected by the 2026-08-31 no-filter "
                     "incident. Dry-run by default \u2014 pass --commit "
                     "to actually send."),
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true",
                   help="Preview recipients + resolved first names "
                        "without sending or writing audit rows. Default.")
    g.add_argument("--commit", action="store_true",
                   help="Actually send the emails and write audit "
                        "rows. Requires APP_ENV=production, kill "
                        "switch OFF, RESEND_API_KEY set.")
    p.add_argument("--retry-failed", action="store_true",
                   help="Only send to recipients that have a non-sent "
                        "audit row from a prior --commit run.")
    return p


def main() -> None:
    args = build_parser().parse_args()
    if not args.commit:
        args.dry_run = True  # explicit or default
    code = asyncio.run(main_async(args))
    sys.exit(code)


if __name__ == "__main__":
    main()
