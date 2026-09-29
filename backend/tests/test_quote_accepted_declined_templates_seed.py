"""Phase EMAIL-MIGRATE · Batch 3 · Feb-2026 — seed migration contract:
``quote_accepted_owner_email`` + ``quote_declined_owner_email``."""
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
def _wipe_rows():
    from config import db
    from migrations.seed_quote_accepted_declined_templates import (
        TEMPLATE_CODES,
    )
    _run(db.marketing_templates.delete_many(
        {"code": {"$in": list(TEMPLATE_CODES)}},
    ))
    yield
    _run(db.marketing_templates.delete_many(
        {"code": {"$in": list(TEMPLATE_CODES)}},
    ))


def test_first_run_inserts_both_rows():
    from config import db
    from migrations.seed_quote_accepted_declined_templates import (
        run, ACCEPTED_CODE, DECLINED_CODE,
        ACCEPTED_BODY, DECLINED_BODY,
        ACCEPTED_SUBJECT, DECLINED_SUBJECT,
        MERGE_TAGS, TEMPLATE_CODES,
    )
    summary = _run(run())
    assert set(summary["inserted"]) == set(TEMPLATE_CODES)

    accepted = _run(db.marketing_templates.find_one(
        {"code": ACCEPTED_CODE}, {"_id": 0},
    ))
    declined = _run(db.marketing_templates.find_one(
        {"code": DECLINED_CODE}, {"_id": 0},
    ))
    assert accepted is not None and declined is not None
    for row in (accepted, declined):
        assert row["tenant_id"] is None
        assert row["category"] == "quote"
        assert row["channel"] == "email"
        assert row["merge_tags"] == MERGE_TAGS
        # Batch-3 canonical tags all surface.
        for tok in ("{{QUOTE_HEADLINE}}", "{{QUOTE_TOTAL}}",
                     "{{QUOTE_LABEL}}", "{{QUOTE_SHORT_ID}}",
                     "{{QUOTE_ADMIN_LINK}}", "{{CUSTOMER_NAME}}"):
            assert tok in row["body"], (row["code"], tok)
    assert accepted["subject"] == ACCEPTED_SUBJECT
    assert declined["subject"] == DECLINED_SUBJECT
    assert accepted["body"] == ACCEPTED_BODY
    assert declined["body"] == DECLINED_BODY


def test_second_run_preserves_edited_rows_independently():
    from config import db
    from migrations.seed_quote_accepted_declined_templates import (
        run, ACCEPTED_CODE, DECLINED_CODE, DECLINED_BODY,
    )
    _run(run())
    custom_accepted = "<p>ACCEPTED-CUSTOM {{QUOTE_TOTAL}}</p>"
    _run(db.marketing_templates.update_one(
        {"code": ACCEPTED_CODE},
        {"$set": {"body": custom_accepted}},
    ))
    summary = _run(run())
    assert summary["inserted"] == []
    a = _run(db.marketing_templates.find_one(
        {"code": ACCEPTED_CODE}, {"_id": 0},
    ))
    d = _run(db.marketing_templates.find_one(
        {"code": DECLINED_CODE}, {"_id": 0},
    ))
    assert a["body"] == custom_accepted        # preserved
    assert d["body"] == DECLINED_BODY          # untouched


def test_re_run_after_deletion_reinserts_defaults():
    from config import db
    from migrations.seed_quote_accepted_declined_templates import (
        run, ACCEPTED_CODE, DECLINED_CODE,
        ACCEPTED_BODY, DECLINED_BODY, TEMPLATE_CODES,
    )
    _run(run())
    _run(db.marketing_templates.delete_many(
        {"code": {"$in": list(TEMPLATE_CODES)}},
    ))
    summary = _run(run())
    assert set(summary["inserted"]) == set(TEMPLATE_CODES)
    a = _run(db.marketing_templates.find_one(
        {"code": ACCEPTED_CODE}, {"_id": 0},
    ))
    d = _run(db.marketing_templates.find_one(
        {"code": DECLINED_CODE}, {"_id": 0},
    ))
    assert a["body"] == ACCEPTED_BODY
    assert d["body"] == DECLINED_BODY
