"""Phase EMAIL-MIGRATE · Batch 2 · Feb-2026 — seed migration contract:
``lead_thank_you_reply_email``."""
from __future__ import annotations

import asyncio

import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _wipe_row():
    from config import db
    _run(db.marketing_templates.delete_many(
        {"code": "lead_thank_you_reply_email"},
    ))
    yield
    _run(db.marketing_templates.delete_many(
        {"code": "lead_thank_you_reply_email"},
    ))


def test_first_run_inserts_the_canonical_row():
    from config import db
    from migrations.seed_lead_thank_you_reply_template import (
        run, BODY_DEFAULT, SUBJECT_DEFAULT, TEMPLATE_CODE, MERGE_TAGS,
    )
    summary = _run(run())
    assert summary["inserted"] is True
    row = _run(db.marketing_templates.find_one(
        {"code": TEMPLATE_CODE}, {"_id": 0},
    ))
    assert row is not None
    assert row["tenant_id"] is None
    assert row["category"] == "lead"
    assert row["subject"] == SUBJECT_DEFAULT
    assert row["body"] == BODY_DEFAULT
    assert row["merge_tags"] == MERGE_TAGS
    assert "{{RECIPIENT_NAME}}" in row["body"]
    assert "{{REJECT_STATE}}" in row["body"]
    assert "{{COMPANY_NAME}}" in row["body"]
    # BUGFIX: no hardcoded tenant name in the seeded copy.
    assert "Pool & Landscaping of Vistancia" not in row["body"]
    # PHONE-PURGE invariant.
    assert "602-887-4400" not in row["body"]
    assert "6028874400" not in row["body"]


def test_second_run_preserves_edited_body():
    from config import db
    from migrations.seed_lead_thank_you_reply_template import (
        run, TEMPLATE_CODE,
    )
    _run(run())
    custom = "<p>THANK-YOU-CUSTOM {{RECIPIENT_NAME}}</p>"
    _run(db.marketing_templates.update_one(
        {"code": TEMPLATE_CODE},
        {"$set": {"body": custom}},
    ))
    summary = _run(run())
    assert summary["inserted"] is False
    row = _run(db.marketing_templates.find_one(
        {"code": TEMPLATE_CODE}, {"_id": 0},
    ))
    assert row["body"] == custom


def test_re_run_after_deletion_reinserts_defaults():
    from config import db
    from migrations.seed_lead_thank_you_reply_template import (
        run, BODY_DEFAULT, TEMPLATE_CODE,
    )
    _run(run())
    _run(db.marketing_templates.delete_many({"code": TEMPLATE_CODE}))
    summary = _run(run())
    assert summary["inserted"] is True
    row = _run(db.marketing_templates.find_one(
        {"code": TEMPLATE_CODE}, {"_id": 0},
    ))
    assert row["body"] == BODY_DEFAULT
