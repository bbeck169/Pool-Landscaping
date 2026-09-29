"""Phase DOOR-HANGER · Feb 2026 — seed migration contract.

Locks the idempotency + preservation contract for
``migrations.seed_door_hanger_template``:

  1. First run inserts a row with the canonical DOOR-HANGER
     ``code`` + subject + body defaults.
  2. Second run is a no-op — the existing row's ``body`` /
     ``subject`` are preserved even when they differ from the
     migration's default (a tenant may have edited them via the
     marketing-templates UI).
  3. The seeded row carries the DOOR-HANGER category / channel /
     kind / flags so downstream code that filters ``marketing_
     templates`` by any of those fields still finds the row.
"""
from __future__ import annotations

import asyncio

import pytest

# ``_run`` mirrors the loop routing used by every other backend
# test in this repo — one shared event loop per file, no
# ``asyncio.run(...)`` per-test.
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _wipe_template_row():
    """Ensure a clean slate before + after every test — the seed
    migration is idempotency-tested here so leftover rows from
    prior test runs would poison the first-insert assertions."""
    from config import db
    _run(db.marketing_templates.delete_many(
        {"code": "door_hanger_job_completed"},
    ))
    yield
    _run(db.marketing_templates.delete_many(
        {"code": "door_hanger_job_completed"},
    ))


def test_first_run_inserts_the_canonical_row():
    from config import db
    from migrations.seed_door_hanger_template import (
        run,
        DOOR_HANGER_BODY_DEFAULT,
        DOOR_HANGER_SUBJECT_DEFAULT,
        TEMPLATE_CODE,
    )

    summary = _run(run())
    assert summary["inserted"] is True
    assert summary["code"] == TEMPLATE_CODE

    row = _run(db.marketing_templates.find_one(
        {"code": TEMPLATE_CODE}, {"_id": 0},
    ))
    assert row is not None
    assert row["code"] == TEMPLATE_CODE
    assert row["name"] == "Door Hanger — Job Completed"
    assert row["category"] == "service_completed"
    assert row["channel"] == "email"
    assert row["kind"] == "transactional"
    assert row["is_system"] is True
    assert row["is_default"] is True
    assert row["editable"] is True
    assert row["tenant_id"] is None   # global default
    # Subject + body match the module-level canonical strings so a
    # regression on either constant is visible from the test row.
    assert row["subject"] == DOOR_HANGER_SUBJECT_DEFAULT
    assert row["body"] == DOOR_HANGER_BODY_DEFAULT
    # Body carries the JOB_PHOTOS + section-injection tags.
    assert "{{JOB_PHOTOS}}" in row["body"]
    assert "{{DOOR_HANGER_HERO_HTML}}" in row["body"]
    assert "{{DOOR_HANGER_FOOTER_HTML}}" in row["body"]


def test_second_run_is_a_no_op_and_preserves_edited_body():
    from config import db
    from migrations.seed_door_hanger_template import run, TEMPLATE_CODE

    # First run seeds the row.
    _run(run())
    # Simulate a tenant edit via the marketing UI — swap in a
    # custom body + subject.
    custom_body = "<p>CUSTOM TENANT COPY — {{JOB_PHOTOS}}</p>"
    custom_subject = "Custom subject — {{COMPANY_NAME}}"
    _run(db.marketing_templates.update_one(
        {"code": TEMPLATE_CODE},
        {"$set": {"body": custom_body, "subject": custom_subject}},
    ))
    # Re-run — must be a no-op that PRESERVES the tenant edit.
    summary = _run(run())
    assert summary["inserted"] is False
    row = _run(db.marketing_templates.find_one(
        {"code": TEMPLATE_CODE}, {"_id": 0},
    ))
    assert row["body"] == custom_body, (
        "seed migration overwrote a tenant-edited body — must use "
        "$setOnInsert to guarantee edits survive re-runs"
    )
    assert row["subject"] == custom_subject


def test_re_run_after_row_deletion_reinserts_defaults():
    """If someone deletes the seed row, the next run rebuilds it
    with the canonical defaults."""
    from config import db
    from migrations.seed_door_hanger_template import (
        run,
        DOOR_HANGER_BODY_DEFAULT,
        TEMPLATE_CODE,
    )

    _run(run())
    _run(db.marketing_templates.delete_many({"code": TEMPLATE_CODE}))
    summary = _run(run())
    assert summary["inserted"] is True
    row = _run(db.marketing_templates.find_one(
        {"code": TEMPLATE_CODE}, {"_id": 0},
    ))
    assert row is not None
    assert row["body"] == DOOR_HANGER_BODY_DEFAULT
