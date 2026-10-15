"""TD-50 · Feb-2026 — System C → Marketing Forms migration script.

Covers (10 cases):

Translator (3):
    1. ``translate_legacy_field`` renames ``key`` → ``name`` + keeps
       label / type / required.
    2. ``translate_legacy_field`` preserves ``options`` list +
       placeholder when present.
    3. ``translate_legacy_form`` builds the Marketing Forms doc shape
       with slug + id preserved + submit_config.creates mapped from
       destination.

Destination mapper (2):
    4. Known destinations (lead/customer/both/booking/service/quote)
       map to the correct Marketing Forms enum value.
    5. Unknown destinations fall back to ``lead``.

Audit (1):
    6. ``audit()`` returns totals + per-tenant breakdown + submission
       count across the shared form_submissions collection.

Migrate — idempotent + preserves FK (4):
    7. First-run migrate inserts one marketing_forms row per legacy
       form, preserving id so form_submissions.form_id stays valid.
    8. Second-run migrate SKIPS already-migrated rows (idempotency).
    9. ``--dry-run`` makes no DB writes.
   10. form_submissions remain in place — migration never touches
       them.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values

# Hoist the backend scripts dir onto sys.path so we can import the
# migration module directly.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from migrate_system_c_forms_to_marketing_forms import (  # noqa: E402
    _map_destination,
    audit,
    migrate,
    translate_legacy_field,
    translate_legacy_form,
)

_ENV = dotenv_values(Path("/app/backend/.env"))
_TENANT = f"td50-tenant-{uuid.uuid4().hex[:8]}"


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
# 1–3. Field + form translators
# ──────────────────────────────────────────────────────────────────
def test_translate_legacy_field_renames_key_to_name():
    out = translate_legacy_field({
        "key": "first_name", "label": "First Name",
        "type": "text", "required": True,
    })
    assert out["name"] == "first_name"
    assert out["label"] == "First Name"
    assert out["type"] == "text"
    assert out["required"] is True
    # Modern shape omits ``key``.
    assert "key" not in out


def test_translate_legacy_field_preserves_options_and_placeholder():
    out = translate_legacy_field({
        "key": "state", "label": "State", "type": "select",
        "options": ["AZ", "NV", "CA"], "placeholder": "Pick one",
    })
    assert out["options"] == ["AZ", "NV", "CA"]
    assert out["placeholder"] == "Pick one"


def test_translate_legacy_form_preserves_id_slug_fields():
    legacy = {
        "id": "frm_legacy_1",
        "tenant_id": _TENANT,
        "slug": "contact-us",
        "name": "Contact Us",
        "destination": "customer",
        "status": "published",
        "fields": [
            {"key": "email", "label": "Email", "type": "email", "required": True},
            {"key": "notes", "label": "Notes", "type": "textarea", "required": False},
        ],
        "created_at": "2025-01-15T12:00:00Z",
        "updated_at": "2025-06-20T12:00:00Z",
    }
    out = translate_legacy_form(legacy)
    assert out["id"] == "frm_legacy_1"
    assert out["tenant_id"] == _TENANT
    assert out["slug"] == "contact-us"
    assert out["name"] == "Contact Us"
    assert out["submit_config"]["creates"] == "customer"
    assert out["active"] is True  # published → active
    assert out["migrated_from_system_c"] is True
    # Field shape translated.
    assert out["fields"][0]["name"] == "email"
    assert "key" not in out["fields"][0]


# ──────────────────────────────────────────────────────────────────
# 4–5. Destination mapper
# ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("legacy,modern", [
    ("lead", "lead"),
    ("customer", "customer"),
    ("both", "both"),
    ("booking", "booking"),
    ("booking_request", "booking"),
    ("service_log", "service_log"),
    ("service", "service_log"),
    ("quote", "quote_request"),
    ("quote_request", "quote_request"),
    ("estimate", "quote_request"),
    ("LEAD", "lead"),  # case-insensitive
])
def test_map_destination_known(legacy, modern):
    assert _map_destination(legacy) == modern


@pytest.mark.parametrize("legacy", ["", None, "chaos", "subscriber"])
def test_map_destination_unknown_falls_back_to_lead(legacy):
    assert _map_destination(legacy) == "lead"


# ──────────────────────────────────────────────────────────────────
# 6. Audit
# ──────────────────────────────────────────────────────────────────
def _cleanup():
    _sync_db().forms.delete_many({"tenant_id": _TENANT})
    _sync_db().marketing_forms.delete_many({"tenant_id": _TENANT})
    _sync_db().form_submissions.delete_many({"tenant_id": _TENANT})


def test_audit_counts_forms_and_submissions_per_tenant():
    _cleanup()
    try:
        _sync_db().forms.insert_many([
            {"id": "f-a", "tenant_id": _TENANT, "slug": "a", "name": "A",
             "fields": [], "status": "draft"},
            {"id": "f-b", "tenant_id": _TENANT, "slug": "b", "name": "B",
             "fields": [], "status": "published"},
        ])
        _sync_db().form_submissions.insert_many([
            {"id": "s-1", "tenant_id": _TENANT, "form_id": "f-a", "data": {}},
            {"id": "s-2", "tenant_id": _TENANT, "form_id": "f-a", "data": {}},
            {"id": "s-3", "tenant_id": _TENANT, "form_id": "f-b", "data": {}},
        ])
        summary = _run(audit())
        # Totals aggregate across ALL tenants in the live DB; filter
        # to just our test tenant to make assertions deterministic.
        per_tenant = summary["per_tenant"].get(_TENANT, {})
        assert per_tenant.get("forms") == 2
        assert per_tenant.get("submissions") == 3
        assert sorted(per_tenant.get("slugs", [])) == ["a", "b"]
    finally:
        _cleanup()


# ──────────────────────────────────────────────────────────────────
# 7–10. Migrate — idempotent + preserves FK + dry-run safe
# ──────────────────────────────────────────────────────────────────
def _seed_two_legacy_forms():
    _sync_db().forms.insert_many([
        {"id": "f-mig-1", "tenant_id": _TENANT, "slug": "mig-1",
         "name": "Legacy 1", "destination": "lead",
         "fields": [{"key": "email", "label": "Email", "type": "email",
                       "required": True}],
         "status": "published", "created_at": "2025-01-01T00:00:00Z"},
        {"id": "f-mig-2", "tenant_id": _TENANT, "slug": "mig-2",
         "name": "Legacy 2", "destination": "booking",
         "fields": [{"key": "when", "label": "When", "type": "date",
                       "required": True}],
         "status": "draft", "created_at": "2025-02-01T00:00:00Z"},
    ])


def test_migrate_first_run_inserts_rows_preserving_id():
    _cleanup()
    try:
        _seed_two_legacy_forms()
        # Also seed one submission so we can verify FK preserved.
        _sync_db().form_submissions.insert_one({
            "id": "s-mig-1", "tenant_id": _TENANT,
            "form_id": "f-mig-1", "data": {"email": "a@b.test"},
        })
        report = _run(migrate(dry_run=False))
        inserted = [r for r in report["migrated"] if r["action"] == "inserted"
                      and r["tenant_id"] == _TENANT]
        assert len(inserted) == 2
        assert report["errors"] == []
        # IDs preserved — form_submissions.form_id still resolves.
        mf_ids = {m["id"] for m in _sync_db().marketing_forms.find(
            {"tenant_id": _TENANT}, {"_id": 0, "id": 1}
        )}
        assert mf_ids == {"f-mig-1", "f-mig-2"}
        # Submission untouched + still cross-refs the migrated form.
        sub = _sync_db().form_submissions.find_one(
            {"id": "s-mig-1"}, {"_id": 0, "form_id": 1},
        )
        assert sub["form_id"] == "f-mig-1"
        # Marketing form carries the migration marker.
        mig = _sync_db().marketing_forms.find_one(
            {"id": "f-mig-1"}, {"_id": 0, "migrated_from_system_c": 1},
        )
        assert mig["migrated_from_system_c"] is True
    finally:
        _cleanup()


def test_migrate_second_run_is_idempotent():
    _cleanup()
    try:
        _seed_two_legacy_forms()
        _run(migrate(dry_run=False))
        # Count after first run.
        count_after_first = _sync_db().marketing_forms.count_documents(
            {"tenant_id": _TENANT},
        )
        assert count_after_first == 2
        # Re-run.
        report = _run(migrate(dry_run=False))
        skipped = [r for r in report["migrated"]
                     if r["action"] == "skipped-already-migrated"
                     and r["tenant_id"] == _TENANT]
        assert len(skipped) == 2
        assert report["errors"] == []
        # No duplicates.
        count_after_second = _sync_db().marketing_forms.count_documents(
            {"tenant_id": _TENANT},
        )
        assert count_after_second == 2
    finally:
        _cleanup()


def test_dry_run_makes_no_writes():
    _cleanup()
    try:
        _seed_two_legacy_forms()
        report = _run(migrate(dry_run=True))
        would = [r for r in report["migrated"]
                   if r["action"] == "would-insert"
                   and r["tenant_id"] == _TENANT]
        assert len(would) == 2
        # Nothing written.
        assert _sync_db().marketing_forms.count_documents(
            {"tenant_id": _TENANT},
        ) == 0
    finally:
        _cleanup()


def test_migrate_never_touches_form_submissions():
    _cleanup()
    try:
        _seed_two_legacy_forms()
        _sync_db().form_submissions.insert_many([
            {"id": f"s-untouched-{i}", "tenant_id": _TENANT,
             "form_id": "f-mig-1", "data": {"x": i}}
            for i in range(5)
        ])
        before = _sync_db().form_submissions.count_documents(
            {"tenant_id": _TENANT},
        )
        _run(migrate(dry_run=False))
        after = _sync_db().form_submissions.count_documents(
            {"tenant_id": _TENANT},
        )
        assert before == after == 5
    finally:
        _cleanup()
