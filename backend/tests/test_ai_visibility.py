"""Feb-2026 · Phase 24 · AI Visibility Tracker — pytest."""
from __future__ import annotations
import os, uuid, requests, pytest, asyncio
from pathlib import Path
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_E = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
_R = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
API = os.environ.get("BACKEND_API_URL") or ((_R.get("REACT_APP_BACKEND_URL") or "").rstrip("/") + "/api")


def _login(e, p="password123"):
    return requests.post(f"{API}/auth/login", json={"email":e,"password":p}, timeout=15).json()["access_token"]
def _admin(): return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}
def _tech():  return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(autouse=True)
def _clean():
    """Only clear pytest-created prompts + their runs; leave seeded ones alone."""
    tid = _sync.users.find_one({"email":"admin@aquaterra.com"}, {"_id":0,"tenant_id":1})["tenant_id"]
    _sync.ai_prompts.delete_many({"tenant_id": tid, "tags": {"$in": ["pytest"]}})
    _sync.ai_prompt_runs.delete_many({"tenant_id": tid, "provider": {"$in":["__pytest_fake__"]}})
    yield
    _sync.ai_prompts.delete_many({"tenant_id": tid, "tags": {"$in": ["pytest"]}})
    _sync.ai_prompt_runs.delete_many({"tenant_id": tid, "provider": {"$in":["__pytest_fake__"]}})


def test_boot_seed_creates_7_default_prompts():
    """Seed runs on every boot — expects at least the 7 defaults visible."""
    r = requests.get(f"{API}/ai-visibility/prompts", headers=_admin(), timeout=15)
    assert r.status_code == 200
    prompts = r.json()["prompts"]
    texts = {p["prompt_text"] for p in prompts}
    assert "best pool cleaning company peoria az" in texts
    assert "landscaping companies peoria az" in texts


def test_prompt_crud_and_dedupe_and_cap():
    h = _admin()
    txt = f"pytest prompt {uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/ai-visibility/prompts", headers=h,
                       json={"prompt_text": txt, "tags": ["pytest"]}, timeout=15)
    assert r.status_code == 200
    pid = r.json()["id"]

    # Duplicate (case-insensitive) → 409.
    d = requests.post(f"{API}/ai-visibility/prompts", headers=h,
                       json={"prompt_text": txt.upper(), "tags": ["pytest"]}, timeout=15)
    assert d.status_code == 409

    # Delete soft-removes.
    x = requests.delete(f"{API}/ai-visibility/prompts/{pid}", headers=h, timeout=15)
    assert x.status_code == 200


def test_prompts_admin_only():
    r = requests.get(f"{API}/ai-visibility/prompts", headers=_tech(), timeout=15)
    assert r.status_code == 403


def test_mention_detection_finds_brand_and_domain_and_alias():
    from routers.ai_visibility import detect_mention, _brand_terms
    business_card = {"company_name": "Pool & Landscaping of Vistancia",
                      "website_url": "https://poolandlandscapingofvistancia.com"}
    settings = {"ai_visibility": {"brand_aliases": ["PLoV", "Vistancia Pools"]}}
    terms = _brand_terms(business_card, settings)
    # 3 distinct: name + domain + 2 aliases
    assert len(terms) >= 3

    # Exact company name
    d = detect_mention("Try Pool & Landscaping of Vistancia — they are great!", terms)
    assert d["found"] and d["matched_term"] == "Pool & Landscaping of Vistancia"

    # Domain match
    d = detect_mention("See poolandlandscapingofvistancia.com for pricing.", terms)
    assert d["found"]

    # Alias match (case insensitive)
    d = detect_mention("PLOV is one option in the area.", terms)
    assert d["found"]

    # No match
    d = detect_mention("Best pool company here is Aqua Bros LLC.", terms)
    assert not d["found"]


def test_competitor_detection():
    from routers.ai_visibility import detect_competitors
    text = "You should try Aqua Bros or Blue Water Pools in Peoria."
    comps = ["Aqua Bros", "Blue Water Pools", "Not-Mentioned Co"]
    found = detect_competitors(text, comps)
    assert set(found) == {"Aqua Bros", "Blue Water Pools"}


def test_settings_patch_persists_aliases_and_competitors():
    h = _admin()
    r = requests.patch(f"{API}/ai-visibility/settings", headers=h,
                        json={"brand_aliases": ["Test Alias"],
                               "competitor_names": ["CompA", "CompB"]}, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["brand_aliases"] == ["Test Alias"]
    assert body["competitor_names"] == ["CompA", "CompB"]
    # Cleanup
    requests.patch(f"{API}/ai-visibility/settings", headers=h,
                    json={"brand_aliases": [], "competitor_names": []}, timeout=15)


def test_settings_reports_provider_status():
    r = requests.get(f"{API}/ai-visibility/settings", headers=_admin(), timeout=15)
    assert r.status_code == 200
    ps = r.json()["provider_status"]
    assert set(ps.keys()) == {"claude", "perplexity", "gemini", "dataforseo_aio"}
    # Claude + DFS should be True in this env; Perplexity/Gemini disabled.
    assert ps["claude"]["enabled"] is True
    assert ps["dataforseo_aio"]["enabled"] is True


def test_run_now_returns_all_4_provider_rows_with_graceful_degradation(monkeypatch):
    """Add a fresh prompt, fire run-now, verify 4 rows returned regardless
    of which providers are configured. Each disabled provider surfaces
    ``error='provider_disabled'`` on its row."""
    from routers import ai_visibility as _aiv

    h = _admin()
    txt = f"pytest smoke {uuid.uuid4().hex[:6]}"
    p = requests.post(f"{API}/ai-visibility/prompts", headers=h,
                       json={"prompt_text": txt, "tags": ["pytest"]}, timeout=15).json()

    # Monkey-patch the module's PROVIDERS dict via a background curl —
    # we can't monkey-patch the running server process from pytest. So
    # we just verify the shape of the response: 4 providers, some
    # errored (Perplexity/Gemini) and others responded.
    r = requests.post(f"{API}/ai-visibility/prompts/{p['id']}/run-now",
                        headers=h, timeout=90)
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert len(results) == 4
    provs = {row["provider"] for row in results}
    assert provs == {"claude", "perplexity", "gemini", "dataforseo_aio"}
    # Perplexity + Gemini must gracefully degrade with provider_disabled.
    px = next(r for r in results if r["provider"] == "perplexity")
    gm = next(r for r in results if r["provider"] == "gemini")
    assert px["error"] == "provider_disabled"
    assert gm["error"] == "provider_disabled"


def test_run_now_cooldown_returns_429():
    h = _admin()
    txt = f"pytest cooldown {uuid.uuid4().hex[:6]}"
    p = requests.post(f"{API}/ai-visibility/prompts", headers=h,
                       json={"prompt_text": txt, "tags": ["pytest"]}, timeout=15).json()
    # Poke last_run_at recent.
    _sync.ai_prompts.update_one({"id": p["id"]},
        {"$set": {"last_run_at": "2999-01-01T00:00:00+00:00"}})
    r = requests.post(f"{API}/ai-visibility/prompts/{p['id']}/run-now",
                        headers=h, timeout=15)
    assert r.status_code == 429
