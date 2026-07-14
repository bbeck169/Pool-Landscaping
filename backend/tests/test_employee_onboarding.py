"""Phase 20B.2 — Employee onboarding templates + assignments."""
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc(): return MongoClient(MONGO_URL)[DB_NAME]

@pytest.fixture(scope="module")
def admin_h(): return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def tech_h(): return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}


def test_default_template_seeded_on_list(admin_h, dbc):
    r = requests.get(f"{API}/onboarding/templates", headers=admin_h, timeout=15).json()
    tech_defaults = [t for t in r if t.get("role") == "technician" and t.get("is_default")]
    assert len(tech_defaults) >= 1
    steps = tech_defaults[0]["steps"]
    kinds = {s["kind"] for s in steps}
    assert {"doc_upload", "video", "quiz", "policy_ack"}.issubset(kinds)


def test_template_crud(admin_h, dbc):
    body = {
        "role": "marketing", "title": "Marketing onboarding TEST",
        "steps": [
            {"title": "Read style guide", "kind": "task"},
            {"title": "Sign NDA", "kind": "doc_upload"},
        ],
    }
    r = requests.post(f"{API}/onboarding/templates", headers=admin_h,
                      json=body, timeout=15).json()
    tid = r["id"]
    upd = requests.put(f"{API}/onboarding/templates/{tid}", headers=admin_h,
                       json={"title": "Marketing onboarding TEST v2"}, timeout=15).json()
    assert upd["title"] == "Marketing onboarding TEST v2"
    d = requests.delete(f"{API}/onboarding/templates/{tid}", headers=admin_h, timeout=15)
    assert d.status_code == 200


def test_assign_and_complete_flow_transitions_status(admin_h, tech_h, dbc):
    # Grab or create a template with 2 quick steps
    body = {
        "role": "technician", "title": "Quick TEST",
        "steps": [
            {"title": "Read manual", "kind": "task"},
            {"title": "Ack policy", "kind": "policy_ack"},
        ],
    }
    tmpl = requests.post(f"{API}/onboarding/templates", headers=admin_h,
                        json=body, timeout=15).json()
    mike = dbc.users.find_one({"email": "mike@aquaterra.com"})
    a = requests.post(f"{API}/onboarding/assignments", headers=admin_h,
                     json={"user_id": mike["id"], "template_id": tmpl["id"]},
                     timeout=15).json()
    aid = a["id"]
    assert a["status"] == "not_started"

    # Tech completes step 1 (via own token) → in_progress
    s1 = tmpl["steps"][0]["id"]
    r1 = requests.post(
        f"{API}/onboarding/assignments/{aid}/steps/{s1}/complete",
        headers=tech_h, timeout=15,
    ).json()
    assert r1["status"] == "in_progress"

    # Complete step 2 → complete
    s2 = tmpl["steps"][1]["id"]
    r2 = requests.post(
        f"{API}/onboarding/assignments/{aid}/steps/{s2}/complete",
        headers=tech_h, timeout=15,
    ).json()
    assert r2["status"] == "complete"
    assert r2["completed_at"] is not None

    # My assignments endpoint (tech-authed) returns own.
    mine = requests.get(f"{API}/onboarding/assignments/mine",
                        headers=tech_h, timeout=15).json()
    assert any(x["id"] == aid for x in mine)

    # Cleanup
    dbc.onboarding_assignments.delete_one({"id": aid})
    requests.delete(f"{API}/onboarding/templates/{tmpl['id']}",
                    headers=admin_h, timeout=15)


def test_quiz_scoring_gate_at_80pct(admin_h, tech_h, dbc):
    body = {
        "role": "technician", "title": "Quiz TEST",
        "steps": [
            {"title": "Chem quiz", "kind": "quiz",
             "quiz_questions": [
                 {"q": "1", "choices": ["a", "b"], "correct_index": 1},
                 {"q": "2", "choices": ["a", "b"], "correct_index": 1},
                 {"q": "3", "choices": ["a", "b"], "correct_index": 1},
             ]},
        ],
    }
    tmpl = requests.post(f"{API}/onboarding/templates", headers=admin_h,
                        json=body, timeout=15).json()
    mike = dbc.users.find_one({"email": "mike@aquaterra.com"})
    a = requests.post(f"{API}/onboarding/assignments", headers=admin_h,
                     json={"user_id": mike["id"], "template_id": tmpl["id"]},
                     timeout=15).json()
    sid = tmpl["steps"][0]["id"]

    # 1/3 → fails
    r = requests.post(f"{API}/onboarding/assignments/{a['id']}/steps/{sid}/quiz",
                     headers=tech_h, json={"answers": [1, 0, 0]}, timeout=15).json()
    assert r["passed"] is False

    # 3/3 → passes, assignment goes complete
    r = requests.post(f"{API}/onboarding/assignments/{a['id']}/steps/{sid}/quiz",
                     headers=tech_h, json={"answers": [1, 1, 1]}, timeout=15).json()
    assert r["passed"] is True and r["score"] == 100

    dbc.onboarding_assignments.delete_one({"id": a["id"]})
    requests.delete(f"{API}/onboarding/templates/{tmpl['id']}",
                    headers=admin_h, timeout=15)
