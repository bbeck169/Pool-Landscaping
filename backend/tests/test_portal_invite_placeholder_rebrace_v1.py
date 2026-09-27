"""Feb-2026 · Portal-invite placeholder rebrace migration · tests.

Locks the contracts for
``services.migrations.portal_invite_placeholder_rebrace_v1``:

  1. **Fresh DB** — no ``marketing_templates`` rows scoped to the
     test's synthetic tenant → migration reports zeros, sentinel
     completes cleanly.
  2. **Legacy → canonical rewrite** — a row with all four legacy
     placeholders in the body → migration rewrites each to the
     canonical double-brace token; ``rows_rebrace == 1``.
  3. **Idempotency** — a second run short-circuits via the
     sentinel with ``skipped=True``.  Even after a sentinel clear,
     the migration is a no-op on already-rebrace bodies
     (``rows_skipped_no_legacy`` picks them up).
  4. **Mixed placeholders in same body** — a body containing
     legacy ``{name}`` alongside canonical ``{{COMPANY_NAME}}``
     rewrites only the legacy substring; the double-brace token
     is preserved verbatim.
  5. **User-edit preservation** — a body containing a legacy
     placeholder AND an unrelated brace literal (``{2024}``)
     rewrites only the enumerated placeholder; ``{2024}`` stays
     byte-identical.
  6. **Row scope** — a ``job_completion_sms`` row with a legacy
     ``{name}`` substring is NOT rewritten (migration scopes to
     ``code=portal_invite_email`` only).
  7. **Already-double-braced preservation** — a body already
     written with double-brace ``{{name}}`` is treated as a
     no-op by the rebrace regex's negative lookbehind/lookahead
     guard; content is byte-identical after the migration runs.

Loop / DB hygiene
─────────────────
Reuses the ``_f7_loop_fixture.run_test`` pattern already covering
the sibling ``test_marketing_templates_portal_job.py`` file —
rebinds ``config.db`` + every dependent module to a fresh loop-
scoped Motor handle, restores originals on teardown.  No
``sys.modules.pop`` needed here because the migration doesn't
lazy-import the rebound modules and the fixture already handles
its own snapshot/restore.

Cleanup
───────
All seeded rows carry the tag prefix ``TEST-portal-rebrace-`` in
their ``tenant_id`` so cleanup is a single ``delete_many`` per
collection.  Sentinel is scrubbed at the top of every test that
runs the migration so the tests are order-independent.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict

from tests._f7_loop_fixture import run_test


MIGRATION_KEY = "portal_invite_placeholder_rebrace_v1"
_TENANT_PREFIX = "TEST-portal-rebrace-"


def _mk_tid() -> str:
    return _TENANT_PREFIX + uuid.uuid4().hex[:12]


# ═══════════════════════════════════════════════════════════════════
# Fixture helpers — every test seeds via these to keep row shapes
# consistent with the live seed at
# ``migrations/te_portal_job_templates_seed.py``.
# ═══════════════════════════════════════════════════════════════════
async def _seed_row(
    db,
    tenant_id: str,
    *,
    code: str = "portal_invite_email",
    body: str,
    subject: str = "Your customer portal login",
) -> str:
    row_id = f"{_TENANT_PREFIX}row-{uuid.uuid4().hex[:8]}"
    await db.marketing_templates.insert_one({
        "id": row_id,
        "tenant_id": tenant_id,
        "code": code,
        "name": ("Portal Invite — Email" if code == "portal_invite_email"
                  else "Job Completion — SMS"),
        "channel": "email" if code == "portal_invite_email" else "sms",
        "category": ("portal_invite" if code == "portal_invite_email"
                       else "job_completion"),
        "kind": "transactional",
        "subject": subject if code == "portal_invite_email" else None,
        "body": body,
        "variables": [],
        "is_system": True,
        "is_editable": True,
        "is_active": True,
        "created_at": "2026-02-01T00:00:00+00:00",
        "updated_at": "2026-02-01T00:00:00+00:00",
    })
    return row_id


async def _cleanup(db, tenant_id: str) -> None:
    await db.marketing_templates.delete_many({"tenant_id": tenant_id})


async def _reset_sentinel(db) -> None:
    await db.migration_status.delete_one({"key": MIGRATION_KEY})


async def _run_migration_scoped(db, tenant_id: str) -> Dict[str, Any]:
    """Run the migration scoped to the test's synthetic tenant so
    co-existing rows in the shared DB don't contaminate our
    counters."""
    from services.migrations.portal_invite_placeholder_rebrace_v1 import (
        run,
    )
    return await run(
        db,
        row_filter={"tenant_id": tenant_id},
    )


# ═══════════════════════════════════════════════════════════════════
# 1) Fresh DB — no rows scoped to our tenant → all zeros
# ═══════════════════════════════════════════════════════════════════
def test_fresh_db_no_rows_scoped_to_tenant():
    async def _go(db):
        tid = _mk_tid()
        await _cleanup(db, tid)
        await _reset_sentinel(db)
        try:
            res = await _run_migration_scoped(db, tid)
            assert res["ok"] is True
            assert res["skipped"] is False
            assert res["rows_scanned"] == 0
            assert res["rows_rebrace"] == 0
            assert res["rows_skipped_no_legacy"] == 0
            assert res["rows_failed"] == 0

            sen = await db.migration_status.find_one(
                {"key": MIGRATION_KEY}, {"_id": 0},
            )
            assert sen is not None
            assert sen.get("completed_at")
            assert sen.get("must_succeed") is False
        finally:
            await _cleanup(db, tid)
            await _reset_sentinel(db)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 2) Legacy → canonical rewrite — all four placeholders converted
# ═══════════════════════════════════════════════════════════════════
def test_legacy_placeholders_get_rewritten_to_canonical():
    async def _go(db):
        tid = _mk_tid()
        await _cleanup(db, tid)
        await _reset_sentinel(db)
        try:
            row_id = await _seed_row(db, tid, body=(
                "<p>Hi {name},</p>"
                "<p>Email: {to} — password: {temp_password}</p>"
                "<p><a href='{login_url}'>Sign in</a></p>"
            ))
            res = await _run_migration_scoped(db, tid)
            assert res["ok"] is True
            assert res["rows_scanned"] == 1
            assert res["rows_rebrace"] == 1
            assert res["rows_skipped_no_legacy"] == 0

            row = await db.marketing_templates.find_one(
                {"id": row_id}, {"_id": 0, "body": 1},
            )
            body = row["body"]
            # Canonical present.
            assert "{{NAME}}" in body
            assert "{{TO}}" in body
            assert "{{TEMP_PASSWORD}}" in body
            assert "{{LOGIN_URL}}" in body
            # Legacy scrubbed.
            for legacy in ("{name}", "{to}", "{temp_password}",
                            "{login_url}"):
                assert legacy not in body, (
                    f"legacy placeholder {legacy!r} survived rewrite"
                )
        finally:
            await _cleanup(db, tid)
            await _reset_sentinel(db)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 3) Idempotency — 2nd run short-circuits + no-op on already-rebrace
# ═══════════════════════════════════════════════════════════════════
def test_migration_is_idempotent_via_sentinel_and_per_row():
    async def _go(db):
        tid = _mk_tid()
        await _cleanup(db, tid)
        await _reset_sentinel(db)
        try:
            row_id = await _seed_row(db, tid, body=(
                "<p>Hi {name} — login {login_url}</p>"
            ))
            first = await _run_migration_scoped(db, tid)
            assert first["ok"] is True
            assert first["skipped"] is False
            assert first["rows_rebrace"] == 1

            # Second run — sentinel short-circuit.
            second = await _run_migration_scoped(db, tid)
            assert second == {
                "ok": True, "skipped": True, "reason": "already_ran",
            }

            # Clear sentinel + re-run — now the body is already
            # rebrace, so the per-row idempotency picks it up as
            # ``rows_skipped_no_legacy`` (NOT ``rows_rebrace`` again).
            await _reset_sentinel(db)
            third = await _run_migration_scoped(db, tid)
            assert third["ok"] is True
            assert third["skipped"] is False
            assert third["rows_scanned"] == 1
            assert third["rows_rebrace"] == 0, third
            assert third["rows_skipped_no_legacy"] == 1, third

            # Body byte-identical after the sentinel-clear replay.
            row = await db.marketing_templates.find_one(
                {"id": row_id}, {"_id": 0, "body": 1},
            )
            assert row["body"] == (
                "<p>Hi {{NAME}} — login {{LOGIN_URL}}</p>"
            )
        finally:
            await _cleanup(db, tid)
            await _reset_sentinel(db)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 4) Mixed placeholders — legacy rewrites, canonical preserved
# ═══════════════════════════════════════════════════════════════════
def test_mixed_placeholders_legacy_rewrites_canonical_preserved():
    async def _go(db):
        tid = _mk_tid()
        await _cleanup(db, tid)
        await _reset_sentinel(db)
        try:
            row_id = await _seed_row(db, tid, body=(
                # Legacy single-brace ``{name}`` PLUS canonical
                # double-brace ``{{COMPANY_NAME}}`` in the same body.
                "<p>Hi {name} — from {{COMPANY_NAME}}</p>"
            ))
            res = await _run_migration_scoped(db, tid)
            assert res["rows_rebrace"] == 1

            row = await db.marketing_templates.find_one(
                {"id": row_id}, {"_id": 0, "body": 1},
            )
            body = row["body"]
            # Legacy rewrote.
            assert "{{NAME}}" in body
            assert "{name}" not in body
            # Canonical preserved verbatim.
            assert "{{COMPANY_NAME}}" in body
            # No extra brace layering damage.
            assert "{{{{" not in body
            assert "}}}}" not in body
        finally:
            await _cleanup(db, tid)
            await _reset_sentinel(db)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 5) User-edit preservation — unrelated brace literal untouched
# ═══════════════════════════════════════════════════════════════════
def test_unrelated_brace_literals_preserved_byte_identical():
    async def _go(db):
        tid = _mk_tid()
        await _cleanup(db, tid)
        await _reset_sentinel(db)
        try:
            row_id = await _seed_row(db, tid, body=(
                "<p>Copyright {2024}. Hi {name}!</p>"
                "<p>Support ticket #{ID_UNRELATED}</p>"
            ))
            res = await _run_migration_scoped(db, tid)
            assert res["rows_rebrace"] == 1

            row = await db.marketing_templates.find_one(
                {"id": row_id}, {"_id": 0, "body": 1},
            )
            body = row["body"]
            # Only ``{name}`` should have been touched.
            assert "{{NAME}}" in body
            assert "{name}" not in body
            # Unrelated brace literals stay byte-identical.
            assert "{2024}" in body, (
                f"unrelated {{2024}} literal was mutated: {body!r}"
            )
            assert "{ID_UNRELATED}" in body, (
                f"unrelated {{ID_UNRELATED}} literal was mutated:"
                f" {body!r}"
            )
        finally:
            await _cleanup(db, tid)
            await _reset_sentinel(db)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 6) Row scope — job_completion_sms rows are NOT touched
# ═══════════════════════════════════════════════════════════════════
def test_row_scope_only_portal_invite_email_rows_rebrace():
    async def _go(db):
        tid = _mk_tid()
        await _cleanup(db, tid)
        await _reset_sentinel(db)
        try:
            # Portal-invite row — SHOULD rebrace.
            portal_id = await _seed_row(db, tid, body=(
                "<p>Hi {name}!</p>"
            ))
            # SMS row with a legacy-shape placeholder — MUST NOT be
            # touched.
            sms_id = await _seed_row(
                db, tid, code="job_completion_sms",
                body=("Hi {name}, your service is complete!"),
            )

            res = await _run_migration_scoped(db, tid)
            # Only the portal-invite row is scanned + rewritten.
            assert res["rows_scanned"] == 1, res
            assert res["rows_rebrace"] == 1, res

            portal = await db.marketing_templates.find_one(
                {"id": portal_id}, {"_id": 0, "body": 1},
            )
            sms = await db.marketing_templates.find_one(
                {"id": sms_id}, {"_id": 0, "body": 1},
            )
            # Portal rewrote.
            assert "{{NAME}}" in portal["body"]
            # SMS byte-identical.
            assert sms["body"] == (
                "Hi {name}, your service is complete!"
            )
        finally:
            await _cleanup(db, tid)
            await _reset_sentinel(db)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 7) Already-double-braced — no rewrite, byte-identical body
# ═══════════════════════════════════════════════════════════════════
def test_already_double_braced_preserved_no_rewrite():
    """Guards the negative-lookbehind/lookahead in the rebrace regex.

    If the regex accidentally matched already-double-braced tokens,
    ``{{name}}`` would become ``{{{{NAME}}}}`` — a runtime disaster
    at the next render. This test locks the guard.
    """
    async def _go(db):
        tid = _mk_tid()
        await _cleanup(db, tid)
        await _reset_sentinel(db)
        try:
            row_id = await _seed_row(db, tid, body=(
                "<p>Hi {{name}} — from {{COMPANY_NAME}}</p>"
            ))
            res = await _run_migration_scoped(db, tid)
            assert res["rows_scanned"] == 1
            assert res["rows_rebrace"] == 0
            assert res["rows_skipped_no_legacy"] == 1

            row = await db.marketing_templates.find_one(
                {"id": row_id}, {"_id": 0, "body": 1},
            )
            # Body byte-identical to the seed.
            assert row["body"] == (
                "<p>Hi {{name}} — from {{COMPANY_NAME}}</p>"
            )
            # Sanity — no brace-layering catastrophe.
            assert "{{{{" not in row["body"]
        finally:
            await _cleanup(db, tid)
            await _reset_sentinel(db)

    run_test(_go)
