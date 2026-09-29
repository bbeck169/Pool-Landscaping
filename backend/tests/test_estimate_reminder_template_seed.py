"""Phase EMAIL-MIGRATE · Batch 4 · Feb-2026 — seed migration contract:
``estimate_reminder_email``."""
from __future__ import annotations

import asyncio
import os

import pytest


# Batch 4 · Feb-2026 — isolated event loop + fresh Motor client so
# ``asyncio.get_event_loop()`` poisoning from unrelated tests
# (:mod:`test_reminder_doc_type_routing` etc.) cannot break this
# module when run under the shared ``pytest -k`` filter.
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _orig = _cfg.db
    _cfg.db = fresh_db
    try:
        yield
    finally:
        _cfg.db = _orig


@pytest.fixture(autouse=True)
def _wipe_row():
    from config import db
    _run(db.marketing_templates.delete_many(
        {"code": "estimate_reminder_email"},
    ))
    yield
    _run(db.marketing_templates.delete_many(
        {"code": "estimate_reminder_email"},
    ))


def test_first_run_inserts_the_canonical_row():
    from config import db
    from migrations.seed_estimate_reminder_template import (
        run, BODY_DEFAULT, SUBJECT_DEFAULT, TEMPLATE_CODE, MERGE_TAGS,
    )
    summary = _run(run())
    assert summary["inserted"] is True
    row = _run(db.marketing_templates.find_one(
        {"code": TEMPLATE_CODE}, {"_id": 0},
    ))
    assert row is not None
    assert row["tenant_id"] is None
    assert row["category"] == "finance"
    assert row["subject"] == SUBJECT_DEFAULT
    assert row["body"] == BODY_DEFAULT
    assert row["merge_tags"] == MERGE_TAGS
    for tok in ("{{ESTIMATE_NUMBER}}", "{{ESTIMATE_TOTAL}}",
                 "{{ESTIMATE_EXPIRES}}", "{{ACCEPT_LINK}}",
                 "{{COMPANY_NAME}}", "{{CUSTOMER_NAME}}"):
        assert tok in row["body"]
    # Guard: estimate reminder must NEVER emit the invoice-only
    # "outstanding balance" / "amount due" / "Pay Now" copy.
    assert "outstanding balance" not in row["body"].lower()
    assert "pay now" not in row["body"].lower()
    assert "amount due" not in row["body"].lower()


def test_second_run_preserves_edited_body():
    from config import db
    from migrations.seed_estimate_reminder_template import (
        run, TEMPLATE_CODE,
    )
    _run(run())
    custom = "<p>ESTIMATE-CUSTOM {{ESTIMATE_NUMBER}}</p>"
    _run(db.marketing_templates.update_one(
        {"code": TEMPLATE_CODE}, {"$set": {"body": custom}},
    ))
    summary = _run(run())
    assert summary["inserted"] is False
    row = _run(db.marketing_templates.find_one(
        {"code": TEMPLATE_CODE}, {"_id": 0},
    ))
    assert row["body"] == custom


def test_re_run_after_deletion_reinserts_defaults():
    from config import db
    from migrations.seed_estimate_reminder_template import (
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
