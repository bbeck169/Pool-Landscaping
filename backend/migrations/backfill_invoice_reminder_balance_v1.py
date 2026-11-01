"""Feb-2026 · TD-invoice-reminder-balance-backfill · Phase 1.

One-shot, idempotent, preserve-on-edit backfill that rewrites
``{{INVOICE_TOTAL}}`` → ``{{INVOICE_BALANCE}}`` in operator-authored
past-due-reminder templates whose body/subject carries balance
semantics.

Context — why this ticket exists
================================

The dedupe shipped as ``TD-invoice-total-dual-registry-drift``
(``6eae834e6``) removed the Batch 4 ``INVOICE_TOTAL`` registry entry
in ``services/marketing/merge_tags.py:2115`` that carried label
``"Invoice — Balance"`` + category ``"Finance"``.  Operators who
clicked that picker tile in the admin UI to insert a balance figure
into a custom past-due-reminder template got ``{{INVOICE_TOTAL}}``
written into their body — a token whose canonical semantic (post-
dedupe) is TOTAL, not balance.  Partial-payment invoices on those
tenant-authored templates will render the total (not the balance
owed) unless the send path happens to populate the flat
``ctx['invoice_total']`` key, which only ``emailer.py``'s invoice-
reminder path does today.

This scanner closes the gap: tenant-scoped past-due-reminder rows
whose body/subject carries ``{{INVOICE_TOTAL}}`` AND semantically
refers to balance (``balance``, ``outstanding``, ``owed``, ``past
due``) are rewritten to ``{{INVOICE_BALANCE}}``.  Operators who
hand-edited the body to something materially different (no balance
word) are classified as ``no_balance_semantic`` and left alone —
unless the operator explicitly passes ``--include-non-balance-
semantic`` to force the rewrite.

Scope
=====

**In scope** (``invoice-reminder class`` match on the shipped three
seed anchors):

  * ``marketing_templates`` rows where ``system_key ∈ {
      "system_tpl_invoice_past_due_7d_email",
      "system_tpl_invoice_past_due_7d_sms",
    }``                  — per-tenant canonical past-due reminders.
  * ``marketing_templates`` rows where ``code = "invoice_reminder_
    email"``                        — tenant override of the global
    fallback template.
  * BOTH the ``body`` and ``subject`` fields are rewritten when
    ``{{INVOICE_TOTAL}}`` appears in either (operator intent on a
    reminder template is one coherent surface).

**Out of scope**:

  * The ``tenant_id = None`` global seed-fallback row of ``invoice_
    reminder_email`` — its body/subject already use
    ``{{INVOICE_BALANCE}}`` post-Ticket-1, so the predicate naturally
    misses.  Belt-and-braces: the match query filters it out with
    ``tenant_id: {"$ne": None}``.
  * Templates outside the invoice-reminder class (job-completed,
    service-reports, marketing campaigns, receipts, confirmations,
    estimates, etc.) — the query filter never selects them.
  * Non-balance-semantic matches without ``--include-non-balance-
    semantic`` — e.g. a tenant who used ``{{INVOICE_TOTAL}}`` in a
    "Your invoice total was $X" confirmation blurb kept inside a
    reminder-category template.  Operator-steered via the escape
    hatch flag.
  * Mobile, FE, and all other BE routes.

Preserve-on-edit
================

The strict balance-semantic predicate IS the preserve-on-edit
mechanism (same convention as the shipped ``portal_invite_split_
email_temppassword_paragraph_v1`` migration).  There's no explicit
``is_user_edited`` flag anywhere on the ``marketing_templates``
collection; the PATCH route (`routers/marketing_templates.py:432`)
only bumps ``updated_at``.  Admins who reshaped their reminder body
such that no balance word is present classify as
``no_balance_semantic`` and are reported in the audit — not
mangled.

Idempotency
===========

A second ``--apply`` run after the first = all-zero.  Post-rewrite
``{{INVOICE_TOTAL}}`` no longer appears in body/subject of the
rewritten rows, so the match predicate correctly reports them as
``no_invoice_total_token`` (skip reason) and no writes occur.  The
idempotency does NOT require a sentinel doc — the per-row predicate
is strong enough — but a ``migration_runs`` audit doc per tenant per
``--apply`` invocation is still emitted for operator traceability
(matches ``recover_outbound_deferred_stuck_pending_v1``).

Tenant isolation
================

Every read + write is scoped by ``tenant_id``.  ``--all-tenants``
iterates per tenant with full isolation.  Fail-closed-per-tenant:
a tenant that errors mid-apply records partial counts in its audit
row + the exception is swallowed so the remaining tenants
continue.

CLI
===

    # dry-run on one tenant (default; prints what WOULD rewrite)
    python backend/migrations/backfill_invoice_reminder_balance_v1.py \\
      --tenant-id <tid>

    # apply on one tenant
    python backend/migrations/backfill_invoice_reminder_balance_v1.py \\
      --tenant-id <tid> --apply

    # dry-run across every active tenant
    python backend/migrations/backfill_invoice_reminder_balance_v1.py \\
      --all-tenants

    # apply across every tenant, forcing rewrite on
    # non-balance-semantic rows too (operator escape hatch)
    python backend/migrations/backfill_invoice_reminder_balance_v1.py \\
      --all-tenants --apply --include-non-balance-semantic
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import dotenv_values  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from utils import now_iso  # noqa: E402


logger = logging.getLogger("backfill_invoice_reminder_balance_v1")


# ═══════════════════════════════════════════════════════════════════
# Predicate.
# ═══════════════════════════════════════════════════════════════════

# Invoice-reminder-class anchors — the only three seed shapes the
# shipped FE picker could have landed ``{{INVOICE_TOTAL}}`` into.
INVOICE_REMINDER_SYSTEM_KEYS = (
    "system_tpl_invoice_past_due_7d_email",
    "system_tpl_invoice_past_due_7d_sms",
)
INVOICE_REMINDER_CODE = "invoice_reminder_email"

# Case-insensitive, whitespace-tolerant match for the catalog token
# — same shape as ``services/marketing/merge_tags.py:_TAG_RE`` so a
# rewrite target survives any whitespace variant an operator typed.
_INVOICE_TOTAL_TOKEN_RE = re.compile(
    r"\{\{\s*INVOICE_TOTAL\s*\}\}",
    flags=re.IGNORECASE,
)
# Canonical replacement — no whitespace, uppercase.
INVOICE_BALANCE_REPLACEMENT = "{{INVOICE_BALANCE}}"

# Balance-semantic heuristic — presence of ANY of these words
# anywhere in the concatenated ``subject + "\n" + body`` authorises
# the rewrite without ``--include-non-balance-semantic``.  Word
# boundaries + case-insensitive + optional hyphen in "past due".
_BALANCE_SEMANTIC_RE = re.compile(
    r"\b(balance|outstanding|owed|past[-\s]?due)\b",
    flags=re.IGNORECASE,
)


def _mongo_match(tenant_id: Optional[str]) -> Dict[str, Any]:
    """Build the invoice-reminder-class match query for one tenant.
    Excludes the ``tenant_id=None`` global fallback row.
    """
    anchor_clause: Dict[str, Any] = {"$or": [
        {"system_key": {"$in": list(INVOICE_REMINDER_SYSTEM_KEYS)}},
        {"code": INVOICE_REMINDER_CODE},
    ]}
    if tenant_id is None:
        # ``--all-tenants`` mode: iterate per tenant below; this
        # branch is unused but defined for symmetry.
        return {"$and": [anchor_clause, {"tenant_id": {"$ne": None}}]}
    return {"$and": [anchor_clause, {"tenant_id": tenant_id}]}


def _has_balance_semantic(subject: Optional[str], body: Optional[str]) -> bool:
    hay = f"{subject or ''}\n{body or ''}"
    return bool(_BALANCE_SEMANTIC_RE.search(hay))


def _has_invoice_total_token(*fields: Optional[str]) -> bool:
    for f in fields:
        if f and _INVOICE_TOTAL_TOKEN_RE.search(f):
            return True
    return False


def _rewrite_field(value: Optional[str]) -> str:
    """Rewrite every ``{{INVOICE_TOTAL}}`` in ``value`` to the
    canonical ``{{INVOICE_BALANCE}}``.  Returns the input verbatim
    when the field is empty or has no match."""
    if not value:
        return value or ""
    return _INVOICE_TOTAL_TOKEN_RE.sub(INVOICE_BALANCE_REPLACEMENT, value)


# ═══════════════════════════════════════════════════════════════════
# Scanner
# ═══════════════════════════════════════════════════════════════════

async def _list_tenants(db) -> List[str]:
    rows = await db.tenants.find(
        {"$or": [{"active": {"$ne": False}},
                   {"active": {"$exists": False}}]},
        {"_id": 0, "id": 1},
    ).to_list(10_000)
    return [r["id"] for r in rows if r.get("id")]


async def _backfill_tenant(
    db, tenant_id: str, *,
    dry_run: bool,
    include_non_balance_semantic: bool,
) -> Dict[str, Any]:
    """Scan + optionally rewrite one tenant's invoice-reminder
    templates.  Returns a per-tenant summary with aggregate counts +
    sample row details for operator audit.

    Fail-closed-per-tenant: on exception inside the per-row loop,
    ``error`` is set + the exception is swallowed so other tenants
    continue.
    """
    summary: Dict[str, Any] = {
        "rows_scanned":                0,
        "rows_matched":                0,
        "rows_rewritten":              0,
        "rows_skipped":                0,
        "skip_reasons": {
            "no_invoice_total_token":  0,
            "no_balance_semantic":     0,
        },
        "sample_matches":              [],
        "error":                       None,
    }
    _SAMPLE_CAP = 5

    try:
        cursor = db.marketing_templates.find(
            _mongo_match(tenant_id),
            {"_id": 0, "id": 1, "tenant_id": 1,
             "system_key": 1, "code": 1, "channel": 1,
             "subject": 1, "body": 1},
        )
        async for row in cursor:
            summary["rows_scanned"] += 1
            subject = row.get("subject")
            body = row.get("body")

            if not _has_invoice_total_token(subject, body):
                summary["rows_skipped"] += 1
                summary["skip_reasons"]["no_invoice_total_token"] += 1
                continue

            # Row has the token.  Apply the balance-semantic gate
            # unless the operator forced it with the escape hatch.
            balance_hit = _has_balance_semantic(subject, body)
            if not balance_hit and not include_non_balance_semantic:
                summary["rows_skipped"] += 1
                summary["skip_reasons"]["no_balance_semantic"] += 1
                continue

            summary["rows_matched"] += 1
            new_subject = _rewrite_field(subject)
            new_body = _rewrite_field(body)

            if len(summary["sample_matches"]) < _SAMPLE_CAP:
                summary["sample_matches"].append({
                    "id":         row.get("id"),
                    "system_key": row.get("system_key"),
                    "code":       row.get("code"),
                    "channel":    row.get("channel"),
                    "balance_semantic_hit": balance_hit,
                    "before_subject_snippet":
                        _snippet(subject),
                    "after_subject_snippet":
                        _snippet(new_subject),
                    "before_body_snippet":
                        _snippet(body),
                    "after_body_snippet":
                        _snippet(new_body),
                })

            if dry_run:
                continue

            # Tenant-isolated write: filter by both ``id`` AND
            # ``tenant_id`` so a mis-shaped scan can never cross
            # tenant.
            set_patch: Dict[str, Any] = {
                "body":       new_body,
                "updated_at": now_iso(),
            }
            # SMS rows have ``subject = None``; don't overwrite None
            # with "".
            if subject is not None:
                set_patch["subject"] = new_subject
            await db.marketing_templates.update_one(
                {"id": row["id"], "tenant_id": tenant_id},
                {"$set": set_patch},
            )
            summary["rows_rewritten"] += 1
    except Exception as exc:  # noqa: BLE001
        summary["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "[backfill_invoice_reminder_balance_v1] tenant=%s "
            "aborted mid-scan: %s", tenant_id, exc,
        )
    return summary


def _snippet(value: Optional[str], *, radius: int = 40) -> str:
    """Trim a field around the first match of ``{{INVOICE_TOTAL}}``
    (pre-rewrite) or ``{{INVOICE_BALANCE}}`` (post-rewrite) for
    operator-readable before/after audit output.  Falls back to the
    first ``radius*2`` chars when neither token is present."""
    if not value:
        return ""
    s = str(value)
    for probe in ("{{INVOICE_TOTAL}}", "{{INVOICE_BALANCE}}"):
        idx = s.upper().find(probe)
        if idx >= 0:
            start = max(0, idx - radius)
            end = min(len(s), idx + len(probe) + radius)
            prefix = "…" if start > 0 else ""
            suffix = "…" if end < len(s) else ""
            return f"{prefix}{s[start:end]}{suffix}"
    return s[: radius * 2] + ("…" if len(s) > radius * 2 else "")


# ═══════════════════════════════════════════════════════════════════
# Top-level entry point
# ═══════════════════════════════════════════════════════════════════

async def backfill_invoice_reminder_balance(
    db, *,
    tenant_id: Optional[str] = None,
    all_tenants: bool = False,
    dry_run: bool = True,
    include_non_balance_semantic: bool = False,
) -> Dict[str, Any]:
    """Pass ``tenant_id`` XOR ``all_tenants``.  ``dry_run`` (default
    True) scans and reports without writing; ``dry_run=False``
    applies.  ``include_non_balance_semantic`` is the operator
    escape hatch — forces rewrite on rows whose body/subject carries
    ``{{INVOICE_TOTAL}}`` but no balance word.
    """
    if tenant_id and all_tenants:
        raise ValueError(
            "pass either --tenant-id OR --all-tenants, not both",
        )
    if not tenant_id and not all_tenants:
        raise ValueError(
            "pass --tenant-id <id> OR --all-tenants (explicit)",
        )

    tids = [tenant_id] if tenant_id else await _list_tenants(db)

    per_tenant: Dict[str, Dict[str, Any]] = {}
    totals = {
        "tenants_scanned":  0,
        "rows_scanned":     0,
        "rows_matched":     0,
        "rows_rewritten":   0,
        "rows_skipped":     0,
        "skip_reasons": {
            "no_invoice_total_token":  0,
            "no_balance_semantic":     0,
        },
        "tenants_with_errors": 0,
    }

    audit_at = datetime.now(timezone.utc).isoformat()

    for tid in tids:
        if not tid:
            continue
        totals["tenants_scanned"] += 1
        summary = await _backfill_tenant(
            db, tid,
            dry_run=dry_run,
            include_non_balance_semantic=include_non_balance_semantic,
        )
        per_tenant[tid] = summary
        totals["rows_scanned"]   += summary["rows_scanned"]
        totals["rows_matched"]   += summary["rows_matched"]
        totals["rows_rewritten"] += summary["rows_rewritten"]
        totals["rows_skipped"]   += summary["rows_skipped"]
        totals["skip_reasons"]["no_invoice_total_token"] += \
            summary["skip_reasons"]["no_invoice_total_token"]
        totals["skip_reasons"]["no_balance_semantic"] += \
            summary["skip_reasons"]["no_balance_semantic"]
        if summary["error"]:
            totals["tenants_with_errors"] += 1
        if not dry_run:
            await db.migration_runs.insert_one({
                "id":        str(uuid.uuid4()),
                "name":      "backfill_invoice_reminder_balance_v1",
                "tenant_id": tid,
                "status":    "error" if summary["error"] else "ok",
                "include_non_balance_semantic":
                    bool(include_non_balance_semantic),
                "summary":   {k: v for k, v in summary.items()
                              if k != "sample_matches"},
                "at":        audit_at,
            })

    return {
        "dry_run":                      dry_run,
        "all_tenants":                  bool(all_tenants and not tenant_id),
        "include_non_balance_semantic": bool(include_non_balance_semantic),
        "totals":                       totals,
        "per_tenant":                   per_tenant,
    }


# ─────────────────────────── CLI ──────────────────────────────────
def _print_summary(result: Dict[str, Any]) -> None:
    totals = result["totals"]
    print(f"include_non_balance_semantic = "
          f"{result['include_non_balance_semantic']}")
    print(f"tenants_scanned              = {totals['tenants_scanned']}")
    print(f"rows_scanned                 = {totals['rows_scanned']}")
    print(f"rows_matched                 = {totals['rows_matched']}")
    print(f"rows_rewritten               = {totals['rows_rewritten']}")
    print(f"rows_skipped                 = {totals['rows_skipped']}")
    print(f"  no_invoice_total_token     = "
          f"{totals['skip_reasons']['no_invoice_total_token']}")
    print(f"  no_balance_semantic        = "
          f"{totals['skip_reasons']['no_balance_semantic']}")
    print(f"tenants_with_errors          = "
          f"{totals['tenants_with_errors']}")
    print()
    if not result["per_tenant"]:
        return
    tenants_with_matches = [
        (tid, row) for tid, row in result["per_tenant"].items()
        if row["rows_matched"] or row["error"]
    ]
    if not tenants_with_matches:
        print("No tenants had matched rows.")
        return
    print("per-tenant (tenants with matches or errors only):")
    for tid, row in tenants_with_matches:
        err = row.get("error")
        print(
            f"  tenant={tid}  scanned={row['rows_scanned']}  "
            f"matched={row['rows_matched']}  "
            f"rewritten={row['rows_rewritten']}  "
            f"skipped={row['rows_skipped']}"
            + (f"  [ERROR] {err}" if err else "")
        )
        for sample in row.get("sample_matches") or []:
            print(
                f"    sample  id={sample['id']}  "
                f"system_key={sample['system_key']!r}  "
                f"code={sample['code']!r}  channel={sample['channel']}  "
                f"balance_hit={sample['balance_semantic_hit']}"
            )
            if sample["before_subject_snippet"]:
                print(f"      subject BEFORE: "
                      f"{sample['before_subject_snippet']!r}")
                print(f"      subject AFTER:  "
                      f"{sample['after_subject_snippet']!r}")
            if sample["before_body_snippet"]:
                print(f"      body    BEFORE: "
                      f"{sample['before_body_snippet']!r}")
                print(f"      body    AFTER:  "
                      f"{sample['after_body_snippet']!r}")


async def _cli(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(description=(
        "Rewrite ``{{INVOICE_TOTAL}}`` → ``{{INVOICE_BALANCE}}`` in "
        "operator-authored past-due-reminder templates with balance "
        "semantics.  Dry-run by default."
    ))
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--tenant-id", default=None,
                         help="Scope to one tenant.")
    group.add_argument("--all-tenants", action="store_true",
                         help="Scope to every active tenant.")
    p.add_argument("--apply", action="store_true",
                    help="Actually mutate.  Default is dry-run.")
    p.add_argument("--include-non-balance-semantic",
                    action="store_true",
                    help=("Operator escape hatch: force rewrite on "
                            "rows whose body/subject carries "
                            "``{{INVOICE_TOTAL}}`` but no balance "
                            "word.  Use when the heuristic misses."))
    args = p.parse_args(argv)

    env = dotenv_values(
        str(Path(__file__).resolve().parents[1] / ".env"),
    )
    mongo_url = env.get("MONGO_URL") or ""
    db_name = env.get("DB_NAME") or ""
    if not mongo_url or not db_name:
        print("MONGO_URL / DB_NAME missing from backend/.env",
              file=sys.stderr)
        sys.exit(2)
    db = AsyncIOMotorClient(mongo_url)[db_name]

    scope = (f"tenant={args.tenant_id}"
             if args.tenant_id else "ALL TENANTS")
    print(f"== backfill-invoice-reminder-balance · dry-run · "
          f"scope={scope} ==")
    dry = await backfill_invoice_reminder_balance(
        db,
        tenant_id=args.tenant_id,
        all_tenants=bool(args.all_tenants and not args.tenant_id),
        dry_run=True,
        include_non_balance_semantic=
            args.include_non_balance_semantic,
    )
    _print_summary(dry)
    if not args.apply:
        print("\nDry-run only.  Re-run with --apply to mutate.")
        return

    print(f"\n== backfill-invoice-reminder-balance · APPLY · "
          f"scope={scope} ==")
    real = await backfill_invoice_reminder_balance(
        db,
        tenant_id=args.tenant_id,
        all_tenants=bool(args.all_tenants and not args.tenant_id),
        dry_run=False,
        include_non_balance_semantic=
            args.include_non_balance_semantic,
    )
    _print_summary(real)

    print("\n-- idempotency re-check (dry-run) --")
    recheck = await backfill_invoice_reminder_balance(
        db,
        tenant_id=args.tenant_id,
        all_tenants=bool(args.all_tenants and not args.tenant_id),
        dry_run=True,
        include_non_balance_semantic=
            args.include_non_balance_semantic,
    )
    _print_summary(recheck)
    if recheck["totals"]["rows_matched"] > 0:
        print("WARNING: idempotency re-check still shows matched rows.")


if __name__ == "__main__":
    asyncio.run(_cli())
