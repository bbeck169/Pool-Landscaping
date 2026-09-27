"""Feb-2026 · Portal-invite placeholder rebrace migration.

Companion to the portal-invite merge-tags fix in
``routers/portal_admin.py::_try_send_reset_email``. That fix swapped
``str.format(**kw)`` for
``services.marketing.merge_tags.render_template`` so that catalog
tokens (``{{COMPANY_NAME}}``, ``{{COMPANY_PHONE}}``, etc.) inside
DB-edited portal-invite bodies actually resolve at render time.

Existing tenants have ``marketing_templates`` rows seeded with the
LEGACY single-brace placeholders — ``{name}``, ``{to}``,
``{temp_password}``, ``{login_url}``. The new renderer's regex only
matches double-brace ``{{TOKEN}}`` and passes single-brace through
verbatim, so without this backfill every live tenant's next portal
invite would ship literal ``{name}`` in the body.

This one-shot migration rewrites the four legacy placeholders to
their canonical double-brace equivalents on every
``marketing_templates`` row where ``code=portal_invite_email``:

    {name}          →  {{NAME}}
    {to}            →  {{TO}}
    {temp_password} →  {{TEMP_PASSWORD}}
    {login_url}     →  {{LOGIN_URL}}

Preserves user edits
────────────────────
* Substitution is scoped to the four enumerated placeholders only
  — everything else in the body stays byte-identical. Unrelated
  brace literals (e.g. a ``{2024}`` label a user added) are
  untouched.
* Uses a negative-lookbehind/lookahead regex so an already-
  double-braced ``{{name}}`` (should any tenant have edited to the
  double-brace form ahead of this migration) is preserved.
* Only rows whose body actually contains one of the four legacy
  substrings after the regex match are updated — no-op rows never
  hit the database.

Idempotency
───────────
Sentinel: ``db.migration_status.find_one({"key": MIGRATION_KEY})``.
Second run short-circuits with
``{"ok": True, "skipped": True, "reason": "already_ran"}``.

Per-row idempotency is stronger than the sentinel: even if the
sentinel is manually cleared, re-running finds no legacy
placeholders on already-rebrace rows and correctly counts them as
``rows_skipped_no_legacy`` without touching them.

Failure mode
────────────
Per-row exceptions are caught + counted in ``rows_failed``. Loop
continues. Sentinel is stamped with ``must_succeed=False`` posture
so the boot sequence never blocks on a partial run.

Rollback
────────
Template-body normalization is NOT perfectly reversible without a
pre-migration snapshot — the original single-brace bodies are not
retained anywhere in the DB after the migration runs. Recommended
recovery when a rollback is needed:

  1. Restore from a snapshot taken BEFORE the migration ran (ops
     retains hourly Mongo snapshots).
  2. Clear the sentinel to un-gate the migration:
       ``db.migration_status.delete_one({"key":
        "portal_invite_placeholder_rebrace_v1"})``

Cheap sentinel-only rollback (safe on the migration's own state
but does NOT restore any body content):

    db.migration_status.delete_one(
        {"key": "portal_invite_placeholder_rebrace_v1"},
    )

The migration is idempotent, so replaying after a sentinel clear
against already-rebrace bodies is a no-op — this is why the
rollback recipe only touches the sentinel.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(
    "services.migrations.portal_invite_placeholder_rebrace_v1",
)

MIGRATION_KEY = "portal_invite_placeholder_rebrace_v1"
TARGET_CODE = "portal_invite_email"


# ═══════════════════════════════════════════════════════════════════
# Placeholder catalogue — legacy substring → canonical double-brace.
#
# NOTE: The regex uses negative lookbehind/lookahead on ``{`` and
# ``}`` so a body that has ALREADY been rebrace to ``{{name}}`` is
# preserved verbatim (both idempotency AND user-safety guardrail).
# ═══════════════════════════════════════════════════════════════════
_LEGACY_TO_CANONICAL: Dict[str, str] = {
    "name": "{{NAME}}",
    "to": "{{TO}}",
    "temp_password": "{{TEMP_PASSWORD}}",
    "login_url": "{{LOGIN_URL}}",
}


def _rebrace(body: str) -> Tuple[str, int]:
    """Return ``(new_body, total_substitutions)``.

    Substitutes single-brace legacy placeholders (``{name}``,
    ``{to}``, ``{temp_password}``, ``{login_url}``) for their
    canonical double-brace equivalents while preserving any other
    brace literals in the body (e.g. ``{2024}`` in user prose).
    Already-double-braced placeholders (``{{name}}``) are also
    preserved via the negative-lookbehind/lookahead in the regex.
    """
    if not isinstance(body, str) or not body:
        return body or "", 0
    total = 0
    new_body = body
    for token, canonical in _LEGACY_TO_CANONICAL.items():
        # (?<!\{) — not preceded by another ``{`` (so ``{{token}}``
        #           is skipped)
        # \{token\} — the literal single-brace placeholder
        # (?!\})   — not followed by another ``}`` (defensive; catches
        #           the ``{token}}`` malformed case)
        pattern = r"(?<!\{)\{" + re.escape(token) + r"\}(?!\})"
        new_body, count = re.subn(pattern, canonical, new_body)
        total += count
    return new_body, total


async def run(
    db: Any,
    *,
    row_filter: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Rewrite legacy single-brace placeholders on every
    ``marketing_templates`` row where ``code=portal_invite_email``.

    Args:
        db: Motor async database handle.
        row_filter: OPTIONAL extra Mongo predicate composed into the
            row-scan query via ``$and``. Production callers (the
            boot sequence) pass ``None`` so every tenant's row is
            scanned. Tests pass a scoping filter (e.g.
            ``{"tenant_id": {"$regex": "^TEST-"}}``) to isolate
            their seeded rows from co-existing data.

    Returns:
        Migration report dict::

            {
                "ok": bool,
                "skipped": bool,
                "reason": str | absent,
                "rows_scanned": int,
                "rows_rebrace": int,
                "rows_skipped_no_legacy": int,
                "rows_failed": int,
                "error": str | absent,
            }
    """
    sentinel = await db.migration_status.find_one(
        {"key": MIGRATION_KEY}, {"_id": 0},
    )
    if sentinel and sentinel.get("completed_at"):
        return {
            "ok": True, "skipped": True,
            "reason": "already_ran",
        }

    rows_scanned = 0
    rows_rebrace = 0
    rows_skipped_no_legacy = 0
    rows_failed = 0
    failures: List[Dict[str, str]] = []
    _FAILURE_LOG_CAP = 50

    # Detection cursor — every portal_invite_email row.  The
    # per-row _rebrace check filters out rows without legacy
    # placeholders so we never issue a no-op Mongo update.
    _match: Dict[str, Any] = {"code": TARGET_CODE}
    if row_filter:
        _match = {"$and": [_match, row_filter]}

    cursor = db.marketing_templates.find(
        _match,
        {"_id": 0, "id": 1, "tenant_id": 1, "body": 1, "code": 1},
    )

    async for row in cursor:
        rows_scanned += 1
        row_id = row.get("id")
        tenant_id = row.get("tenant_id")
        body = row.get("body")

        if not row_id or body is None:
            # Malformed row — skip silently (not a failure, just
            # unreachable for a body normalization pass).
            rows_skipped_no_legacy += 1
            continue

        try:
            new_body, count = _rebrace(body)
            if count == 0:
                # No legacy placeholders present — already rebrace
                # or the tenant edited them all out.  No-op.
                rows_skipped_no_legacy += 1
                continue

            await db.marketing_templates.update_one(
                {"id": row_id, "code": TARGET_CODE},
                {"$set": {
                    "body": new_body,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            rows_rebrace += 1
        except Exception as _row_e:                             # noqa: BLE001
            rows_failed += 1
            logger.warning(
                "[portal_invite_placeholder_rebrace_v1] per-row "
                "error id=%s tenant=%s: %s",
                row_id, tenant_id, _row_e,
            )
            if len(failures) < _FAILURE_LOG_CAP:
                failures.append({
                    "id": str(row_id or ""),
                    "tenant_id": str(tenant_id or ""),
                    "error": str(_row_e)[:200],
                })

    # Sentinel completion — always write on loop-exit.
    await db.migration_status.update_one(
        {"key": MIGRATION_KEY},
        {"$set": {
            "key": MIGRATION_KEY,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "rows_scanned": rows_scanned,
            "rows_rebrace": rows_rebrace,
            "rows_skipped_no_legacy": rows_skipped_no_legacy,
            "rows_failed": rows_failed,
            "failures": failures,
            "must_succeed": False,
        },
         "$unset": {"error": "", "last_attempt_at": ""}},
        upsert=True,
    )
    logger.info(
        "[portal_invite_placeholder_rebrace_v1] complete — "
        "scanned=%s rebrace=%s skipped_no_legacy=%s failed=%s",
        rows_scanned, rows_rebrace, rows_skipped_no_legacy,
        rows_failed,
    )
    return {
        "ok": True, "skipped": False,
        "rows_scanned": rows_scanned,
        "rows_rebrace": rows_rebrace,
        "rows_skipped_no_legacy": rows_skipped_no_legacy,
        "rows_failed": rows_failed,
    }
