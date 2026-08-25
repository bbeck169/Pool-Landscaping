"""Regression: a soft-deleted account must never be issued a token.

Bug: ``POST /api/auth/login`` gated on ``active is False`` but not on
``deleted_at``, while ``get_current_user`` hard-401s ("account_deleted")
on ``deleted_at``. A soft-deleted user therefore got ``200 + token`` and
was then 401'd on every subsequent request. The mobile client wipes the
session on 401 (``registerLogoutOn401``), so signing in appeared to
succeed and then instantly bounced back to the login screen -- forever.

The gate now lives in ``utils.create_token`` so every token-issuing path
(login, signup, impersonate, revert-impersonation, portal auto-login) is
covered and cannot drift from ``get_current_user`` again.
"""
import uuid
import datetime

import pytest
import requests
from fastapi import HTTPException

from utils import create_token, hash_password

BASE = "http://localhost:8001/api"
T = 20
PW = "password123"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ---------------------------------------------------------------- unit level

def test_create_token_blocks_soft_deleted():
    user = {"id": "u1", "email": "d@example.com", "role": "technician",
            "deleted_at": _now()}
    with pytest.raises(HTTPException) as ei:
        create_token(user)
    assert ei.value.status_code == 401


def test_create_token_blocks_deactivated():
    user = {"id": "u2", "email": "i@example.com", "role": "technician",
            "active": False}
    with pytest.raises(HTTPException) as ei:
        create_token(user)
    assert ei.value.status_code == 403


def test_create_token_blocks_impersonating_a_deleted_customer():
    """The impersonation path calls create_token with an impersonator_id."""
    user = {"id": "u3", "email": "c@example.com", "role": "customer",
            "deleted_at": _now()}
    with pytest.raises(HTTPException) as ei:
        create_token(user, impersonator_id="admin-1")
    assert ei.value.status_code == 401


def test_create_token_allows_healthy_user():
    user = {"id": "u4", "email": "h@example.com", "role": "technician"}
    assert create_token(user).count(".") == 2


# ------------------------------------------------------------- http level

@pytest.fixture
def seeded_users():
    """Seed a soft-deleted and a healthy user; drop them afterwards."""
    import os
    import pymongo
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    cli = pymongo.MongoClient(os.environ["MONGO_URL"])
    db = cli[os.environ["DB_NAME"]]
    tag = uuid.uuid4().hex[:8]
    made = {}
    for label, extra in (("deleted", {"deleted_at": _now()}), ("healthy", {})):
        email = f"zz-{label}-{tag}@fixture-qa.com"
        doc = {"id": str(uuid.uuid4()), "email": email, "name": "Fixture",
               "role": "technician", "password_hash": hash_password(PW),
               "created_at": _now()}
        doc.update(extra)
        db.users.insert_one(doc)
        made[label] = email
    yield made
    db.users.delete_many({"email": {"$in": list(made.values())}})
    cli.close()


def _login(email):
    return requests.post(f"{BASE}/auth/login",
                         json={"email": email, "password": PW}, timeout=T)


def test_soft_deleted_login_is_rejected_outright(seeded_users):
    r = _login(seeded_users["deleted"])
    assert r.status_code == 401, r.text
    assert "access_token" not in r.json()


def test_healthy_login_still_works_end_to_end(seeded_users):
    r = _login(seeded_users["healthy"])
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    me = requests.get(f"{BASE}/auth/me",
                      headers={"Authorization": f"Bearer {token}"}, timeout=T)
    assert me.status_code == 200, me.text
