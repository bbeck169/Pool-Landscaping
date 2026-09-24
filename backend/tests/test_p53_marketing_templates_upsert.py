"""Phase P53 · Feb-2026 — Idempotent marketing_templates upsert.

Locks the version-aware upsert semantics of
``seed_referral_credit_templates`` for the
``referral_credit_earned_email`` template:

  1. Fresh insert — row gets the new BOOM body + version marker.
  2. Second run — idempotent; no double-write, counts land in
     ``skipped_current``.
  3. Legacy Phase-10 row (``system=True``, body matches
     ``_REFERRAL_EMAIL_BODY_LEGACY_P10``) — UPGRADED to BOOM body +
     version marker.
  4. Tenant-customized row (``system=True`` but body diverges) —
     SKIPPED under normal upsert; upgraded ONLY if
     ``force_upgrade=True``.
  5. Non-system row (``system=False``) — always SKIPPED.

The SMS row keeps insert-if-missing semantics (no P53 redesign).
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import List

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from services.referral_watcher import (
    _REFERRAL_EMAIL_BODY,
    _REFERRAL_EMAIL_BODY_LEGACY_P10,
    _REFERRAL_EMAIL_BODY_VERSION,
    seed_referral_credit_templates,
)
from tests._phase34_asyncio import batch_safe_run as _run


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "p53_upsert_"


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def cleanup(dbc):
    tenant_ids: List[str] = []
    yield tenant_ids
    if tenant_ids:
        dbc.tenants.delete_many({"id": {"$in": tenant_ids}})
        dbc.marketing_templates.delete_many({"tenant_id": {"$in": tenant_ids}})


def _seed_tenant(dbc, ids: List[str]) -> str:
    tid = f"{TAG}tenant-{uuid.uuid4().hex[:6]}"
    dbc.tenants.insert_one({
        "id": tid,
        "name": f"P53 Upsert Test {tid}",
        "created_at": "2026-02-15T00:00:00Z",
    })
    ids.append(tid)
    return tid


def _run_upsert(*, force_upgrade: bool = False) -> dict:
    return _run(seed_referral_credit_templates(
        force_upgrade=force_upgrade,
    ))


def _fetch_email_row(dbc, tid: str) -> dict:
    return dbc.marketing_templates.find_one(
        {"tenant_id": tid, "system_key": "referral_credit_earned_email"},
        {"_id": 0},
    )


# ═════════════════════════════════════════════════════════════════════
# Section 1 — Fresh insert
# ═════════════════════════════════════════════════════════════════════
def test_fresh_tenant_inserts_boom_body_and_version(dbc, cleanup):
    tid = _seed_tenant(dbc, cleanup)

    counts = _run_upsert()

    row = _fetch_email_row(dbc, tid)
    assert row is not None, "expected an email row after seed"
    assert row["body"] == _REFERRAL_EMAIL_BODY
    assert row["body_version"] == _REFERRAL_EMAIL_BODY_VERSION
    assert row["system"] is True
    assert row["channel"] == "email"
    assert counts["inserted"] >= 1


# ═════════════════════════════════════════════════════════════════════
# Section 2 — Idempotent second run
# ═════════════════════════════════════════════════════════════════════
def test_second_run_is_idempotent(dbc, cleanup):
    tid = _seed_tenant(dbc, cleanup)

    _run_upsert()          # first pass — insert
    row1 = _fetch_email_row(dbc, tid)
    counts2 = _run_upsert()  # second pass — skip
    row2 = _fetch_email_row(dbc, tid)

    assert row1["body"] == row2["body"]
    assert row1["body_version"] == row2["body_version"]
    # ``updated_at`` should also be untouched by the idempotent pass —
    # skipping means no write. We assert equality on the timestamp.
    assert row1["updated_at"] == row2["updated_at"]
    assert counts2["skipped_current"] >= 1


# ═════════════════════════════════════════════════════════════════════
# Section 3 — Upgrade legacy Phase-10 body
# ═════════════════════════════════════════════════════════════════════
def test_legacy_phase10_row_upgraded_to_boom(dbc, cleanup):
    """A pre-P53 system row with the Phase-10 body must be upgraded
    in place — this is the primary migration path."""
    tid = _seed_tenant(dbc, cleanup)
    # Pre-seed the row with the OLD Phase-10 canonical body.
    dbc.marketing_templates.insert_one({
        "id": f"{TAG}row-{uuid.uuid4().hex[:6]}",
        "tenant_id": tid,
        "system_key": "referral_credit_earned_email",
        "name": "Referral credit earned — Email",
        "channel": "email",
        "category": "referral",
        "subject": "You earned a {{REFERRAL_CREDIT_AMOUNT}} credit!",
        "body": _REFERRAL_EMAIL_BODY_LEGACY_P10,
        "active": True,
        "system": True,
        "created_at": "2026-02-01T00:00:00Z",
        "updated_at": "2026-02-01T00:00:00Z",
    })

    counts = _run_upsert()

    row = _fetch_email_row(dbc, tid)
    assert row["body"] == _REFERRAL_EMAIL_BODY, (
        "expected legacy Phase-10 body to be upgraded to BOOM body"
    )
    assert row["body_version"] == _REFERRAL_EMAIL_BODY_VERSION
    assert counts["upgraded"] >= 1


# ═════════════════════════════════════════════════════════════════════
# Section 4 — Customized row is preserved
# ═════════════════════════════════════════════════════════════════════
def test_tenant_customized_row_is_preserved(dbc, cleanup):
    """When ``system=True`` but the body diverges from every known
    canonical prior, the tenant has customized the copy — the upsert
    MUST leave it alone."""
    tid = _seed_tenant(dbc, cleanup)
    custom_body = "<p>Our custom referral copy — do not overwrite!</p>"
    dbc.marketing_templates.insert_one({
        "id": f"{TAG}row-{uuid.uuid4().hex[:6]}",
        "tenant_id": tid,
        "system_key": "referral_credit_earned_email",
        "name": "Referral credit earned — Email",
        "channel": "email",
        "category": "referral",
        "subject": "Our custom subject",
        "body": custom_body,
        "active": True,
        "system": True,
        "created_at": "2026-02-01T00:00:00Z",
        "updated_at": "2026-02-01T00:00:00Z",
    })

    counts = _run_upsert()

    row = _fetch_email_row(dbc, tid)
    assert row["body"] == custom_body, (
        "customized copy must be preserved by the upsert"
    )
    assert row.get("body_version") != _REFERRAL_EMAIL_BODY_VERSION
    assert counts["skipped_customized"] >= 1


def test_force_upgrade_overwrites_customized_row(dbc, cleanup):
    """``force_upgrade=True`` is the emergency escape hatch — CLI
    operators can force every system row back to canonical BOOM."""
    tid = _seed_tenant(dbc, cleanup)
    dbc.marketing_templates.insert_one({
        "id": f"{TAG}row-{uuid.uuid4().hex[:6]}",
        "tenant_id": tid,
        "system_key": "referral_credit_earned_email",
        "name": "Referral credit earned — Email",
        "channel": "email",
        "category": "referral",
        "subject": "Our custom subject",
        "body": "<p>Custom copy A</p>",
        "active": True,
        "system": True,
        "created_at": "2026-02-01T00:00:00Z",
        "updated_at": "2026-02-01T00:00:00Z",
    })

    counts = _run_upsert(force_upgrade=True)

    row = _fetch_email_row(dbc, tid)
    assert row["body"] == _REFERRAL_EMAIL_BODY
    assert row["body_version"] == _REFERRAL_EMAIL_BODY_VERSION
    assert counts["upgraded"] >= 1


# ═════════════════════════════════════════════════════════════════════
# Section 5 — Non-system row is always skipped
# ═════════════════════════════════════════════════════════════════════
def test_non_system_row_is_never_touched(dbc, cleanup):
    tid = _seed_tenant(dbc, cleanup)
    dbc.marketing_templates.insert_one({
        "id": f"{TAG}row-{uuid.uuid4().hex[:6]}",
        "tenant_id": tid,
        "system_key": "referral_credit_earned_email",
        "name": "Tenant-owned copy",
        "channel": "email",
        "category": "referral",
        "subject": "Tenant subject",
        "body": _REFERRAL_EMAIL_BODY_LEGACY_P10,  # even a canonical prior
        "active": True,
        "system": False,   # ← tenant fully overrode
        "created_at": "2026-02-01T00:00:00Z",
        "updated_at": "2026-02-01T00:00:00Z",
    })

    counts = _run_upsert(force_upgrade=True)

    row = _fetch_email_row(dbc, tid)
    assert row["body"] == _REFERRAL_EMAIL_BODY_LEGACY_P10, (
        "system=False row must be untouched even under force_upgrade"
    )
    assert counts["skipped_non_system"] >= 1


# ═════════════════════════════════════════════════════════════════════
# Section 6 — SMS row is unaffected by P53
# ═════════════════════════════════════════════════════════════════════
def test_sms_row_insert_if_missing(dbc, cleanup):
    tid = _seed_tenant(dbc, cleanup)

    _run_upsert()

    sms_row = dbc.marketing_templates.find_one(
        {"tenant_id": tid, "system_key": "referral_credit_earned_sms"},
        {"_id": 0},
    )
    assert sms_row is not None
    assert sms_row["channel"] == "sms"
    # SMS row does NOT get a body_version — it's out of P53 scope.
    assert "body_version" not in sms_row or \
           sms_row.get("body_version") is None
