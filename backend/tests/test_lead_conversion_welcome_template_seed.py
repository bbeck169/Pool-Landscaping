"""Phase EMAIL-MIGRATE · Batch 2 · Feb-2026 — seed migration contract:
``lead_conversion_welcome_email``.

Includes explicit assertions locking the BUGFIX contract:
* No hardcoded ``"Pool & Landscaping of Vistancia"`` in the seeded
  body or subject — the row uses ``{{COMPANY_NAME}}``.
* No hardcoded phone literal (``602-887-4400``, parenthesised or
  otherwise) in the seeded body — the row uses ``{{COMPANY_PHONE}}``.
"""
from __future__ import annotations

import asyncio

import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _wipe_row():
    from config import db
    _run(db.marketing_templates.delete_many(
        {"code": "lead_conversion_welcome_email"},
    ))
    yield
    _run(db.marketing_templates.delete_many(
        {"code": "lead_conversion_welcome_email"},
    ))


def test_first_run_inserts_the_canonical_row():
    from config import db
    from migrations.seed_lead_conversion_welcome_template import (
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
    assert "{{CUSTOMER_NAME}}" in row["body"]
    assert "{{COMPANY_NAME}}" in row["body"]
    assert "{{COMPANY_PHONE}}" in row["body"]
    assert "{{PORTAL_LINK}}" in row["body"]
    # BUGFIX assertions — the row must NOT ship with the plofv-
    # specific tenant name or the plofv-internal phone literal.
    assert "Pool & Landscaping of Vistancia" not in row["body"]
    assert "Pool & Landscaping of Vistancia" not in row["subject"]
    assert "Pool &amp; Landscaping of Vistancia" not in row["body"]
    for phone_literal in ("602-887-4400", "(602) 887-4400",
                          "6028874400", "602.887.4400"):
        assert phone_literal not in row["body"], (
            f"seeded body must not carry hardcoded phone "
            f"{phone_literal!r} — the migration replaces it with "
            "{{COMPANY_PHONE}}"
        )


def test_second_run_preserves_edited_body():
    from config import db
    from migrations.seed_lead_conversion_welcome_template import (
        run, TEMPLATE_CODE,
    )
    _run(run())
    custom = "<p>WELCOME-CUSTOM {{CUSTOMER_NAME}}</p>"
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
    from migrations.seed_lead_conversion_welcome_template import (
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
