"""Feb-2026 · Quote/Estimate email seed regression suite.

Covers:
  1. Fresh tenant → seeder inserts exactly one row with the stable
     ``system_key``.
  2. Re-running the seeder is idempotent — count stable, no duplicate
     rows.
  3. User edits to the body survive the next seed run (preserve
     tenant customization).
  4. ``GET /api/marketing/templates?channel=email&category=quotes``
     returns the seeded row for an authenticated admin.
  5. Rendering the subject + body with a sample quote context
     resolves every merge tag the template references:
       * CUSTOMER_FIRST_NAME
       * QUOTE_LABEL  (customer-visible doc-type)
       * QUOTE_SHORT_ID
       * QUOTE_TOTAL  (formatted dollars)
       * QUOTE_LINE_ITEMS_HTML — every item description + line total
       * ESTIMATE_LINK — present inside the CTA ``<a href=...>``
       * COMPANY_NAME

Isolation: tests seed a throwaway tenant via direct Mongo writes
and reap it on teardown so the admin tenant's row count stays
untouched. Live admin smoke (#4) also seeds + reaps a dedicated
tenant + admin user so it exercises the real HTTP stack without
polluting the primary demo tenant.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Dict, List

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"

TAG = "qep-seed-"


def _env():
    return dotenv_values(Path(__file__).resolve().parents[1] / ".env")


@pytest.fixture(scope="module")
def dbc():
    env = _env()
    return MongoClient(env["MONGO_URL"])[env["DB_NAME"]]


@pytest.fixture
def tenant_cleanup(dbc):
    tids: List[str] = []
    uids: List[str] = []
    yield (tids, uids)
    if tids:
        dbc.marketing_templates.delete_many({"tenant_id": {"$in": tids}})
        dbc.tenants.delete_many({"id": {"$in": tids}})
    if uids:
        dbc.users.delete_many({"id": {"$in": uids}})


def _mk_tenant(dbc, tids: List[str]) -> str:
    tid = f"{TAG}t-{uuid.uuid4().hex[:8]}"
    dbc.tenants.insert_one({
        "id": tid, "slug": tid,
        "name": f"QEP seed test {tid}",
        "created_at": "2026-02-15T00:00:00Z",
    })
    tids.append(tid)
    return tid


def _mk_admin(dbc, tenant_id: str, uids: List[str]) -> str:
    from utils import hash_password  # type: ignore
    uid = f"{TAG}u-{uuid.uuid4().hex[:8]}"
    email = f"{TAG}{uuid.uuid4().hex[:8]}@example.com"
    dbc.users.insert_one({
        "id": uid, "email": email,
        "password_hash": hash_password("password123"),
        "role": "admin", "tenant_id": tenant_id, "status": "active",
        "created_at": "2026-02-15T00:00:00Z",
    })
    uids.append(uid)
    return email


# ═══════════════════════════════════════════════════════════════════
# 1. Fresh insert
# ═══════════════════════════════════════════════════════════════════
def test_seed_inserts_exactly_one_row_per_tenant(dbc, tenant_cleanup):
    tids, _ = tenant_cleanup
    tid = _mk_tenant(dbc, tids)
    # Make sure nothing is pre-seeded for this throwaway tenant.
    dbc.marketing_templates.delete_many(
        {"tenant_id": tid, "system_key": "quote_estimate_email"},
    )

    from services.migrations.seed_quote_estimate_template import (
        seed_for_tenant, TEMPLATE_SYSTEM_KEY,
    )
    report = asyncio.get_event_loop().run_until_complete(
        seed_for_tenant(tid),
    )
    assert report == {
        "inserted": 1,
        "skipped_current": 0,
        "skipped_customized": 0,
        "skipped_non_system": 0,
    }, report

    rows = list(dbc.marketing_templates.find(
        {"tenant_id": tid, "system_key": TEMPLATE_SYSTEM_KEY},
    ))
    assert len(rows) == 1
    row = rows[0]
    assert row["channel"] == "email"
    assert row["category"] == "quotes"
    assert row["name"] == "Quote / Estimate"
    assert row["system"] is True
    assert row["active"] is True
    assert "QUOTE_LABEL" in (row["subject"] or "")
    assert "QUOTE_LINE_ITEMS_HTML" in (row["body"] or "")
    assert "ESTIMATE_LINK" in (row["body"] or "")
    assert row.get("body_version"), "body_version must be stamped on insert"


# ═══════════════════════════════════════════════════════════════════
# 2. Idempotency
# ═══════════════════════════════════════════════════════════════════
def test_seed_is_idempotent_on_rerun(dbc, tenant_cleanup):
    tids, _ = tenant_cleanup
    tid = _mk_tenant(dbc, tids)
    dbc.marketing_templates.delete_many(
        {"tenant_id": tid, "system_key": "quote_estimate_email"},
    )

    from services.migrations.seed_quote_estimate_template import seed_for_tenant
    r1 = asyncio.get_event_loop().run_until_complete(seed_for_tenant(tid))
    assert r1["inserted"] == 1
    count1 = dbc.marketing_templates.count_documents(
        {"tenant_id": tid, "system_key": "quote_estimate_email"},
    )
    assert count1 == 1

    r2 = asyncio.get_event_loop().run_until_complete(seed_for_tenant(tid))
    assert r2["inserted"] == 0
    assert r2["skipped_current"] == 1
    count2 = dbc.marketing_templates.count_documents(
        {"tenant_id": tid, "system_key": "quote_estimate_email"},
    )
    assert count2 == 1, (
        f"idempotency broken: re-seed added rows ({count1} → {count2})"
    )


# ═══════════════════════════════════════════════════════════════════
# 3. User edits preserved
# ═══════════════════════════════════════════════════════════════════
def test_seed_preserves_user_edits_on_rerun(dbc, tenant_cleanup):
    tids, _ = tenant_cleanup
    tid = _mk_tenant(dbc, tids)
    dbc.marketing_templates.delete_many(
        {"tenant_id": tid, "system_key": "quote_estimate_email"},
    )

    from services.migrations.seed_quote_estimate_template import seed_for_tenant
    asyncio.get_event_loop().run_until_complete(seed_for_tenant(tid))

    # Admin edits the body — drop body_version so the row looks
    # like a tenant-customized copy to the seeder.
    custom_body = "<p>MY CUSTOM BODY — don't trample me</p>"
    dbc.marketing_templates.update_one(
        {"tenant_id": tid, "system_key": "quote_estimate_email"},
        {"$set": {"body": custom_body, "body_version": None}},
    )
    pre = dbc.marketing_templates.find_one(
        {"tenant_id": tid, "system_key": "quote_estimate_email"}, {"_id": 0},
    )
    assert pre["body"] == custom_body

    # Re-seed — must NOT overwrite.
    r = asyncio.get_event_loop().run_until_complete(seed_for_tenant(tid))
    assert r["inserted"] == 0
    assert r["skipped_customized"] == 1, r

    post = dbc.marketing_templates.find_one(
        {"tenant_id": tid, "system_key": "quote_estimate_email"}, {"_id": 0},
    )
    assert post["body"] == custom_body, (
        "Seeder overwrote the admin's edited body — must preserve "
        "tenant customization."
    )


# ═══════════════════════════════════════════════════════════════════
# 4. List endpoint visibility
# ═══════════════════════════════════════════════════════════════════
def test_list_endpoint_returns_seeded_template(dbc, tenant_cleanup):
    tids, uids = tenant_cleanup
    tid = _mk_tenant(dbc, tids)
    email = _mk_admin(dbc, tid, uids)
    dbc.marketing_templates.delete_many(
        {"tenant_id": tid, "system_key": "quote_estimate_email"},
    )
    from services.migrations.seed_quote_estimate_template import seed_for_tenant
    asyncio.get_event_loop().run_until_complete(seed_for_tenant(tid))

    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": "password123"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    rr = requests.get(
        f"{API}/marketing/templates?channel=email&category=quotes",
        headers=headers, timeout=30,
    )
    assert rr.status_code == 200, rr.text
    data = rr.json()
    rows = data.get("templates") or data.get("items") or []
    # Exactly one row for this throwaway tenant.
    assert any(
        row.get("system_key") == "quote_estimate_email"
          and row.get("category") == "quotes"
          and row.get("channel") == "email"
          and row.get("name") == "Quote / Estimate"
        for row in rows
    ), f"seeded template not visible via list endpoint; got {rows}"


# ═══════════════════════════════════════════════════════════════════
# 5. End-to-end render with sample quote context
# ═══════════════════════════════════════════════════════════════════
def test_rendered_template_resolves_all_required_merge_tags():
    from services.marketing.merge_tags import render_template
    from services.migrations.seed_quote_estimate_template import _factory_doc

    doc = _factory_doc("render-smoke")

    ctx = {
        "customer": {"first_name": "Jamie", "last_name": "Rivera",
                       "email": "jamie@example.com"},
        "tenant": {"name": "AquaTerra Pools"},
        "company_name": "AquaTerra Pools",
        "quote_label": "Estimate",
        "quote_short_id": "A1B2C3D4",
        "quote_total": "$1,275.50",
        "estimate": {"public_url": "https://portal.example.com/e/estimate?t=xyz"},
        "quote": {
            "line_items": [
                {"description": "Weekly pool service — 4 weeks",
                 "quantity": 4, "unit_price": 150, "line_total": 600},
                {"description": "Equipment inspection",
                 "quantity": 1, "unit_price": 125, "line_total": 125},
                {"description": "Chlorine shock treatment",
                 "quantity": 3, "unit_price": 50, "line_total": 150},
            ],
            "subtotal": 875, "tax": 70, "total": 1275.50,
        },
    }

    subject, sub_missing = render_template(doc["subject"], ctx)
    body, body_missing = render_template(doc["body"], ctx)

    assert sub_missing == [], f"subject has unresolved tokens: {sub_missing}"
    assert body_missing == [], f"body has unresolved tokens: {body_missing}"

    # Subject assertions.
    assert "Estimate" in subject
    assert "AquaTerra Pools" in subject

    # Body assertions — every required merge tag resolved.
    assert "Jamie" in body, "CUSTOMER_FIRST_NAME did not resolve"
    assert "Estimate" in body, "QUOTE_LABEL did not resolve"
    assert "A1B2C3D4" in body, "QUOTE_SHORT_ID did not resolve"
    assert "$1,275.50" in body, "QUOTE_TOTAL did not resolve"
    assert "AquaTerra Pools" in body, "COMPANY_NAME did not resolve"

    # Line items — each description + each line total.
    for it in ctx["quote"]["line_items"]:
        assert it["description"] in body, (
            f"line-item description missing: {it['description']}"
        )
    assert "$600.00" in body and "$125.00" in body and "$150.00" in body, (
        "formatted line totals missing"
    )
    # Footer total via QUOTE_LINE_ITEMS_HTML.
    assert "$875.00" in body, "subtotal row missing"
    assert "$70.00" in body, "tax row missing"

    # CTA — portal URL must be inside the <a href="...">.
    assert 'href="https://portal.example.com/e/estimate?t=xyz"' in body, (
        "ESTIMATE_LINK portal URL missing from CTA <a href>"
    )
