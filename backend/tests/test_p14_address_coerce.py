"""Phase P14 · Feb-2026 · Item 1 — Address string coercion.

Unit tests for ``_coerce_address_to_str`` + integration tests
proving ``GET /api/jobs`` returns 200 with a coerced string
when Mongo has a dict-shaped ``address`` value.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from routers.jobs import _coerce_address_to_str


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")


# ── Unit tests on the helper ────────────────────────────────────────
class TestCoerceAddressToStr:
    def test_none_returns_empty(self):
        assert _coerce_address_to_str(None) == ""

    def test_bare_string_stripped(self):
        assert _coerce_address_to_str("  123 Main St  ") == "123 Main St"

    def test_empty_dict_returns_empty(self):
        assert _coerce_address_to_str({}) == ""

    def test_formatted_wins(self):
        d = {"formatted": "123 Main St, Phoenix, AZ 85001",
             "street": "wrong"}
        assert _coerce_address_to_str(d) == "123 Main St, Phoenix, AZ 85001"

    def test_full_wins_over_line1(self):
        d = {"full": "42 Palm Ln, Tucson, AZ", "line1": "42 Palm Ln"}
        assert _coerce_address_to_str(d) == "42 Palm Ln, Tucson, AZ"

    def test_concat_from_atomic_parts(self):
        d = {"street": "500 5th Ave", "city": "Scottsdale",
             "state": "AZ", "zip": "85251"}
        assert _coerce_address_to_str(d) == "500 5th Ave, Scottsdale, AZ 85251"

    def test_concat_postal_code_alias(self):
        d = {"street": "1 Elm", "city": "Mesa",
             "state": "AZ", "postal_code": "85201"}
        assert _coerce_address_to_str(d) == "1 Elm, Mesa, AZ 85201"

    def test_missing_state_zip_still_valid(self):
        d = {"street": "77 W Adams", "city": "Phoenix"}
        assert _coerce_address_to_str(d) == "77 W Adams, Phoenix"

    def test_only_street(self):
        assert _coerce_address_to_str({"street": "77 W Adams"}) == "77 W Adams"

    def test_line1_bare_falls_through_to_concat(self):
        # ``line1`` with NO comma → treated as street, we still
        # append city / state / zip from the atomic fields.
        d = {"line1": "77 W Adams", "city": "Phoenix",
             "state": "AZ", "zip": "85003"}
        assert _coerce_address_to_str(d) == "77 W Adams, Phoenix, AZ 85003"

    def test_non_dict_non_string_returns_empty(self):
        assert _coerce_address_to_str(12345) == ""
        assert _coerce_address_to_str(True) == ""
        assert _coerce_address_to_str([1, 2, 3]) == ""

    def test_whitespace_only_string_becomes_empty(self):
        assert _coerce_address_to_str("   \n  ") == ""

    def test_never_raises_on_weird_nested(self):
        # Nested dict INSIDE a value — should ignore that field
        # (not a string) and coerce cleanly.
        d = {"street": {"nested": "chaos"}, "city": "OK",
             "state": "AZ", "zip": "85001"}
        assert _coerce_address_to_str(d) == "OK, AZ 85001"


# ── Integration: GET /api/jobs with dict address ────────────────────
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_h() -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": "admin@aquaterra.com",
                              "password": "password123"},
                       timeout=15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def _cleanup(dbc):
    bag: list[str] = []
    yield bag
    for jid in bag:
        dbc.jobs.delete_one({"id": jid})


def test_p14_get_jobs_coerces_dict_address_field_without_crash(
    admin_h, dbc, _cleanup,
):
    """Seed a job whose ``address`` is a dict — the endpoint must
    return 200 and the ``address`` field on the wire must be a
    string. Pre-P14 the pydantic model rejected the dict shape
    and the whole list call crashed."""
    admin = dbc.users.find_one({"email": "admin@aquaterra.com"})
    tenant_id = admin["tenant_id"]
    jid = str(uuid.uuid4())
    dbc.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "title": "p14 · dict address regression",
        "status": "scheduled",
        "scheduled_date": "2028-05-05",
        "address": {"street": "42 Palm Ln", "city": "Phoenix",
                     "state": "AZ", "zip": "85001"},
    })
    _cleanup.append(jid)

    r = requests.get(
        f"{API}/jobs?scheduled_date=2028-05-05",
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 200, r.text[:300]
    row = next((j for j in r.json() if j.get("id") == jid), None)
    assert row is not None, "seeded job missing from response"
    assert isinstance(row.get("address"), str), (
        f"address must be a string on the wire, got "
        f"{type(row.get('address')).__name__}"
    )
    assert row["address"] == "42 Palm Ln, Phoenix, AZ 85001"


def test_p14_get_jobs_coerces_property_address_dict(admin_h, dbc, _cleanup):
    """Same coercion applies to ``property_address``."""
    admin = dbc.users.find_one({"email": "admin@aquaterra.com"})
    tenant_id = admin["tenant_id"]
    jid = str(uuid.uuid4())
    dbc.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "title": "p14 · property_address dict",
        "status": "scheduled",
        "scheduled_date": "2028-05-06",
        "address": "77 W Adams, Phoenix, AZ 85003",
        "property_address": {"formatted": "500 5th Ave, Scottsdale, AZ 85251"},
    })
    _cleanup.append(jid)
    r = requests.get(
        f"{API}/jobs?scheduled_date=2028-05-06",
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 200, r.text[:300]
    row = next((j for j in r.json() if j.get("id") == jid), None)
    assert row is not None
    assert isinstance(row.get("property_address"), str)
    assert row["property_address"] == "500 5th Ave, Scottsdale, AZ 85251"


def test_p14_string_address_untouched(admin_h, dbc, _cleanup):
    """Regression net — an already-string address round-trips
    unchanged. No stripping past what the helper would do to a
    bare string."""
    admin = dbc.users.find_one({"email": "admin@aquaterra.com"})
    tenant_id = admin["tenant_id"]
    jid = str(uuid.uuid4())
    dbc.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "title": "p14 · string address regression net",
        "status": "scheduled",
        "scheduled_date": "2028-05-07",
        "address": "9 Oak St, Chandler, AZ 85224",
    })
    _cleanup.append(jid)
    r = requests.get(
        f"{API}/jobs?scheduled_date=2028-05-07",
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 200, r.text[:300]
    row = next((j for j in r.json() if j.get("id") == jid), None)
    assert row is not None
    assert row["address"] == "9 Oak St, Chandler, AZ 85224"
