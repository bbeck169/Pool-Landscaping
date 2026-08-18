"""Feb-2026 · POST /api/recurring-jobs · role gate + Nth-weekday payload.

Suite pins the widened role gate that lets managers create recurring
templates from the new-job form and the recurring-jobs admin page
(same helper ``require_admin_or_manager`` guards both surfaces).

Also asserts the exact wire shape the web form emits for the Nth-
weekday pattern (``monthly_pattern="nth_weekday"``, ``monthly_nth_week``
as string enum, ``monthly_weekday`` as int 0..6).
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import requests
from pymongo import MongoClient


BASE_URL = ""
for ln in Path("/app/frontend/.env").read_text().splitlines():
    if ln.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = ln.split("=", 1)[1].strip().strip('"').rstrip("/")
        break
API = f"{BASE_URL}/api"

AQUATERRA_TID = "3814833a-dd0d-4bd9-90ea-351c24924649"
CREDS = {
    "super":      {"email": "super@aquaterra.com",      "password": "password123"},
    "admin":      {"email": "admin@aquaterra.com",      "password": "password123"},
    "manager":    {"email": "manager@aquaterra.com",    "password": "password123"},
    "landscaper": {"email": "landscaper@aquaterra.com", "password": "password123"},
    "customer":   {"email": "alice@customer.demo",      "password": "password123"},
}


def _env(k: str) -> str:
    for ln in Path("/app/backend/.env").read_text().splitlines():
        if ln.startswith(f"{k}="):
            return ln.split("=", 1)[1].strip().strip('"')
    return ""


@pytest.fixture(scope="module")
def sync_db():
    cli = MongoClient(_env("MONGO_URL"), serverSelectionTimeoutMS=5000)
    try:
        yield cli[_env("DB_NAME") or "aquaterra"]
    finally:
        cli.close()


@pytest.fixture(autouse=True)
def _ensure_manager_seed(sync_db):
    """Seed ``manager@aquaterra.com`` if it isn't already present.

    The default demo seed doesn't include a manager account; the
    Feb-2026 recurrence widening exposes ``role=manager`` for the
    first time on Aquaterra, so this fixture provisions it lazily.
    """
    from bcrypt import hashpw, gensalt
    existing = sync_db.users.find_one({"email": "manager@aquaterra.com"})
    if not existing:
        sync_db.users.insert_one({
            "id": f"manager-{uuid4().hex[:8]}",
            "email": "manager@aquaterra.com",
            "name": "Aquaterra Manager",
            "role": "manager",
            "tenant_id": AQUATERRA_TID,
            "hashed_password": hashpw(b"password123", gensalt()).decode(),
            "active": True,
        })
    yield


def _login(email: str, password: str):
    try:
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
        r.raise_for_status()
        return r.json()["access_token"]
    except Exception:
        return None


def _post_tpl(token: str, extra: dict | None = None) -> requests.Response:
    payload = {
        "customer_id": "bug-repro-1",
        "service_type": "Weekly Pool",
        "frequency": "monthly",
        "monthly_pattern": "nth_weekday",
        "monthly_nth_week": "second",
        "monthly_weekday": 2,      # Wed (Mon=0…Sun=6)
        "start_date": "2026-02-01",
        "price_cents": 12000,
        "recurrence_never_ends": True,
        "active": True,
    }
    payload.update(extra or {})
    return requests.post(
        f"{API}/recurring-jobs", json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )


@pytest.fixture()
def cleanup_ids(sync_db):
    ids: list[str] = []
    yield ids
    if ids:
        sync_db.recurring_job_templates.delete_many({"id": {"$in": ids}})


def test_super_admin_accepted(sync_db, cleanup_ids):
    tok = _login(**CREDS["super"])
    r = _post_tpl(tok)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["monthly_pattern"] == "nth_weekday"
    assert body["monthly_nth_week"] == "second"
    assert body["monthly_weekday"] == 2
    cleanup_ids.append(body["id"])


def test_admin_accepted(sync_db, cleanup_ids):
    tok = _login(**CREDS["admin"])
    if not tok:
        pytest.skip("admin seed missing on this pod")
    r = _post_tpl(tok)
    assert r.status_code == 200, r.text
    cleanup_ids.append(r.json()["id"])


def test_manager_accepted(sync_db, cleanup_ids):
    tok = _login(**CREDS["manager"])
    assert tok, "manager fixture failed to seed / login"
    r = _post_tpl(tok)
    assert r.status_code == 200, r.text
    cleanup_ids.append(r.json()["id"])


def test_technician_rejected():
    tok = _login(**CREDS["landscaper"])
    r = _post_tpl(tok)
    assert r.status_code == 403, r.text


def test_int_nth_week_rejected(cleanup_ids):
    # Regression guard — tester previously confirmed 422 on int.
    tok = _login(**CREDS["super"])
    r = _post_tpl(tok, extra={"monthly_nth_week": 2})  # type: ignore[arg-type]
    assert r.status_code in (400, 422), r.text
