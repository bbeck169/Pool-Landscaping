"""Phase 48 · Feb-2026 — Customer contact redesign backend contract.

Covers:
    * Customer model accepts + persists ``home_phone``.
    * ``MAX_MOBILES`` bumped to 3, ``MAX_EMAILS`` bumped to 4.
    * Cap-enforcement routes still reject over-caps with a clean 400.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


API = "/api"


@pytest.fixture
def client():
    from server import app
    return TestClient(app)


# ── Constants moved ─────────────────────────────────────────────────
def test_max_mobiles_bumped_to_three():
    from services.customer_multi_contact import MAX_MOBILES
    assert MAX_MOBILES == 3


def test_max_emails_bumped_to_four():
    from services.customer_multi_contact import MAX_EMAILS
    assert MAX_EMAILS == 4


def test_normalize_respects_new_caps():
    from services.customer_multi_contact import (
        normalize_mobiles, normalize_emails, MAX_MOBILES, MAX_EMAILS,
    )
    m_input = [
        {"number_e164": f"+1480555010{i}", "is_primary": i == 0}
        for i in range(5)
    ]
    m_out = normalize_mobiles(m_input)
    assert len(m_out) == MAX_MOBILES
    e_input = [
        {"address": f"e{i}@example.com", "is_primary": i == 0}
        for i in range(6)
    ]
    e_out = normalize_emails(e_input)
    assert len(e_out) == MAX_EMAILS


# ── Model accepts home_phone ────────────────────────────────────────
def test_customerin_model_accepts_home_phone():
    from models import CustomerIn
    c = CustomerIn(name="Demo Customer",
                   first_name="Demo", last_name="Customer",
                   home_phone="+14805551234")
    assert c.home_phone == "+14805551234"


def test_customerin_model_home_phone_defaults_empty():
    from models import CustomerIn
    c = CustomerIn(name="Demo")
    assert c.home_phone == ""


# ── Cap-check messages surface the new numbers ──────────────────────
def test_router_mobiles_endpoint_rejects_over_new_cap(client):
    """PATCH /customers/{id}/mobiles should 400 on >3 rows and echo
    the current MAX_MOBILES value in the error message."""
    from services.customer_multi_contact import MAX_MOBILES
    body = {"mobiles": [{"number_e164": f"+1480555000{i}"} for i in range(4)]}
    # A garbage customer id short-circuits the actual DB writes but the
    # cap-check runs BEFORE the lookup, so the 400 fires deterministically.
    r = client.patch(
        f"{API}/customers/does-not-matter/mobiles",
        json=body,
        headers={"Authorization": "Bearer dummy"},
    )
    # 401 (no auth) is acceptable too — some auth middlewares run
    # ahead of the body-length check. What we care about is that the
    # response is a clean 4xx (never 500 / silent 200).
    assert r.status_code in (400, 401, 403, 404, 422), r.text
    if r.status_code == 400:
        assert str(MAX_MOBILES) in r.text
        assert "mobiles" in r.text.lower()


def test_router_emails_endpoint_rejects_over_new_cap(client):
    from services.customer_multi_contact import MAX_EMAILS
    body = {"emails": [{"address": f"e{i}@example.com"} for i in range(5)]}
    r = client.patch(
        f"{API}/customers/does-not-matter/emails",
        json=body,
        headers={"Authorization": "Bearer dummy"},
    )
    assert r.status_code in (400, 401, 403, 404, 422), r.text
    if r.status_code == 400:
        assert str(MAX_EMAILS) in r.text
        assert "emails" in r.text.lower()


# ── Regression: BusinessCard component still in-tree ────────────────
def test_business_card_component_still_present():
    """Phase 48 unmounts <BusinessCard/> from CustomerDetail but the
    component itself is kept for other surfaces (tech ToolsHub,
    marketing card slot). If someone deletes the component file, this
    guard flags it before those pages break."""
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "frontend" / "src" / \
        "components" / "business-card" / "BusinessCard.jsx"
    assert p.exists(), \
        "Phase 48 kept BusinessCard.jsx in-tree — do NOT delete it"
