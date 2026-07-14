"""Phase 16B · Business OS tests — SOPs, roles, KPI scorecards, huddles,
Lana chat, plans catalog + assignment, tenant isolation.

Sync `requests` convention (matches existing suite)."""
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = (_FE_ENV.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = _BE_ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE_ENV.get("DB_NAME") or os.environ.get("DB_NAME")


def _login(email, password="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def super_h():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def sunbelt_admin_h():
    return {"Authorization": f"Bearer {_login('admin@sunbelt.com')}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


# ─── Seed sanity checks ───────────────────────────────────────────────────
def test_business_os_seeded(admin_h):
    """Every aquaterra admin should see 10 seeded SOPs, 8 roles, 3 leanboards."""
    sops = requests.get(f"{API}/sops", headers=admin_h, timeout=20).json()
    assert len(sops) >= 10
    roles = requests.get(f"{API}/role-definitions", headers=admin_h, timeout=20).json()
    assert len(roles) >= 8
    boards = requests.get(f"{API}/leanboards", headers=admin_h, timeout=20).json()
    assert len(boards) >= 3


# ─── SOP CRUD + tenant isolation ──────────────────────────────────────────
def test_sop_crud_and_tenant_isolation(admin_h, sunbelt_admin_h):
    payload = {"title": "TEST_ Isolation SOP", "category": "Pool",
               "content": "Step 1", "owner_role": "tech"}
    r = requests.post(f"{API}/sops", headers=admin_h, json=payload, timeout=20)
    assert r.status_code == 200
    sop_id = r.json()["id"]
    # aquaterra sees it
    r = requests.get(f"{API}/sops", headers=admin_h, timeout=20)
    assert any(s["id"] == sop_id for s in r.json())
    # sunbelt does NOT
    r = requests.get(f"{API}/sops", headers=sunbelt_admin_h, timeout=20)
    assert not any(s["id"] == sop_id for s in r.json())
    # cleanup
    requests.delete(f"{API}/sops/{sop_id}", headers=admin_h, timeout=20)


# ─── Roles CRUD ────────────────────────────────────────────────────────────
def test_role_definition_crud(admin_h):
    r = requests.post(f"{API}/role-definitions", headers=admin_h,
                      json={"title": "TEST_ Field Supervisor",
                            "responsibilities": ["QA weekly visits"],
                            "kpis": ["Callback rate"]},
                      timeout=20)
    assert r.status_code == 200
    rid = r.json()["id"]
    r = requests.put(f"{API}/role-definitions/{rid}", headers=admin_h,
                     json={"title": "TEST_ Field Supervisor (Updated)",
                           "responsibilities": ["QA", "Coach"],
                           "kpis": ["Callback rate", "CSAT"]},
                     timeout=20)
    assert r.status_code == 200
    assert "Updated" in r.json()["title"]
    requests.delete(f"{API}/role-definitions/{rid}", headers=admin_h, timeout=20)


# ─── KPI scorecards + auto-recompute ──────────────────────────────────────
def test_kpi_recompute_returns_actuals(admin_h, db):
    r = requests.post(f"{API}/business-os/kpis/recompute", headers=admin_h, timeout=20)
    assert r.status_code == 200
    payload = r.json()
    assert payload["ok"] is True
    assert "updated_scorecards" in payload
    assert "revenue_30d" in payload


# ─── Huddles ──────────────────────────────────────────────────────────────
def test_huddle_and_action_items_become_tasks(admin_h):
    today = datetime.now(timezone.utc).date().isoformat()
    # Create fresh huddle
    r = requests.post(f"{API}/huddles", headers=admin_h,
                      json={"date": today, "title": "TEST_ huddle"}, timeout=20)
    assert r.status_code == 200
    hid = r.json()["id"]
    # Add an action item
    r = requests.post(f"{API}/huddles/{hid}/action-items", headers=admin_h,
                      json={"huddle_id": hid, "text": "TEST_ ship SOP QA"},
                      timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body["action"]["text"] == "TEST_ ship SOP QA"
    assert body["task"]["id"]
    assert body["task"]["source"] == f"huddle:{hid}"


# ─── Lana chat happy path ─────────────────────────────────────────────────
def test_lana_chat_returns_reply_and_mocked_flag(admin_h):
    r = requests.post(f"{API}/business-os/lana/chat", headers=admin_h,
                      json={"message": "Give me 2 tenets of an EOS-style huddle in one line each."},
                      timeout=45)
    assert r.status_code == 200
    d = r.json()
    assert isinstance(d.get("mocked"), bool)
    assert isinstance(d.get("reply"), str) and len(d["reply"]) > 0
    assert d.get("conversation_id")


# ─── Plans catalog removed — pricing tier system deleted in Phase 16C add-on.
# The former `test_plans_catalog_and_assignment` test has been dropped.


# ─── LeanBoard card move (kanban integrity) ───────────────────────────────
def test_leanboard_card_create_and_move(admin_h):
    boards = requests.get(f"{API}/leanboards", headers=admin_h, timeout=20).json()
    board = boards[0]
    first_col = board["columns"][0]
    second_col = board["columns"][1]
    r = requests.post(f"{API}/leanboards/{board['id']}/cards", headers=admin_h,
                      json={"board_id": board["id"], "column": first_col,
                            "title": "TEST_ card"},
                      timeout=20)
    assert r.status_code == 200
    cid = r.json()["id"]
    r = requests.post(f"{API}/leanboards/cards/{cid}/move", headers=admin_h,
                      json={"column": second_col}, timeout=20)
    assert r.status_code == 200 and r.json()["column"] == second_col
    requests.delete(f"{API}/leanboards/cards/{cid}", headers=admin_h, timeout=20)
