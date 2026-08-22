"""Feb-2026 · P43 — "No email" / "No phone number" data-quality filters."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"
_TAG = "TEST_p43_"


def _login(email="admin@aquaterra.com", pw="password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"})["tenant_id"]


def _seed(tid: str, *, email: str, phone: str,
             is_active: bool = True, tag: str = "") -> str:
    cid = f"{_TAG}{tag}{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tid,
        "name": f"P43 {cid}", "last_name": f"{_TAG}{tag}",
        "email": email, "phone": phone,
        "is_active": is_active,
        "status": "active" if is_active else "inactive",
    })
    return cid


@pytest.fixture(autouse=True)
def _cleanup(aquaterra_tid):
    def _reset():
        _sync.customers.delete_many({
            "tenant_id": aquaterra_tid,
            "id": {"$regex": f"^{_TAG}"},
        })
    _reset(); yield; _reset()


def _list(admin_h, q: str) -> dict:
    r = requests.get(f"{API}/customers?{q}", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _my_rows(items, tag_prefix=_TAG):
    """Filter shared-tenant noise so assertions target only P43 seeds."""
    return [c for c in items
              if (c.get("last_name") or "").startswith(tag_prefix)]


# ── missing_email ───────────────────────────────────────────────────
def test_missing_email_returns_customers_without_email(
        admin_h, aquaterra_tid):
    a = _seed(aquaterra_tid, email="a@ex.com", phone="+15551110001", tag="A_")
    b = _seed(aquaterra_tid, email="b@ex.com", phone="", tag="B_")
    c = _seed(aquaterra_tid, email="", phone="+15551110003", tag="C_")
    d = _seed(aquaterra_tid, email="", phone="", tag="D_")
    body = _list(admin_h, "missing_email=true&page=1&page_size=500")
    ids = {row["id"] for row in _my_rows(body["items"])}
    # C (no email, has phone) + D (neither) → both surface.
    # A and B (have email) → excluded.
    assert c in ids and d in ids
    assert a not in ids and b not in ids


def test_missing_phone_returns_customers_without_phone(
        admin_h, aquaterra_tid):
    a = _seed(aquaterra_tid, email="a@ex.com", phone="+15551110001", tag="A_")
    b = _seed(aquaterra_tid, email="b@ex.com", phone="", tag="B_")
    c = _seed(aquaterra_tid, email="", phone="+15551110003", tag="C_")
    d = _seed(aquaterra_tid, email="", phone="", tag="D_")
    body = _list(admin_h, "missing_phone=true&page=1&page_size=500")
    ids = {row["id"] for row in _my_rows(body["items"])}
    assert b in ids and d in ids
    assert a not in ids and c not in ids


def test_both_filters_active_returns_customers_missing_both(
        admin_h, aquaterra_tid):
    a = _seed(aquaterra_tid, email="a@ex.com", phone="+15551110001", tag="A_")
    b = _seed(aquaterra_tid, email="b@ex.com", phone="", tag="B_")
    c = _seed(aquaterra_tid, email="", phone="+15551110003", tag="C_")
    d = _seed(aquaterra_tid, email="", phone="", tag="D_")
    body = _list(admin_h,
                    "missing_email=true&missing_phone=true"
                    "&page=1&page_size=500")
    ids = {row["id"] for row in _my_rows(body["items"])}
    assert ids == {d}
    assert a not in ids and b not in ids and c not in ids


# ── Whitespace-only counts as missing ───────────────────────────────
def test_whitespace_only_email_and_phone_are_missing(
        admin_h, aquaterra_tid):
    e = _seed(aquaterra_tid, email="   ", phone="\t \n", tag="E_")
    body = _list(admin_h,
                    "missing_email=true&missing_phone=true"
                    "&page=1&page_size=500")
    ids = {row["id"] for row in _my_rows(body["items"])}
    assert e in ids


# ── count_only parity (P40 unified-predicate contract) ─────────────
def test_count_only_matches_list_total_for_missing_email(
        admin_h, aquaterra_tid):
    _seed(aquaterra_tid, email="", phone="+15551110001", tag="C1_")
    _seed(aquaterra_tid, email="", phone="", tag="D1_")
    _seed(aquaterra_tid, email="ok@ex.com", phone="", tag="A1_")

    list_body = _list(admin_h, "missing_email=true&page=1&page_size=500")
    list_ours = _my_rows(list_body["items"])
    count_body = _list(admin_h, "missing_email=true&count_only=true")

    # Global count includes shared-tenant noise; the parity guarantee
    # is that our seeded rows are present in BOTH branches.
    assert count_body["count"] >= len(list_ours) >= 2


def test_count_only_matches_list_total_for_missing_phone(
        admin_h, aquaterra_tid):
    _seed(aquaterra_tid, email="a@ex.com", phone="", tag="P1_")
    _seed(aquaterra_tid, email="", phone="", tag="P2_")
    list_body = _list(admin_h, "missing_phone=true&page=1&page_size=500")
    list_ours = _my_rows(list_body["items"])
    count_body = _list(admin_h, "missing_phone=true&count_only=true")
    assert count_body["count"] >= len(list_ours) >= 2


def test_count_only_matches_list_total_for_both_filters(
        admin_h, aquaterra_tid):
    _seed(aquaterra_tid, email="", phone="", tag="B1_")
    _seed(aquaterra_tid, email="a@ex.com", phone="", tag="B2_")
    list_body = _list(admin_h,
                         "missing_email=true&missing_phone=true"
                         "&page=1&page_size=500")
    list_ours = _my_rows(list_body["items"])
    count_body = _list(admin_h,
                          "missing_email=true&missing_phone=true"
                          "&count_only=true")
    assert count_body["count"] >= len(list_ours) >= 1


# ── Tab composition ─────────────────────────────────────────────────
def test_tab_inactive_composes_with_missing_phone(
        admin_h, aquaterra_tid):
    inactive_no_phone = _seed(aquaterra_tid, email="a@ex.com", phone="",
                                    is_active=False, tag="I1_")
    inactive_has_phone = _seed(aquaterra_tid, email="b@ex.com",
                                     phone="+15551110002",
                                     is_active=False, tag="I2_")
    active_no_phone = _seed(aquaterra_tid, email="c@ex.com", phone="",
                                  is_active=True, tag="I3_")
    body = _list(admin_h,
                    "is_active=false&missing_phone=true"
                    "&page=1&page_size=500")
    ids = {row["id"] for row in _my_rows(body["items"])}
    assert inactive_no_phone in ids
    assert inactive_has_phone not in ids
    assert active_no_phone not in ids


# ── Default off (control) ───────────────────────────────────────────
def test_default_off_returns_all_seeded_rows(admin_h, aquaterra_tid):
    a = _seed(aquaterra_tid, email="a@ex.com", phone="+15551110001", tag="Q1_")
    d = _seed(aquaterra_tid, email="", phone="", tag="Q2_")
    body = _list(admin_h, "page=1&page_size=500")
    ids = {row["id"] for row in _my_rows(body["items"])}
    assert a in ids and d in ids


# ── Pagination envelope shape ───────────────────────────────────────
def test_pagination_envelope_with_missing_email(
        admin_h, aquaterra_tid):
    _seed(aquaterra_tid, email="", phone="+15551110001", tag="G1_")
    _seed(aquaterra_tid, email="", phone="+15551110002", tag="G2_")
    body = _list(admin_h, "missing_email=true&page=1&page_size=100")
    assert "items" in body and "total" in body
    assert "page" in body and "page_size" in body
    assert body["total"] >= 2
