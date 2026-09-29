"""Phase EMAIL-MIGRATE · Batch 1 · Feb-2026 — seed migration contract:
``signup_verify_code_email``."""
from __future__ import annotations

import pytest

from tests._asyncio_loop_isolation import make_isolated_loop, bind_config_db

# Feb-2026 · Test Hygiene Phase 2 — isolated event loop + Motor
# rebind so cross-module ``asyncio.get_event_loop()`` poisoning
# from unrelated tests cannot break this seed under ``pytest -k``.
_LOOP, _run = make_isolated_loop()


@pytest.fixture(scope="module", autouse=True)
def _bind_isolated_db():
    yield from bind_config_db(_LOOP)


@pytest.fixture(autouse=True)
def _wipe_row():
    from config import db
    _run(db.marketing_templates.delete_many(
        {"code": "signup_verify_code_email"},
    ))
    yield
    _run(db.marketing_templates.delete_many(
        {"code": "signup_verify_code_email"},
    ))


def test_first_run_inserts_the_canonical_row():
    from config import db
    from migrations.seed_signup_verify_code_template import (
        run, BODY_DEFAULT, SUBJECT_DEFAULT, TEMPLATE_CODE, MERGE_TAGS,
    )
    summary = _run(run())
    assert summary["inserted"] is True
    row = _run(db.marketing_templates.find_one(
        {"code": TEMPLATE_CODE}, {"_id": 0},
    ))
    assert row is not None
    assert row["tenant_id"] is None
    assert row["category"] == "signup"
    assert row["subject"] == SUBJECT_DEFAULT
    assert row["body"] == BODY_DEFAULT
    assert row["merge_tags"] == MERGE_TAGS
    assert "{{VERIFY_CODE}}" in row["body"]
    assert "{{BUSINESS_NAME}}" in row["body"]
    assert "{{RECIPIENT_NAME}}" in row["body"]


def test_second_run_preserves_edited_body():
    from config import db
    from migrations.seed_signup_verify_code_template import (
        run, TEMPLATE_CODE,
    )
    _run(run())
    custom = "<p>SIGNUP-CUSTOM {{VERIFY_CODE}}</p>"
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
    from migrations.seed_signup_verify_code_template import (
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
