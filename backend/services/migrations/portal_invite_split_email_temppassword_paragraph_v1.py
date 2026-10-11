"""M-TAG-FIX FOLLOWUP · Feb-2026 · Split-Email+TempPassword paragraph.

Companion to the portal-invite empty-TEMP_PASSWORD paragraph-strip
fix in ``routers/portal_admin.py::_try_send_reset_email``. That fix
removes the ``<p>...{{TEMP_PASSWORD}}...</p>`` paragraph from the
HTML body when no password is minted (e.g. re-sending a login
reminder on an already-active portal account).

The LEGACY seed shape colocated the Email address AND the Temporary
password inside the SAME ``<p>`` tag, separated by a ``<br>``::

    <p><strong>Email:</strong> {{TO}}<br>
       <strong>Temporary password:</strong> {{TEMP_PASSWORD}}</p>

When ``TEMP_PASSWORD`` is empty the paragraph-removal regex strips
the ENTIRE ``<p>`` — which also deletes the customer's Email line
from the HTML.  The plain-text surface keeps the Email because it's
line-oriented, so the two surfaces diverge.

This one-shot migration rewrites every ``marketing_templates`` row
where ``code=portal_invite_email`` from the single-paragraph legacy
shape to the two-paragraph canonical shape::

    <p><strong>Email:</strong> {{TO}}</p>
    <p><strong>Temporary password:</strong> {{TEMP_PASSWORD}}</p>

The surrounding template body (greeting, intro, sign-in CTA, etc.)
is preserved byte-for-byte.

Preserves user edits
────────────────────
The match predicate is a DEFENSIVE regex that fires only when the
paragraph contains BOTH ``{{TO}}`` and ``{{TEMP_PASSWORD}}`` AND
the Email / Temporary-password text labels AND a ``<br>`` between
them.  Admins who hand-edited their template to a materially
different shape are SKIPPED — reported in the ``templates_skipped``
tally with ``reason="shape_mismatch"`` so we can audit the long
tail without mangling anyone's custom template.

Dry-run default
───────────────
``run(db, dry_run=True)`` (the default) scans and reports what
WOULD be migrated — no writes.  Admins invoke with
``dry_run=False`` to apply.  Dry-run mode never stamps the sentinel
so a follow-up fix run proceeds normally.

Idempotency
───────────
Sentinel: ``db.migration_status.find_one({"key": MIGRATION_KEY})``.
Second fix run short-circuits with
``{"ok": True, "skipped": True, "reason": "already_ran"}``.

Per-row idempotency is stronger than the sentinel: even if the
sentinel is manually cleared, re-running finds no legacy-shape rows
on already-migrated bodies (they no longer match the predicate) and
correctly counts them as ``templates_skipped`` with
``reason="shape_mismatch"`` or ``reason="already_split"`` without
touching them.

Failure mode
────────────
Per-row exceptions are caught + counted in ``templates_failed``.
Loop continues.  Sentinel is stamped with ``must_succeed=False``
posture so the boot sequence (if ever auto-wired) never blocks on
a partial run.  Current wiring is admin-triggered via
``POST /api/admin/migrations/portal-invite-split-paragraph`` — no
auto-boot.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(
    "services.migrations."
    "portal_invite_split_email_temppassword_paragraph_v1",
)

MIGRATION_KEY = (
    "portal_invite_split_email_temppassword_paragraph_v1"
)
TARGET_CODE = "portal_invite_email"


# ═══════════════════════════════════════════════════════════════════
# Match predicate.
#
# Fires ONLY on the legacy single-paragraph shape — a ``<p>`` tag
# that holds BOTH ``Email: {{TO}}`` AND
# ``Temporary password: {{TEMP_PASSWORD}}``, separated by a
# ``<br>``.  Case-insensitive on the label text; whitespace-tolerant
# around the merge-tag braces + the ``<br>`` tag.
#
# Deliberately strict — admins who re-worded the labels (``Login
# email:``, ``Your password:``, …) are SKIPPED, not mangled.
# Operators can run this migration repeatedly as new tenants land
# on the legacy seed; the predicate correctly reports already-split
# tenants as ``already_split``.
# ═══════════════════════════════════════════════════════════════════
_LEGACY_P_RE = re.compile(
    r"<p[^>]*>"                                     # opening <p>
    r"(?:(?!</?p\b)[\s\S])*?"                       # (no nested <p>)
    r"<strong>\s*Email\s*:\s*</strong>\s*"
    r"\{\{\s*TO\s*\}\}"
    r"(?:(?!</?p\b)[\s\S])*?"
    r"<\s*br\s*/?\s*>"                              # <br>
    r"(?:(?!</?p\b)[\s\S])*?"
    r"<strong>\s*Temporary\s*password\s*:\s*</strong>\s*"
    r"(?:<code>\s*)?"                               # optional <code>
    r"\{\{\s*TEMP_PASSWORD\s*\}\}"
    r"\s*(?:</code>)?"
    r"(?:(?!</?p\b)[\s\S])*?"
    r"</p>",
    re.IGNORECASE,
)


def _split_paragraph(body: str) -> Tuple[str, int]:
    """Return ``(new_body, substitutions)``.

    Rewrites the legacy single-paragraph Email+TempPassword shape to
    two separate ``<p>`` tags.  Byte-identical for bodies that don't
    match the legacy predicate.
    """
    if not isinstance(body, str) or not body:
        return body or "", 0

    def _replace(match: "re.Match[str]") -> str:
        # Two canonical paragraphs preserving the merge tags.
        # We rebuild from the match's known shape rather than
        # trying to splice around the <br> — the predicate guarantees
        # the shape, so a clean rewrite is safer than surgical edits.
        return (
            "<p><strong>Email:</strong> {{TO}}</p>"
            "<p><strong>Temporary password:</strong> "
            "<code>{{TEMP_PASSWORD}}</code></p>"
        )

    new_body, count = _LEGACY_P_RE.subn(_replace, body)
    return new_body, count


def _classify_skip(body: str) -> str:
    """Return a human-readable skip reason for reporting.

    * ``already_split`` — the body contains two SEPARATE paragraphs
      for Email and Temporary password (the canonical shape).
    * ``no_temp_password_tag`` — the body doesn't contain
      ``{{TEMP_PASSWORD}}`` at all (admin removed it).
    * ``shape_mismatch`` — the body has ``{{TEMP_PASSWORD}}`` but
      not in the recognised legacy shape (hand-edited template).
    """
    if not isinstance(body, str):
        return "shape_mismatch"

    # Already-split heuristic — two separate <p> tags, each
    # containing one of the two tags.
    _email_p = re.search(
        r"<p[^>]*>(?:(?!</?p\b)[\s\S])*?\{\{\s*TO\s*\}\}"
        r"(?:(?!</?p\b)[\s\S])*?</p>",
        body, re.IGNORECASE,
    )
    _pw_p = re.search(
        r"<p[^>]*>(?:(?!</?p\b)[\s\S])*?\{\{\s*TEMP_PASSWORD\s*\}\}"
        r"(?:(?!</?p\b)[\s\S])*?</p>",
        body, re.IGNORECASE,
    )
    if _email_p and _pw_p and _email_p.group(0) != _pw_p.group(0):
        return "already_split"

    if not re.search(r"\{\{\s*TEMP_PASSWORD\s*\}\}", body, re.IGNORECASE):
        return "no_temp_password_tag"

    return "shape_mismatch"


async def run(
    db: Any,
    *,
    dry_run: bool = True,
    row_filter: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Scan + optionally rewrite every ``marketing_templates`` row
    where ``code=portal_invite_email`` from the legacy
    single-paragraph shape to the canonical two-paragraph shape.

    Args:
        db: Motor async database handle.
        dry_run: When True (default) report what WOULD change — no
            writes.  Set False to apply.
        row_filter: OPTIONAL extra Mongo predicate composed into the
            row-scan query via ``$and``.  Tests pass a scoping
            filter (``{"tenant_id": {"$regex": "^TEST-"}}``) to
            isolate seeded rows from co-existing data.

    Returns:
        Migration report dict::

            {
                "ok": bool,
                "dry_run": bool,
                "skipped": bool,
                "reason": str | absent,
                "tenants_scanned": int,
                "templates_matched": int,
                "templates_migrated": int,
                "templates_skipped": int,
                "skip_reasons": {"already_split": int,
                                 "no_temp_password_tag": int,
                                 "shape_mismatch": int},
                "templates_failed": int,
            }
    """
    sentinel = await db.migration_status.find_one(
        {"key": MIGRATION_KEY}, {"_id": 0},
    )
    # Dry-run never consults nor stamps the sentinel so the FIRST
    # audit pass always runs cleanly.  Only a fix run short-
    # circuits on a prior fix run's completion sentinel.
    if (not dry_run) and sentinel and sentinel.get("completed_at"):
        return {
            "ok": True,
            "dry_run": False,
            "skipped": True,
            "reason": "already_ran",
        }

    tenants_scanned: set[str] = set()
    templates_matched = 0
    templates_migrated = 0
    templates_skipped = 0
    skip_reasons: Dict[str, int] = {
        "already_split": 0,
        "no_temp_password_tag": 0,
        "shape_mismatch": 0,
    }
    templates_failed = 0
    failures: List[Dict[str, str]] = []
    _FAILURE_LOG_CAP = 50

    _match: Dict[str, Any] = {"code": TARGET_CODE}
    if row_filter:
        _match = {"$and": [_match, row_filter]}

    cursor = db.marketing_templates.find(
        _match,
        {"_id": 0, "id": 1, "tenant_id": 1, "body": 1, "code": 1},
    )

    async for row in cursor:
        row_id = row.get("id")
        tenant_id = row.get("tenant_id")
        body = row.get("body")

        if tenant_id:
            tenants_scanned.add(tenant_id)

        if not row_id or body is None:
            # Malformed row — count as skip with shape_mismatch so
            # it shows up in the operator report.
            templates_skipped += 1
            skip_reasons["shape_mismatch"] += 1
            continue

        try:
            new_body, count = _split_paragraph(body)
            if count == 0:
                # Legacy shape not found — classify + skip.
                templates_skipped += 1
                skip_reasons[_classify_skip(body)] += 1
                continue

            templates_matched += 1

            if dry_run:
                # Audit pass — don't write.
                continue

            await db.marketing_templates.update_one(
                {"id": row_id, "code": TARGET_CODE},
                {"$set": {
                    "body": new_body,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            templates_migrated += 1
        except Exception as _row_e:                             # noqa: BLE001
            templates_failed += 1
            logger.warning(
                "[portal_invite_split_paragraph_v1] per-row error "
                "id=%s tenant=%s: %s",
                row_id, tenant_id, _row_e,
            )
            if len(failures) < _FAILURE_LOG_CAP:
                failures.append({
                    "id": str(row_id or ""),
                    "tenant_id": str(tenant_id or ""),
                    "error": str(_row_e)[:200],
                })

    # Sentinel stamp ONLY on a successful fix run.  Dry-run leaves
    # the sentinel untouched so the operator can safely iterate.
    if not dry_run:
        await db.migration_status.update_one(
            {"key": MIGRATION_KEY},
            {"$set": {
                "key": MIGRATION_KEY,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "tenants_scanned": len(tenants_scanned),
                "templates_matched": templates_matched,
                "templates_migrated": templates_migrated,
                "templates_skipped": templates_skipped,
                "skip_reasons": skip_reasons,
                "templates_failed": templates_failed,
                "failures": failures,
                "must_succeed": False,
            },
             "$unset": {"error": "", "last_attempt_at": ""}},
            upsert=True,
        )
    logger.info(
        "[portal_invite_split_paragraph_v1] %s complete — "
        "tenants=%s matched=%s migrated=%s skipped=%s failed=%s",
        "DRY-RUN" if dry_run else "FIX-RUN",
        len(tenants_scanned), templates_matched, templates_migrated,
        templates_skipped, templates_failed,
    )
    return {
        "ok": True,
        "dry_run": dry_run,
        "skipped": False,
        "tenants_scanned": len(tenants_scanned),
        "templates_matched": templates_matched,
        "templates_migrated": templates_migrated,
        "templates_skipped": templates_skipped,
        "skip_reasons": skip_reasons,
        "templates_failed": templates_failed,
    }
