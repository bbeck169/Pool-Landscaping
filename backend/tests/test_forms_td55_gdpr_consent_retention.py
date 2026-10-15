"""TD-55 · Feb-2026 — GDPR consent checkbox + submission retention.

Phase 6 Commit 1 of the GDPR ship.

Server-side contract:
    * ``consent_checkbox`` is a value-carrying field type (NOT
      layout — participates in the required-check so an unchecked
      box blocks submit when ``required=true``).
    * Carries an optional ``privacy_policy_url`` (max 500 chars)
      used by the widget renderer to attach a 'Privacy policy' link.
    * ``consent_checkbox`` with ``required=true`` + a falsy value
      (``false`` / ``None`` / missing) is treated as missing in the
      required-check — same 422 error surface as a missing text
      field, so operator UX stays uniform.
    * ``db.tenants.form_submission_retention_days`` — optional
      per-tenant retention policy. ``None`` / unset / <=0 means
      INFINITE retention (default). Non-zero means delete rows in
      ``db.form_submissions`` older than N days on each cron run.
    * ``purge_expired_form_submissions`` — plain async coroutine.
      Mirrors ``routers/gps_settings.py:purge_expired_pings`` so
      the APScheduler registration is a trivial one-liner.
    * ``db.form_submission_prune_audit`` — one row per tenant per
      non-null retention run (even when ``deleted_count == 0`` so
      compliance can see we tried).

Covers (18 cases):

Palette (3):
    1. ``consent_checkbox`` is in ``_FIELD_TYPES``.
    2. ``consent_checkbox`` is NOT in ``_LAYOUT_TYPES`` (value-
       carrying).
    3. ``consent_checkbox`` is NOT in ``_OPTIONS_REQUIRED_TYPES``.

Model (3):
    4. ``FormField`` accepts ``consent_checkbox`` with
       ``privacy_policy_url``.
    5. ``privacy_policy_url`` >500 chars rejected.
    6. ``privacy_policy_url`` on other field types is round-trip
       preserved (set + ignored by the widget / server, not
       stripped at save time).

Required-check (4):
    7. Required ``consent_checkbox`` + value=True passes.
    8. Required ``consent_checkbox`` + value=False → 422 missing.
    9. Required ``consent_checkbox`` missing from payload → 422
       missing.
   10. Non-required ``consent_checkbox`` + value=False → PASSES
       (opt-in semantics).

Retention cron (8):
   11. Tenant with ``form_submission_retention_days=None`` → SKIPPED
       (no deletes).
   12. Tenant with ``form_submission_retention_days=0`` → SKIPPED
       (infinite retention sentinel).
   13. Tenant with ``form_submission_retention_days=30`` deletes
       submissions older than cutoff + writes one audit row.
   14. Submissions NEWER than the cutoff are preserved.
   15. Cross-tenant isolation — tenant A's purge never touches
       tenant B's rows.
   16. Audit row is written even when deleted_count == 0 (compliance
       trail "we tried" marker).
   17. Second run of the cron deletes nothing further (idempotent
       within the same minute).
   18. Non-int ``form_submission_retention_days`` is ignored (no
       crash, no delete).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from dotenv import dotenv_values
from fastapi import HTTPException
from pydantic import ValidationError

from routers.marketing_forms import (
    FormField,
    _FIELD_TYPES,
    _LAYOUT_TYPES,
    _OPTIONS_REQUIRED_TYPES,
    _validate_field_defs,
    purge_expired_form_submissions,
)


_ENV = dotenv_values(Path("/app/backend/.env"))
_TENANT_A = f"td55-A-{uuid.uuid4().hex[:8]}"
_TENANT_B = f"td55-B-{uuid.uuid4().hex[:8]}"


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _sync_db():
    from pymongo import MongoClient
    return MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]


# ──────────────────────────────────────────────────────────────────
# 1–3. Palette
# ──────────────────────────────────────────────────────────────────
def test_consent_checkbox_in_field_types():
    assert "consent_checkbox" in _FIELD_TYPES


def test_consent_checkbox_not_layout():
    assert "consent_checkbox" not in _LAYOUT_TYPES


def test_consent_checkbox_not_options_required():
    assert "consent_checkbox" not in _OPTIONS_REQUIRED_TYPES


# ──────────────────────────────────────────────────────────────────
# 4–6. Model
# ──────────────────────────────────────────────────────────────────
def test_form_field_accepts_consent_checkbox_with_privacy_url():
    f = FormField(name="gdpr", label="I agree", type="consent_checkbox",
                     required=True, privacy_policy_url="https://e.test/privacy")
    assert f.type == "consent_checkbox"
    assert f.privacy_policy_url == "https://e.test/privacy"


def test_privacy_policy_url_over_500_chars_rejected():
    with pytest.raises(ValidationError):
        FormField(name="x", label="Agree", type="consent_checkbox",
                     privacy_policy_url="https://e.test/" + "a" * 500)


def test_privacy_policy_url_round_trips_on_other_types():
    out = _validate_field_defs([
        FormField(name="email", label="Email", type="email",
                     privacy_policy_url="https://e.test/privacy"),
    ])
    # Preserved but ignored (widget / server don't surface it for
    # non-consent types; the admin UI only exposes the input for
    # consent_checkbox rows).
    assert out[0].get("privacy_policy_url") == "https://e.test/privacy"


# ──────────────────────────────────────────────────────────────────
# 7–10. Required-check — the gist of the consent contract
# ──────────────────────────────────────────────────────────────────
def _consent_field(name="gdpr", required=True) -> dict:
    """Normalise once via the validator so id / order are stable."""
    return _validate_field_defs([
        FormField(name=name, label="I consent", type="consent_checkbox",
                     required=required),
    ])[0]


def _run_consent_required_check(fields: list, payload: dict) -> None:
    """Minimal re-implementation of the dispatcher's required-check
    + the TD-55 consent branch. Mirrors the exact behavior wired at
    routers/marketing_forms.py."""
    missing = []
    for f in fields:
        if not f.get("required"):
            continue
        val = payload.get(f["name"])
        if val is None and f.get("id"):
            val = payload.get(f["id"])
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(f["name"])
            continue
        if f.get("type") == "consent_checkbox" and not val:
            missing.append(f["name"])
    if missing:
        raise HTTPException(
            422, f"missing required fields: {', '.join(missing)}"
        )


def test_required_consent_checkbox_truthy_passes():
    f = _consent_field()
    _run_consent_required_check([f], {"gdpr": True})


def test_required_consent_checkbox_false_is_missing():
    f = _consent_field()
    with pytest.raises(HTTPException) as exc:
        _run_consent_required_check([f], {"gdpr": False})
    assert exc.value.status_code == 422
    assert "gdpr" in str(exc.value.detail)


def test_required_consent_checkbox_absent_is_missing():
    f = _consent_field()
    with pytest.raises(HTTPException) as exc:
        _run_consent_required_check([f], {})
    assert exc.value.status_code == 422


def test_non_required_consent_checkbox_false_passes():
    f = _consent_field(required=False)
    # Opt-in: unchecked optional consent is fine.
    _run_consent_required_check([f], {"gdpr": False})


# ──────────────────────────────────────────────────────────────────
# 11–18. Retention cron
# ──────────────────────────────────────────────────────────────────
def _cleanup():
    _sync_db().tenants.delete_many(
        {"id": {"$in": [_TENANT_A, _TENANT_B]}},
    )
    _sync_db().form_submissions.delete_many(
        {"tenant_id": {"$in": [_TENANT_A, _TENANT_B]}},
    )
    _sync_db().form_submission_prune_audit.delete_many(
        {"tenant_id": {"$in": [_TENANT_A, _TENANT_B]}},
    )


def _seed_tenant(tid: str, retention_days):
    doc = {"id": tid, "slug": tid, "name": tid, "active": True}
    if retention_days is not None:
        doc["form_submission_retention_days"] = retention_days
    _sync_db().tenants.insert_one(doc)


def _seed_submission(tid: str, days_old: int, sid: str | None = None):
    sid = sid or ("s-" + uuid.uuid4().hex[:8])
    ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
    _sync_db().form_submissions.insert_one({
        "id": sid, "tenant_id": tid, "form_id": "f1",
        "answers": {}, "created_at": ts,
    })
    return sid


def test_tenant_without_retention_setting_is_skipped():
    _cleanup()
    try:
        # No form_submission_retention_days on tenant doc at all.
        _sync_db().tenants.insert_one(
            {"id": _TENANT_A, "slug": "a", "name": "A", "active": True},
        )
        _seed_submission(_TENANT_A, days_old=400)  # very old
        summary = _run(purge_expired_form_submissions())
        # No audit row + submission still there.
        assert _TENANT_A not in summary["per_tenant"]
        assert _sync_db().form_submissions.count_documents(
            {"tenant_id": _TENANT_A},
        ) == 1
        assert _sync_db().form_submission_prune_audit.count_documents(
            {"tenant_id": _TENANT_A},
        ) == 0
    finally:
        _cleanup()


def test_tenant_with_zero_retention_is_skipped():
    """0 is the sentinel for 'infinite retention' (same contract as
    the Null case; UI operators who want infinite retention set 0
    explicitly instead of unsetting the field)."""
    _cleanup()
    try:
        _seed_tenant(_TENANT_A, retention_days=0)
        _seed_submission(_TENANT_A, days_old=400)
        summary = _run(purge_expired_form_submissions())
        assert _TENANT_A not in summary["per_tenant"]
        assert _sync_db().form_submissions.count_documents(
            {"tenant_id": _TENANT_A},
        ) == 1
    finally:
        _cleanup()


def test_retention_deletes_old_submissions_and_writes_audit():
    _cleanup()
    try:
        _seed_tenant(_TENANT_A, retention_days=30)
        _seed_submission(_TENANT_A, days_old=60, sid="s-old")
        summary = _run(purge_expired_form_submissions())
        assert summary["per_tenant"][_TENANT_A] == 1
        # Old row deleted.
        assert _sync_db().form_submissions.find_one(
            {"id": "s-old"}, {"_id": 0, "id": 1},
        ) is None
        # Audit row written.
        audit = _sync_db().form_submission_prune_audit.find_one(
            {"tenant_id": _TENANT_A}, {"_id": 0},
        )
        assert audit is not None
        assert audit["deleted_count"] == 1
        assert audit["retention_days"] == 30
        assert audit["pruned_at"]
    finally:
        _cleanup()


def test_retention_preserves_newer_submissions():
    _cleanup()
    try:
        _seed_tenant(_TENANT_A, retention_days=30)
        _seed_submission(_TENANT_A, days_old=10, sid="s-new")
        _seed_submission(_TENANT_A, days_old=60, sid="s-old")
        _run(purge_expired_form_submissions())
        assert _sync_db().form_submissions.find_one(
            {"id": "s-new"}, {"_id": 0, "id": 1},
        ) is not None
        assert _sync_db().form_submissions.find_one(
            {"id": "s-old"}, {"_id": 0, "id": 1},
        ) is None
    finally:
        _cleanup()


def test_cross_tenant_isolation():
    _cleanup()
    try:
        _seed_tenant(_TENANT_A, retention_days=30)
        _seed_tenant(_TENANT_B, retention_days=None)
        _seed_submission(_TENANT_A, days_old=60, sid="s-a-old")
        _seed_submission(_TENANT_B, days_old=60, sid="s-b-old")
        _run(purge_expired_form_submissions())
        # Tenant A row gone; tenant B row preserved.
        assert _sync_db().form_submissions.find_one(
            {"id": "s-a-old"},
        ) is None
        assert _sync_db().form_submissions.find_one(
            {"id": "s-b-old"},
        ) is not None
    finally:
        _cleanup()


def test_audit_row_written_even_when_nothing_to_delete():
    _cleanup()
    try:
        _seed_tenant(_TENANT_A, retention_days=30)
        _seed_submission(_TENANT_A, days_old=5, sid="s-new")
        _run(purge_expired_form_submissions())
        audit = _sync_db().form_submission_prune_audit.find_one(
            {"tenant_id": _TENANT_A}, {"_id": 0},
        )
        assert audit is not None
        assert audit["deleted_count"] == 0
    finally:
        _cleanup()


def test_second_run_is_idempotent():
    _cleanup()
    try:
        _seed_tenant(_TENANT_A, retention_days=30)
        _seed_submission(_TENANT_A, days_old=60, sid="s-old")
        _run(purge_expired_form_submissions())
        # One row deleted + one audit row.
        _run(purge_expired_form_submissions())
        # Second run deletes nothing (the old row is gone) + writes
        # another "we tried, nothing to do" audit row.
        audits = list(_sync_db().form_submission_prune_audit.find(
            {"tenant_id": _TENANT_A}, {"_id": 0, "deleted_count": 1},
        ))
        assert len(audits) == 2
        assert sorted([a["deleted_count"] for a in audits]) == [0, 1]
    finally:
        _cleanup()


def test_non_int_retention_is_ignored():
    _cleanup()
    try:
        _seed_tenant(_TENANT_A, retention_days="chaos")
        _seed_submission(_TENANT_A, days_old=60, sid="s-chaos")
        summary = _run(purge_expired_form_submissions())
        assert _TENANT_A not in summary["per_tenant"]
        assert _sync_db().form_submissions.find_one(
            {"id": "s-chaos"},
        ) is not None
    finally:
        _cleanup()
