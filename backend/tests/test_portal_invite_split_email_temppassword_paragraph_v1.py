"""M-TAG-FIX FOLLOWUP · Feb-2026 · Split-Email+TempPassword migration · tests.

Locks the contracts for
``services.migrations.portal_invite_split_email_temppassword_paragraph_v1``
AND the companion hardened paragraph-removal regex in
``routers/portal_admin.py::_try_send_reset_email``:

  1. **Dry-run reports but does not write** — a tenant with the
     legacy single-paragraph shape is REPORTED as a match but the
     DB row is NOT touched + sentinel NOT stamped.
  2. **Fix run migrates + stamps sentinel** — same tenant after
     ``dry_run=False`` has the split canonical shape in the DB.
  3. **Idempotency (fix after fix)** — second fix run short-
     circuits via the sentinel.  Clearing the sentinel + replaying
     is a no-op (already-split rows classify as
     ``already_split``).
  4. **Admin-edited template is skipped, not mangled** — a
     hand-edited template shape (e.g. Spanish labels) is classified
     ``shape_mismatch`` and left byte-identical.
  5. **Empty-TEMP_PASSWORD send preserves the Email line
     POST-MIGRATION** — the stored template renders the Email
     paragraph intact when ``temp_password=""``.
  6. **Populated-TEMP_PASSWORD send unchanged POST-MIGRATION** —
     both Email + Temporary-password paragraphs render verbatim.
  7. **Hardened regex: mixed-tag paragraph survives the strip** —
     an admin who merged ``{{TEMP_PASSWORD}}`` with ``{{TO}}`` into
     a single paragraph DOES NOT lose their Email line even when
     the migration SKIPS their template.  Defense in depth.

Loop / DB hygiene
─────────────────
Reuses ``_f7_loop_fixture.run_test`` to rebind ``config.db`` + its
dependent modules to a fresh loop-scoped Motor handle.  Every test
seeds under a unique ``TEST-split-paragraph-`` tenant prefix and
cleans up both the ``marketing_templates`` rows AND the sentinel
on teardown so the suite is order-independent.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from tests._f7_loop_fixture import run_test


MIGRATION_KEY = (
    "portal_invite_split_email_temppassword_paragraph_v1"
)
_TENANT_PREFIX = "TEST-split-paragraph-"


# ═══════════════════════════════════════════════════════════════════
# Legacy / canonical body fixtures (match the shapes used by the
# seed in ``migrations/te_portal_job_templates_seed.py``).
# ═══════════════════════════════════════════════════════════════════
_LEGACY_SINGLE_P_BODY = (
    "<p>Hi {{NAME}},</p>"
    "<p>Your portal login is ready.</p>"
    "<p><strong>Email:</strong> {{TO}}<br>"
    "<strong>Temporary password:</strong> "
    "<code>{{TEMP_PASSWORD}}</code></p>"
    "<p><a href='{{LOGIN_URL}}'>Sign in here</a> and change "
    "your password from Profile.</p>"
)

_CANONICAL_SPLIT_BODY = (
    "<p>Hi {{NAME}},</p>"
    "<p>Your portal login is ready.</p>"
    "<p><strong>Email:</strong> {{TO}}</p>"
    "<p><strong>Temporary password:</strong> "
    "<code>{{TEMP_PASSWORD}}</code></p>"
    "<p><a href='{{LOGIN_URL}}'>Sign in here</a> and change "
    "your password from Profile.</p>"
)


def _mk_tid() -> str:
    return _TENANT_PREFIX + uuid.uuid4().hex[:12]


async def _seed_row(
    db,
    tenant_id: str,
    *,
    body: str,
    code: str = "portal_invite_email",
) -> str:
    row_id = f"{_TENANT_PREFIX}row-{uuid.uuid4().hex[:8]}"
    await db.marketing_templates.insert_one({
        "id": row_id,
        "tenant_id": tenant_id,
        "code": code,
        "name": "Portal Invite — Email",
        "channel": "email",
        "category": "portal_invite",
        "kind": "transactional",
        "subject": "Your customer portal login",
        "body": body,
        "variables": ["name", "to", "temp_password", "login_url"],
        "is_system": True,
        "is_editable": True,
        "is_active": True,
        "created_at": "2026-02-01T00:00:00+00:00",
        "updated_at": "2026-02-01T00:00:00+00:00",
    })
    return row_id


async def _cleanup(db, tenant_id: str) -> None:
    await db.marketing_templates.delete_many({"tenant_id": tenant_id})
    await db.tenants.delete_many({"id": tenant_id})


async def _reset_sentinel(db) -> None:
    await db.migration_status.delete_one({"key": MIGRATION_KEY})


async def _seed_synthetic_tenant(db, tenant_id: str) -> None:
    """Branding-gate bypass — the send path checks for a non-empty
    company_name/phone in ``tenants.settings.business_card`` before
    firing Resend.  Insert the minimum shape expected."""
    await db.tenants.insert_one({
        "id": tenant_id,
        "slug": f"te-split-{tenant_id}",
        "name": "TE Split-Paragraph Co.",
        "settings": {
            "business_card": {
                "company_name": "TE Split-Paragraph Co.",
                "phone": "555-000-0042",
            },
        },
    })


async def _run_migration_scoped(
    db, tenant_id: str, *, dry_run: bool = True,
) -> Dict[str, Any]:
    from services.migrations.portal_invite_split_email_temppassword_paragraph_v1 import (  # noqa: E501
        run,
    )
    return await run(
        db,
        dry_run=dry_run,
        row_filter={"tenant_id": tenant_id},
    )


# ═══════════════════════════════════════════════════════════════════
# 1) Dry-run reports but does not write
# ═══════════════════════════════════════════════════════════════════
def test_dry_run_reports_match_without_writing_or_stamping_sentinel():
    async def _go(db):
        tid = _mk_tid()
        await _cleanup(db, tid)
        await _reset_sentinel(db)
        try:
            row_id = await _seed_row(db, tid, body=_LEGACY_SINGLE_P_BODY)
            res = await _run_migration_scoped(db, tid, dry_run=True)

            assert res["ok"] is True
            assert res["dry_run"] is True
            assert res["skipped"] is False
            assert res["tenants_scanned"] == 1
            assert res["templates_matched"] == 1
            # Dry-run NEVER writes.
            assert res["templates_migrated"] == 0
            assert res["templates_failed"] == 0

            # Body unchanged in the DB.
            row = await db.marketing_templates.find_one(
                {"id": row_id}, {"_id": 0, "body": 1},
            )
            assert row["body"] == _LEGACY_SINGLE_P_BODY

            # Sentinel NOT stamped by a dry-run.
            sen = await db.migration_status.find_one(
                {"key": MIGRATION_KEY}, {"_id": 0},
            )
            assert sen is None
        finally:
            await _cleanup(db, tid)
            await _reset_sentinel(db)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 2) Fix run migrates + stamps sentinel
# ═══════════════════════════════════════════════════════════════════
def test_fix_run_migrates_legacy_shape_and_stamps_sentinel():
    async def _go(db):
        tid = _mk_tid()
        await _cleanup(db, tid)
        await _reset_sentinel(db)
        try:
            row_id = await _seed_row(db, tid, body=_LEGACY_SINGLE_P_BODY)
            res = await _run_migration_scoped(db, tid, dry_run=False)

            assert res["ok"] is True
            assert res["dry_run"] is False
            assert res["templates_matched"] == 1
            assert res["templates_migrated"] == 1

            row = await db.marketing_templates.find_one(
                {"id": row_id}, {"_id": 0, "body": 1},
            )
            # Email on its own <p>, TempPassword on its own <p>.
            assert (
                "<p><strong>Email:</strong> {{TO}}</p>" in row["body"]
            )
            assert (
                "<p><strong>Temporary password:</strong> "
                "<code>{{TEMP_PASSWORD}}</code></p>" in row["body"]
            )
            # Legacy single-paragraph shape is gone.
            assert "{{TO}}<br>" not in row["body"]

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
# 3) Idempotency — sentinel short-circuits, per-row no-op
# ═══════════════════════════════════════════════════════════════════
def test_fix_run_is_idempotent_via_sentinel_and_per_row_shape_check():
    async def _go(db):
        tid = _mk_tid()
        await _cleanup(db, tid)
        await _reset_sentinel(db)
        try:
            await _seed_row(db, tid, body=_LEGACY_SINGLE_P_BODY)

            first = await _run_migration_scoped(db, tid, dry_run=False)
            assert first["templates_migrated"] == 1

            # 2nd fix run — sentinel short-circuits.
            second = await _run_migration_scoped(db, tid, dry_run=False)
            assert second["skipped"] is True
            assert second["reason"] == "already_ran"

            # Clear sentinel + replay — now the per-row check
            # protects us (bodies are already split).
            await _reset_sentinel(db)
            third = await _run_migration_scoped(db, tid, dry_run=False)
            assert third["templates_matched"] == 0
            assert third["templates_migrated"] == 0
            assert third["templates_skipped"] == 1
            assert third["skip_reasons"]["already_split"] == 1
        finally:
            await _cleanup(db, tid)
            await _reset_sentinel(db)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 4) Admin-edited template is skipped, not mangled
# ═══════════════════════════════════════════════════════════════════
def test_admin_edited_template_is_skipped_shape_mismatch():
    """Admins who re-worded the labels (e.g. localized) have a shape
    the predicate deliberately won't match.  The migration must
    SKIP such rows — leaving the body byte-identical — and report
    them under ``skip_reasons.shape_mismatch`` so operators can
    audit the long tail without us destroying anyone's customisation.
    """
    async def _go(db):
        tid = _mk_tid()
        await _cleanup(db, tid)
        await _reset_sentinel(db)
        try:
            custom_body = (
                "<p>Hola {{NAME}},</p>"
                "<p><strong>Correo:</strong> {{TO}}<br>"
                "<strong>Contraseña temporal:</strong> "
                "<code>{{TEMP_PASSWORD}}</code></p>"
            )
            row_id = await _seed_row(db, tid, body=custom_body)

            res = await _run_migration_scoped(db, tid, dry_run=False)
            assert res["templates_matched"] == 0
            assert res["templates_migrated"] == 0
            assert res["templates_skipped"] == 1
            assert res["skip_reasons"]["shape_mismatch"] == 1

            # Byte-identical preservation.
            row = await db.marketing_templates.find_one(
                {"id": row_id}, {"_id": 0, "body": 1},
            )
            assert row["body"] == custom_body
        finally:
            await _cleanup(db, tid)
            await _reset_sentinel(db)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 5) Empty-TEMP_PASSWORD send preserves Email line POST-MIGRATION
# ═══════════════════════════════════════════════════════════════════
def test_empty_temp_password_send_preserves_email_line_after_migration(
    monkeypatch,
):
    """Full end-to-end proof: legacy template → migration → Resend
    send with ``temp_password=""`` → captured HTML preserves the
    Email line AND omits the Temporary-password paragraph."""
    import routers.portal_admin as _pa
    import config as _cfg

    async def _go(db):
        tid = _mk_tid()
        await _cleanup(db, tid)
        await _reset_sentinel(db)
        try:
            await _seed_synthetic_tenant(db, tid)
            await _seed_row(db, tid, body=_LEGACY_SINGLE_P_BODY)

            # Apply the migration.
            res = await _run_migration_scoped(db, tid, dry_run=False)
            assert res["templates_migrated"] == 1

            # Mock Resend.
            monkeypatch.setattr(_cfg, "RESEND_API_KEY", "test-key-x",
                                raising=False)
            monkeypatch.setattr(_cfg, "EMAIL_FROM",
                                "test@example.com", raising=False)
            captured: Dict[str, Any] = {}

            class _FakeEmails:
                @staticmethod
                def send(payload):
                    captured.update(payload)
                    return {"id": "resend-fake-id-post-migrate"}

            class _FakeResendModule:
                api_key: Optional[str] = None
                Emails = _FakeEmails

            monkeypatch.setitem(__import__("sys").modules, "resend",
                                _FakeResendModule)

            email_id = await _pa._try_send_reset_email(
                "jane@example.com", "Jane", "",       # <- EMPTY
                "https://x/login", tenant_id=tid,
            )
            assert email_id == "resend-fake-id-post-migrate"
            html = captured.get("html", "")

            # Email line survives post-migration.
            assert "jane@example.com" in html, (
                "Email line was lost — migration or paragraph-"
                "strip regressed."
            )
            # Temporary-password paragraph is cleanly stripped.
            assert "Temporary password" not in html, (
                "Temporary-password label leaked for empty password."
            )
            # No raw merge tags.
            assert "{{" not in html
            assert "}}" not in html
            assert "%7B%7B" not in html
        finally:
            await _cleanup(db, tid)
            await _reset_sentinel(db)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 6) Populated-TEMP_PASSWORD send unchanged POST-MIGRATION
# ═══════════════════════════════════════════════════════════════════
def test_populated_temp_password_send_renders_both_lines_after_migration(
    monkeypatch,
):
    import routers.portal_admin as _pa
    import config as _cfg

    async def _go(db):
        tid = _mk_tid()
        await _cleanup(db, tid)
        await _reset_sentinel(db)
        try:
            await _seed_synthetic_tenant(db, tid)
            await _seed_row(db, tid, body=_LEGACY_SINGLE_P_BODY)
            await _run_migration_scoped(db, tid, dry_run=False)

            monkeypatch.setattr(_cfg, "RESEND_API_KEY", "test-key-x",
                                raising=False)
            monkeypatch.setattr(_cfg, "EMAIL_FROM",
                                "test@example.com", raising=False)
            captured: Dict[str, Any] = {}

            class _FakeEmails:
                @staticmethod
                def send(payload):
                    captured.update(payload)
                    return {"id": "resend-fake-id-pop"}

            class _FakeResendModule:
                api_key: Optional[str] = None
                Emails = _FakeEmails

            monkeypatch.setitem(__import__("sys").modules, "resend",
                                _FakeResendModule)

            await _pa._try_send_reset_email(
                "sam@example.com", "Sam", "Tempp1234",
                "https://x/login", tenant_id=tid,
            )
            html = captured.get("html", "")

            # Both lines render.
            assert "sam@example.com" in html
            assert "Tempp1234" in html
            assert "Temporary password" in html
            # No raw braces leak.
            assert "{{" not in html
            assert "}}" not in html
        finally:
            await _cleanup(db, tid)
            await _reset_sentinel(db)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 7) HARDENED REGEX — mixed-tag paragraph survives the strip
# ═══════════════════════════════════════════════════════════════════
def test_mixed_tag_paragraph_is_NOT_stripped_on_empty_temp_password(
    monkeypatch,
):
    """Defense in depth.  Even if the migration SKIPS a hand-edited
    template that still has ``{{TO}}`` and ``{{TEMP_PASSWORD}}`` in
    the same paragraph (``shape_mismatch``), the hardened
    paragraph-strip regex must preserve the paragraph so the Email
    line survives — the ``{{TEMP_PASSWORD}}`` placeholder renders to
    empty string via the normal substitution cascade.
    """
    import routers.portal_admin as _pa
    import config as _cfg

    async def _go(db):
        tid = _mk_tid()
        await _cleanup(db, tid)
        try:
            await _seed_synthetic_tenant(db, tid)
            # Admin-edited mixed-tag paragraph: two merge tags in
            # the same <p>.  Migration will SKIP this
            # (shape_mismatch); the paragraph-strip regex MUST also
            # preserve the paragraph so the Email line survives.
            mixed_body = (
                "<p>Hi {{NAME}},</p>"
                "<p>Email {{TO}} password {{TEMP_PASSWORD}} end</p>"
                "<p><a href='{{LOGIN_URL}}'>Sign in</a></p>"
            )
            await _seed_row(db, tid, body=mixed_body)

            monkeypatch.setattr(_cfg, "RESEND_API_KEY", "test-key-x",
                                raising=False)
            monkeypatch.setattr(_cfg, "EMAIL_FROM",
                                "test@example.com", raising=False)
            captured: Dict[str, Any] = {}

            class _FakeEmails:
                @staticmethod
                def send(payload):
                    captured.update(payload)
                    return {"id": "resend-fake-id-mixed"}

            class _FakeResendModule:
                api_key: Optional[str] = None
                Emails = _FakeEmails

            monkeypatch.setitem(__import__("sys").modules, "resend",
                                _FakeResendModule)

            await _pa._try_send_reset_email(
                "mixed@example.com", "Mixed", "",       # <- EMPTY
                "https://x/login", tenant_id=tid,
            )
            html = captured.get("html", "")

            # Email line survives — the hardened regex did NOT strip
            # the mixed-tag paragraph.
            assert "mixed@example.com" in html, (
                "Mixed-tag paragraph was stripped — hardened regex "
                "regressed; Email line was lost."
            )
            # No raw braces leak.
            assert "{{" not in html
            assert "}}" not in html
        finally:
            await _cleanup(db, tid)

    run_test(_go)
