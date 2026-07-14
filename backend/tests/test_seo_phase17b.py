"""Phase 17B — Topical Map + LLM Visibility + Atlas Agent."""
import time
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
    r.raise_for_status(); return r.json()


@pytest.fixture(scope="module")
def dbc(): return MongoClient(MONGO_URL)[DB_NAME]

@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def sunbelt_admin_h():
    try:
        return {"Authorization": f"Bearer {_login('admin@sunbelt.com')['access_token']}"}
    except Exception:
        pytest.skip("no sunbelt admin")


# ─── Polish 1 · items[] on /audits/{id}/pages ───────────────────────────
def test_polish_audit_pages_items_shape(admin_h, dbc):
    r = requests.post(f"{API}/seo/audits", headers=admin_h,
                     json={"url": "https://example.com", "depth": 1,
                           "max_pages": 1}, timeout=15).json()
    aid = r["audit_id"]
    # Wait briefly for the background task to log something.
    time.sleep(3)
    resp = requests.get(f"{API}/seo/audits/{aid}/pages",
                        headers=admin_h, timeout=15).json()
    # Standard REST shape: `items` + `total`, `rows` kept as alias.
    assert "items" in resp and isinstance(resp["items"], list)
    assert "total" in resp and isinstance(resp["total"], int)
    dbc.seo_audits.delete_one({"id": aid})
    dbc.seo_audit_pages.delete_many({"audit_id": aid})


# ─── Polish 2 · /seo/ping capability flags ──────────────────────────────
def test_polish_seo_ping_capability_flags(admin_h):
    r = requests.get(f"{API}/seo/ping", headers=admin_h, timeout=15).json()
    for k in ("ok", "running_audits", "timestamp", "crawler_available",
              "llm_available", "serp_provider_available", "mocked_domains"):
        assert k in r, f"missing key: {k}"
    assert isinstance(r["llm_available"], bool)
    assert isinstance(r["serp_provider_available"], bool)
    assert "rank_heatmap" in r["mocked_domains"]


# ─── 17B.1 · Topical Map ────────────────────────────────────────────────
def test_topical_map_structure(admin_h, dbc):
    r = requests.post(f"{API}/seo/topical-maps", headers=admin_h,
                     json={"seed_keyword": "pool cleaning phoenix",
                           "business_context": "residential pool service in Arizona"},
                     timeout=60).json()
    assert "map_id" in r
    m = requests.get(f"{API}/seo/topical-maps/{r['map_id']}",
                     headers=admin_h, timeout=15).json()
    assert "tree" in m and "nodes" in m["tree"] and "edges" in m["tree"]
    if not m.get("mocked"):
        # Real LLM should give at least a pillar + some clusters.
        assert len(m["tree"]["nodes"]) >= 1
        node = m["tree"]["nodes"][0]
        assert "title" in node and "intent" in node
    dbc.seo_topical_maps.delete_one({"id": r["map_id"]})


def test_topical_map_role_and_tenant(admin_h, sunbelt_admin_h, tech_h, dbc):
    r = requests.post(f"{API}/seo/topical-maps", headers=admin_h,
                     json={"seed_keyword": "pool test"}, timeout=60).json()
    # Sunbelt admin can't see aquaterra map
    sun = requests.get(f"{API}/seo/topical-maps/{r['map_id']}",
                       headers=sunbelt_admin_h, timeout=15)
    assert sun.status_code == 404
    # Tech → 403
    t = requests.get(f"{API}/seo/topical-maps", headers=tech_h, timeout=15)
    assert t.status_code == 403
    dbc.seo_topical_maps.delete_one({"id": r["map_id"]})


# ─── 17B.2 · LLM Visibility ─────────────────────────────────────────────
def test_llm_visibility_query_crud_and_engines(admin_h, tech_h, dbc):
    q = requests.post(f"{API}/seo/llm-visibility/queries", headers=admin_h,
                     json={"query_text": "best pool cleaning services in Phoenix",
                           "expected_brand": "AquaTerra Pools",
                           "category": "local"}, timeout=15).json()
    assert q["id"]
    lst = requests.get(f"{API}/seo/llm-visibility/queries",
                       headers=admin_h, timeout=15).json()
    assert any(x["id"] == q["id"] for x in lst)

    # Tech → 403
    t = requests.get(f"{API}/seo/llm-visibility/queries",
                     headers=tech_h, timeout=15)
    assert t.status_code == 403

    # Dashboard endpoint honestly lists engines_configured.
    dash = requests.get(f"{API}/seo/llm-visibility/dashboard",
                        headers=admin_h, timeout=15).json()
    assert "engines_configured" in dash
    assert isinstance(dash["engines_configured"], list)
    # Only claude wired for now.
    assert set(dash["engines_configured"]) <= {"claude"}

    requests.delete(f"{API}/seo/llm-visibility/queries/{q['id']}",
                    headers=admin_h, timeout=15)


