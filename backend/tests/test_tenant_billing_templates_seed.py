"""Phase EMAIL-MIGRATE · Batch 3 · Feb-2026 — seed migration contracts:
``tenant_billing_trial_reminder_email`` + ``tenant_billing_dunning_email``."""
from __future__ import annotations

import asyncio

import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _wipe_rows():
    from config import db
    from migrations.seed_tenant_billing_templates import TEMPLATE_CODES
    _run(db.marketing_templates.delete_many(
        {"code": {"$in": list(TEMPLATE_CODES)}},
    ))
    yield
    _run(db.marketing_templates.delete_many(
        {"code": {"$in": list(TEMPLATE_CODES)}},
    ))


def test_first_run_inserts_both_billing_rows():
    from config import db
    from migrations.seed_tenant_billing_templates import (
        run, TRIAL_CODE, DUNNING_CODE,
        TRIAL_BODY, DUNNING_BODY,
        TRIAL_SUBJECT, DUNNING_SUBJECT,
        TRIAL_MERGE_TAGS, DUNNING_MERGE_TAGS, TEMPLATE_CODES,
    )
    summary = _run(run())
    assert set(summary["inserted"]) == set(TEMPLATE_CODES)

    trial = _run(db.marketing_templates.find_one(
        {"code": TRIAL_CODE}, {"_id": 0},
    ))
    dunning = _run(db.marketing_templates.find_one(
        {"code": DUNNING_CODE}, {"_id": 0},
    ))
    for row in (trial, dunning):
        assert row["tenant_id"] is None
        assert row["category"] == "billing"
        assert row["channel"] == "email"
        assert row["kind"] == "transactional"
    assert trial["body"] == TRIAL_BODY
    assert dunning["body"] == DUNNING_BODY
    assert trial["subject"] == TRIAL_SUBJECT
    assert dunning["subject"] == DUNNING_SUBJECT
    assert trial["merge_tags"] == TRIAL_MERGE_TAGS
    assert dunning["merge_tags"] == DUNNING_MERGE_TAGS
    # Trial body carries the trial-only tags.
    for tok in ("{{TRIAL_END_LOCAL}}", "{{PLAN_AMOUNT}}",
                 "{{CANCEL_LINK}}", "{{ADMIN_NAME}}"):
        assert tok in trial["body"]
    # Dunning body carries the update-card link + admin name.
    for tok in ("{{UPDATE_CARD_LINK}}", "{{ADMIN_NAME}}",
                 "{{COMPANY_NAME}}"):
        assert tok in dunning["body"]


def test_second_run_preserves_each_row_independently():
    from config import db
    from migrations.seed_tenant_billing_templates import (
        run, TRIAL_CODE, DUNNING_CODE, DUNNING_BODY,
    )
    _run(run())
    custom_trial = "<p>TRIAL-CUSTOM {{PLAN_AMOUNT}}</p>"
    _run(db.marketing_templates.update_one(
        {"code": TRIAL_CODE}, {"$set": {"body": custom_trial}},
    ))
    summary = _run(run())
    assert summary["inserted"] == []
    trial = _run(db.marketing_templates.find_one(
        {"code": TRIAL_CODE}, {"_id": 0},
    ))
    dunning = _run(db.marketing_templates.find_one(
        {"code": DUNNING_CODE}, {"_id": 0},
    ))
    assert trial["body"] == custom_trial
    assert dunning["body"] == DUNNING_BODY


def test_re_run_after_deletion_reinserts_defaults():
    from config import db
    from migrations.seed_tenant_billing_templates import (
        run, TRIAL_CODE, DUNNING_CODE,
        TRIAL_BODY, DUNNING_BODY, TEMPLATE_CODES,
    )
    _run(run())
    _run(db.marketing_templates.delete_many(
        {"code": {"$in": list(TEMPLATE_CODES)}},
    ))
    summary = _run(run())
    assert set(summary["inserted"]) == set(TEMPLATE_CODES)
    trial = _run(db.marketing_templates.find_one(
        {"code": TRIAL_CODE}, {"_id": 0},
    ))
    dunning = _run(db.marketing_templates.find_one(
        {"code": DUNNING_CODE}, {"_id": 0},
    ))
    assert trial["body"] == TRIAL_BODY
    assert dunning["body"] == DUNNING_BODY
