"""SMS-DATA-CLEANUP · Feb-2026 — Pytest coverage for the ``--fix``
planner + apply path on ``scripts/audit_customer_phone_overlap.py``.

Strategy
--------
A fully isolated end-to-end test against the local Mongo running on
the preview pod. Each test case:

* seeds a unique ``test_tenant_id`` (uuid4-prefixed) plus one tenant
  doc + two customer docs — one with contaminated ``phone`` + mobile,
  one that is clean;
* invokes the audit script via ``subprocess`` (same mechanism ops
  will use), scoping every call with ``--tenant-id`` so the test
  never sees any real contaminated preview rows and never writes
  outside its own fixtures;
* asserts the stdout plan content, the Mongo post-conditions on the
  ``customers`` collection, and the audit-trail rows written to
  ``customer_phone_cleanup_log``;
* tears down tenants + customers + its own cleanup-log rows at the
  end regardless of pass/fail.

Covered properties:

1. ``--fix`` alone → dry-run: no customer / cleanup-log writes.
2. ``--fix --confirm --yes`` → applies the blanks; preserves mobile
   array ordering and non-``number_e164`` fields; writes correctly-
   shaped audit rows.
3. Idempotence: running ``--fix --confirm --yes`` a second time
   finds zero hits and writes nothing further.
4. ``--confirm`` without ``--fix`` → argparse error (exit 2).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient


ROOT = Path(__file__).resolve().parent.parent  # /app/backend
SCRIPT_MODULE = "scripts.audit_customer_phone_overlap"

load_dotenv(ROOT / ".env")

_MONGO_URL = os.environ.get("MONGO_URL") or ""
_DB_NAME = os.environ.get("DB_NAME") or ""

# The audit script uses the preview tenant's RC_FROM_NUMBER as one
# collision source. We hand our fixture tenant its own
# rc_sms_from_number so the test never relies on env state leaking
# in from the pod. A canonical throwaway US number works fine.
_FIXTURE_FROM_NUMBER = "+15555550199"
_FIXTURE_LAST10 = "5555550199"


# ═════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture
def mongo_db():
    if not (_MONGO_URL and _DB_NAME):
        pytest.skip("MONGO_URL / DB_NAME not configured — skipping test")
    client = MongoClient(_MONGO_URL)
    yield client[_DB_NAME]
    client.close()


@pytest.fixture
def seeded(mongo_db):
    """Seeds one tenant + two customers (one dirty, one clean) and
    cleans up every doc + any cleanup-log row it wrote on teardown."""
    tenant_id = f"test-cleanup-{uuid.uuid4()}"
    dirty_cid = f"cust-dirty-{uuid.uuid4()}"
    clean_cid = f"cust-clean-{uuid.uuid4()}"
    mongo_db.tenants.insert_one({
        "id": tenant_id,
        "name": "test-cleanup-tenant",
        "rc_sms_from_number": _FIXTURE_FROM_NUMBER,
        # Also drop the overlapping number into business_card.phone so
        # we can assert multi-source attribution.
        "settings": {"business_card": {"phone": _FIXTURE_FROM_NUMBER}},
    })
    # Dirty customer: phone + one of two mobiles overlap with tenant.
    mongo_db.customers.insert_one({
        "id": dirty_cid,
        "tenant_id": tenant_id,
        "name": "Dirty Row",
        "email": "dirty@example.test",
        "phone": _FIXTURE_FROM_NUMBER,
        "mobiles": [
            {
                "label": "home",
                "number_e164": _FIXTURE_FROM_NUMBER,
                "is_primary": True,
            },
            {
                "label": "work",
                "number_e164": "+15555550101",
                "is_primary": False,
            },
        ],
    })
    # Clean customer: nothing should ever be touched.
    mongo_db.customers.insert_one({
        "id": clean_cid,
        "tenant_id": tenant_id,
        "name": "Clean Row",
        "email": "clean@example.test",
        "phone": "+15555550111",
        "mobiles": [
            {"label": "home", "number_e164": "+15555550112",
             "is_primary": True},
        ],
    })
    try:
        yield {
            "tenant_id": tenant_id,
            "dirty_cid": dirty_cid,
            "clean_cid": clean_cid,
        }
    finally:
        mongo_db.tenants.delete_many({"id": tenant_id})
        mongo_db.customers.delete_many({"tenant_id": tenant_id})
        mongo_db.customer_phone_cleanup_log.delete_many(
            {"tenant_id": tenant_id},
        )


# ═════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════
def _run_script(*argv: str) -> subprocess.CompletedProcess:
    """Invoke the audit script via ``python -m`` from ``/app/backend``."""
    return subprocess.run(
        [sys.executable, "-m", SCRIPT_MODULE, *argv],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )


# ═════════════════════════════════════════════════════════════════════
# Tests
# ═════════════════════════════════════════════════════════════════════
def test_fix_dry_run_prints_plan_and_writes_nothing(mongo_db, seeded):
    """``--fix`` without ``--confirm`` prints the plan and leaves
    the customer doc + cleanup-log collection untouched."""
    tenant_id = seeded["tenant_id"]
    dirty_cid = seeded["dirty_cid"]

    pre_customer = mongo_db.customers.find_one({"id": dirty_cid})
    assert pre_customer["phone"] == _FIXTURE_FROM_NUMBER
    assert pre_customer["mobiles"][0]["number_e164"] == _FIXTURE_FROM_NUMBER

    proc = _run_script("--tenant-id", tenant_id, "--fix")
    assert proc.returncode == 0, proc.stderr

    # Plan content assertions.
    assert "Cleanup plan:" in proc.stdout
    assert "1 customer doc(s)" in proc.stdout  # only the dirty one
    assert "2 field value(s) to blank" in proc.stdout  # phone + 1 mobile
    assert dirty_cid in proc.stdout
    assert "customers.phone" in proc.stdout
    assert "customers.mobiles[].number_e164" in proc.stdout
    assert "Dry-run — no writes applied" in proc.stdout

    # Zero writes.
    post_customer = mongo_db.customers.find_one({"id": dirty_cid})
    assert post_customer["phone"] == _FIXTURE_FROM_NUMBER
    assert post_customer["mobiles"][0]["number_e164"] == _FIXTURE_FROM_NUMBER
    assert mongo_db.customer_phone_cleanup_log.count_documents(
        {"tenant_id": tenant_id},
    ) == 0


def test_fix_confirm_yes_applies_cleanup_and_writes_audit(mongo_db, seeded):
    """``--fix --confirm --yes`` blanks the two contaminated fields,
    preserves the clean mobile entry + its order, leaves the clean
    customer untouched, and writes two correctly-shaped audit rows."""
    tenant_id = seeded["tenant_id"]
    dirty_cid = seeded["dirty_cid"]
    clean_cid = seeded["clean_cid"]

    proc = _run_script(
        "--tenant-id", tenant_id, "--fix", "--confirm", "--yes",
    )
    assert proc.returncode == 0, proc.stderr
    assert "Cleanup complete" in proc.stdout
    assert "updated=1 doc(s)" in proc.stdout
    assert "audit_rows=2" in proc.stdout

    # Dirty customer: phone blanked, first mobile blanked (number_e164
    # only), second mobile untouched, ordering preserved, label +
    # is_primary preserved.
    dirty = mongo_db.customers.find_one({"id": dirty_cid})
    assert dirty["phone"] == ""
    assert len(dirty["mobiles"]) == 2
    assert dirty["mobiles"][0]["label"] == "home"
    assert dirty["mobiles"][0]["number_e164"] == ""
    assert dirty["mobiles"][0]["is_primary"] is True
    assert dirty["mobiles"][1]["label"] == "work"
    assert dirty["mobiles"][1]["number_e164"] == "+15555550101"
    assert dirty["mobiles"][1]["is_primary"] is False

    # Clean customer: completely untouched.
    clean = mongo_db.customers.find_one({"id": clean_cid})
    assert clean["phone"] == "+15555550111"
    assert clean["mobiles"][0]["number_e164"] == "+15555550112"

    # Audit log: two rows for the dirty customer, shape matches spec.
    rows: List[Dict[str, Any]] = list(
        mongo_db.customer_phone_cleanup_log.find({"tenant_id": tenant_id}),
    )
    assert len(rows) == 2
    run_ids = {r["run_id"] for r in rows}
    assert len(run_ids) == 1, "all rows in one invocation share one run_id"
    fields = sorted(r["field"] for r in rows)
    assert fields == ["mobiles[0].number_e164", "phone"]
    for r in rows:
        assert r["tenant_id"] == tenant_id
        assert r["customer_id"] == dirty_cid
        assert r["new_value"] == ""
        assert r["old_value"] == _FIXTURE_FROM_NUMBER
        assert isinstance(r["matched_sources"], list)
        assert len(r["matched_sources"]) >= 1
        # At least the tenant-owned sources we seeded must attribute.
        assert any(
            s in r["matched_sources"]
            for s in (
                "tenants.rc_sms_from_number",
                "tenants.settings.business_card.phone",
            )
        )
        assert isinstance(r["cleaned_at"], str)
        assert "T" in r["cleaned_at"]  # ISO-8601


def test_fix_apply_is_idempotent(mongo_db, seeded):
    """A second ``--fix --confirm --yes`` after cleanup finds zero
    contaminated rows and writes zero further audit entries."""
    tenant_id = seeded["tenant_id"]

    # First apply.
    first = _run_script(
        "--tenant-id", tenant_id, "--fix", "--confirm", "--yes",
    )
    assert first.returncode == 0
    pre_log_count = mongo_db.customer_phone_cleanup_log.count_documents(
        {"tenant_id": tenant_id},
    )
    assert pre_log_count == 2

    # Second apply: audit itself should now find zero hits.
    second = _run_script(
        "--tenant-id", tenant_id, "--fix", "--confirm", "--yes",
    )
    assert second.returncode == 0, second.stderr
    assert "No contaminated customer records found" in second.stdout

    # Zero further audit rows written.
    post_log_count = mongo_db.customer_phone_cleanup_log.count_documents(
        {"tenant_id": tenant_id},
    )
    assert post_log_count == pre_log_count


def test_confirm_without_fix_is_argparse_error():
    """``--confirm`` alone must be rejected by argparse (exit 2)."""
    proc = _run_script("--confirm")
    assert proc.returncode == 2
    assert "--confirm requires --fix" in proc.stderr


def test_audit_default_still_read_only(mongo_db, seeded):
    """Default invocation (no ``--fix``) still runs the read-only
    audit, finds the dirty row, and leaves Mongo untouched."""
    tenant_id = seeded["tenant_id"]
    dirty_cid = seeded["dirty_cid"]

    proc = _run_script("--tenant-id", tenant_id)
    assert proc.returncode == 0
    assert "contaminated row(s)" in proc.stdout
    assert dirty_cid in proc.stdout

    # No writes.
    dirty = mongo_db.customers.find_one({"id": dirty_cid})
    assert dirty["phone"] == _FIXTURE_FROM_NUMBER
    assert mongo_db.customer_phone_cleanup_log.count_documents(
        {"tenant_id": tenant_id},
    ) == 0
