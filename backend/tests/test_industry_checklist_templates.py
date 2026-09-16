"""Phase MI1 · Feb 2026 — Multi-industry checklist template tests.

Covers:
  * Resolver returns tenant override when present, default otherwise.
  * PUT creates + updates an override (idempotent write).
  * DELETE clears the override; subsequent GET returns the default.
  * Role guard: non-admin PUT / DELETE → 403.
  * Seeder runs twice → 7 rows exist once (6 new + Pool), not duplicated.
  * Gate: submitting a landscaping report with a required item unchecked
    → 400 naming the missing item.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._phase34_http_shim import http

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


from tests._phase34_asyncio import batch_safe_run as _run


def _login(email: str, pw: str = "password123") -> str:
    r = http.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def db():
    from config import db as _db
    return _db


@pytest.fixture(scope="module")
def tid(db):
    async def _go():
        t = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
        return t["id"]
    return _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# Seeder — idempotent
# ═══════════════════════════════════════════════════════════════════════
def test_seeder_populates_seven_industry_defaults(db):
    """First run inserts up to 7 (pool + 6 new). Second run inserts 0.
    Regardless of the count on the first run, the collection carries
    exactly one ``is_default=True`` row per canonical industry when
    both invocations complete."""
    from routers.industry_checklists import (
        INDUSTRY_SLUGS, seed_industry_checklist_templates,
    )
    first = _run(seed_industry_checklist_templates())
    second = _run(seed_industry_checklist_templates())
    assert second["inserted"] == 0, (
        "seed is not idempotent — second call inserted "
        f"{second['inserted']} rows"
    )
    # After the two runs, one default row per slug must exist.
    for slug in INDUSTRY_SLUGS:
        docs = _run(db.industry_checklist_templates.find(
            {"industry": slug, "is_default": True}, {"_id": 0, "id": 1},
        ).to_list(10))
        assert len(docs) == 1, (
            f"industry={slug} → expected 1 default row, got {len(docs)}"
        )


# ═══════════════════════════════════════════════════════════════════════
# GET resolver — override wins over default
# ═══════════════════════════════════════════════════════════════════════
def test_get_returns_default_when_no_override(super_headers):
    r = http.get(f"{API}/checklists/industry/landscaping",
                     headers=super_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["industry"] == "landscaping"
    assert body["source"] == "default"
    keys = {i["key"] for i in body["items"]}
    assert "mowed_lawn_areas" in keys
    assert "edged_walkways_driveways" in keys


def test_get_accepts_alias_slugs(super_headers):
    """``pools`` should normalise to ``pool``."""
    r = http.get(f"{API}/checklists/industry/pools",
                     headers=super_headers, timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["industry"] == "pool"


def test_get_unknown_industry_rejected(super_headers):
    r = http.get(f"{API}/checklists/industry/rockets",
                     headers=super_headers, timeout=30)
    assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════════════
# PUT — create + update override
# ═══════════════════════════════════════════════════════════════════════
def test_put_creates_then_updates_override(db, super_headers, tid):
    # Clean state for the test tenant.
    _run(db.tenant_checklist_overrides.delete_many(
        {"tenant_id": tid, "industry": "hvac"},
    ))
    items = [
        {"key": "replaced_air_filter", "label": "Replaced air filter", "required": True},
        {"key": "custom_row", "label": "Tenant-specific step", "required": False},
    ]
    r1 = http.put(f"{API}/checklists/industry/hvac",
                        headers=super_headers, json={"items": items},
                        timeout=30)
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["source"] == "override"
    assert body1["items"][1]["label"] == "Tenant-specific step"

    # Second call — flip the required flag on the first item. Same
    # tenant + industry → idempotent update, not a duplicate row.
    items[0]["required"] = False
    r2 = http.put(f"{API}/checklists/industry/hvac",
                        headers=super_headers, json={"items": items},
                        timeout=30)
    assert r2.status_code == 200, r2.text
    assert r2.json()["items"][0]["required"] is False
    rows = _run(db.tenant_checklist_overrides.find(
        {"tenant_id": tid, "industry": "hvac"}, {"_id": 0, "id": 1},
    ).to_list(10))
    assert len(rows) == 1, f"expected 1 override row, got {len(rows)}"


def test_put_rejects_empty_items(super_headers):
    r = http.put(f"{API}/checklists/industry/hvac",
                       headers=super_headers, json={"items": []},
                       timeout=30)
    assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════════════
# DELETE — clears override; subsequent GET returns default
# ═══════════════════════════════════════════════════════════════════════
def test_delete_reverts_to_default(db, super_headers, tid):
    # Seed an override first.
    _run(db.tenant_checklist_overrides.replace_one(
        {"tenant_id": tid, "industry": "solar"},
        {"id": uuid.uuid4().hex, "tenant_id": tid, "industry": "solar",
         "items": [{"key": "x", "label": "X", "required": True}],
         "created_at": "2026-02-15T00:00:00Z",
         "updated_at": "2026-02-15T00:00:00Z"},
        upsert=True,
    ))
    r_del = http.delete(f"{API}/checklists/industry/solar",
                             headers=super_headers, timeout=30)
    assert r_del.status_code == 200, r_del.text
    assert r_del.json()["source"] == "default"
    # Follow-up GET returns default.
    r_get = http.get(f"{API}/checklists/industry/solar",
                          headers=super_headers, timeout=30)
    assert r_get.status_code == 200
    assert r_get.json()["source"] == "default"


# ═══════════════════════════════════════════════════════════════════════
# Role gate
# ═══════════════════════════════════════════════════════════════════════
def test_customer_role_rejected_on_put(customer_headers):
    r = http.put(f"{API}/checklists/industry/hvac",
                       headers=customer_headers,
                       json={"items": [{"key": "x", "label": "X"}]},
                       timeout=30)
    assert r.status_code in (401, 403)


def test_customer_role_rejected_on_delete(customer_headers):
    r = http.delete(f"{API}/checklists/industry/hvac",
                         headers=customer_headers, timeout=30)
    assert r.status_code in (401, 403)


def test_admin_role_allowed_on_put(admin_headers):
    r = http.put(f"{API}/checklists/industry/pest_control",
                       headers=admin_headers,
                       json={"items": [
                           {"key": "treated_exterior_perimeter",
                            "label": "Treated exterior perimeter",
                            "required": True},
                       ]}, timeout=30)
    assert r.status_code == 200, r.text


# ═══════════════════════════════════════════════════════════════════════
# Required-items gate
# ═══════════════════════════════════════════════════════════════════════
def test_gate_raises_when_required_item_missing():
    from routers.industry_checklists import (
        assert_required_items_present, DEFAULT_TEMPLATES,
    )
    resolved = {"industry": "landscaping",
                "items": DEFAULT_TEMPLATES["landscaping"]}
    # Miss "Cleared debris" (required) → should raise 400 naming it.
    completed = ["mowed_lawn_areas", "edged_walkways_driveways",
                 "blew_off_hardscape"]
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        assert_required_items_present("landscaping", completed, resolved)
    assert exc.value.status_code == 400
    assert "Cleared debris" in str(exc.value.detail)


def test_gate_passes_when_all_required_completed():
    from routers.industry_checklists import (
        assert_required_items_present, DEFAULT_TEMPLATES,
    )
    resolved = {"industry": "landscaping",
                "items": DEFAULT_TEMPLATES["landscaping"]}
    completed = [it["key"] for it in resolved["items"] if it["required"]]
    # Should NOT raise.
    assert_required_items_present("landscaping", completed, resolved)


def test_gate_accepts_label_or_key():
    """Legacy callers persist ``checklist_completed`` rows as
    ``{"label": ..., "done": True}`` (no ``key``). The gate must
    match on label too."""
    from routers.industry_checklists import (
        assert_required_items_present, DEFAULT_TEMPLATES,
    )
    resolved = {"industry": "cleaning",
                "items": DEFAULT_TEMPLATES["cleaning"]}
    completed = [it["label"] for it in resolved["items"] if it["required"]]
    assert_required_items_present("cleaning", completed, resolved)


def test_gate_is_noop_for_pool():
    """Pool jobs must never route through the required-items gate —
    the chemistry gate covers pool completions."""
    from routers.industry_checklists import (
        assert_required_items_present, DEFAULT_TEMPLATES,
    )
    resolved = {"industry": "pool",
                "items": DEFAULT_TEMPLATES["pool"]}
    # Empty ``completed`` list is fine for pool — gate short-circuits.
    assert_required_items_present("pool", [], resolved)


def test_derive_industry_for_job_service_type_keyword():
    from routers.industry_checklists import derive_industry_for_job
    assert derive_industry_for_job(
        {"service_type": "HVAC Tune-Up"}, None) == "hvac"
    assert derive_industry_for_job(
        {"service_type": "Solar Panel Cleaning"}, None) == "solar"
    assert derive_industry_for_job(
        {"service_type": "Landscape maintenance"}, None) == "landscaping"
    # Fallback → pool.
    assert derive_industry_for_job(
        {"service_type": "Weekly service"},
        {"industries": ["pools"]}) == "pool"