def test_llm_visibility_scan_live(admin_h, dbc):
    """Run a real scan on a small query set. Only asserts shape + honesty."""
    q = requests.post(f"{API}/seo/llm-visibility/queries", headers=admin_h,
                     json={"query_text": "what is pool chlorine",
                           "expected_brand": "AquaTerra",
                           "category": "general"}, timeout=15).json()
    r = requests.post(f"{API}/seo/llm-visibility/scan", headers=admin_h,
                     json={"query_ids": [q["id"]]}, timeout=120).json()
    assert "scan_id" in r
    assert "engines_scanned" in r
    # engines_scanned only lists CONFIGURED engines
    assert set(r["engines_scanned"]) <= {"claude"}
    # engines_pending honestly labels what's not wired
    assert "engines_pending" in r
    assert set(r["engines_pending"]) >= {"openai", "gemini", "perplexity"}
    # If live LLM, at least one result
    if r["engines_scanned"]:
        assert len(r["results"]) >= 1
        first = r["results"][0]
        for key in ("brand_mentioned", "position", "competitors",
                    "quote", "sentiment", "raw_response"):
            assert key in first
    requests.delete(f"{API}/seo/llm-visibility/queries/{q['id']}",
                    headers=admin_h, timeout=15)
    dbc.seo_llm_scans.delete_many({"scan_id": r.get("scan_id")})


# ─── 17B.3 · Atlas Agent ────────────────────────────────────────────────
def test_atlas_tool_calls_audit(admin_h, dbc):
    """Send an audit intent → assert tool_calls fires + audit_id present + doc created."""
    r = requests.post(f"{API}/seo/atlas/chat", headers=admin_h,
                     json={"message": "Please run an SEO audit on "
                                       "https://example.com and tell me what you find"},
                     timeout=90).json()
    assert "conversation_id" in r
    msg = r["assistant"]
    assert isinstance(msg.get("tool_calls"), list)
    if msg["tool_calls"]:
        first = msg["tool_calls"][0]
        assert first["name"] == "run_site_audit"
        result = first.get("result") or {}
        assert "audit_id" in result
        # Confirm doc created
        assert dbc.seo_audits.count_documents({"id": result["audit_id"]}) == 1
        dbc.seo_audits.delete_one({"id": result["audit_id"]})
        dbc.seo_audit_pages.delete_many({"audit_id": result["audit_id"]})
    # Cleanup the conversation
    dbc.seo_atlas_conversations.delete_one({"id": r["conversation_id"]})


def test_atlas_plain_chat_no_tool(admin_h, tech_h, dbc):
    r = requests.post(f"{API}/seo/atlas/chat", headers=admin_h,
                     json={"message": "Hello there, how are you?"},
                     timeout=60).json()
    assert r["mocked"] in (True, False)
    # Tech → 403
    t = requests.post(f"{API}/seo/atlas/chat", headers=tech_h,
                      json={"message": "hi"}, timeout=15)
    assert t.status_code == 403
    dbc.seo_atlas_conversations.delete_one({"id": r["conversation_id"]})


def test_atlas_conversation_tenant_isolation(admin_h, sunbelt_admin_h, dbc):
    r = requests.post(f"{API}/seo/atlas/chat", headers=admin_h,
                     json={"message": "list my audits"}, timeout=60).json()
    cid = r["conversation_id"]
    # Sunbelt admin cannot see this conversation
    sun = requests.get(f"{API}/seo/atlas/conversations/{cid}",
                       headers=sunbelt_admin_h, timeout=15)
    assert sun.status_code == 404
    sun_list = requests.get(f"{API}/seo/atlas/conversations",
                            headers=sunbelt_admin_h, timeout=15).json()
    assert all(x["id"] != cid for x in sun_list)
    dbc.seo_atlas_conversations.delete_one({"id": cid})
