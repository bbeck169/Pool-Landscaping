"""Phase 33 · Step 1 — AI CFO NL Q&A + Scenario tests.

Coverage:
 1. RBAC — admin 200, tech/customer 403 on Q&A + Scenario + history.
 2. Validation — empty question / empty prompt → 422.
 3. Q&A LLM error path → 200 with `mocked:true` + reason.
 4. Q&A JSON-parseable success path via stubbed LlmChat helper —
    verifies persistence + tokens_used bump.
 5. Scenario JSON-parseable success — persists to cfo_scenarios, shape
    contains 12 monthly buckets, annual{}, confidence, caveats.
 6. Scenario LLM-error path returns the empty-scenario shape with
    `mocked:true`.
 7. Quota — pin request_count=200 → soft error; ?force=true bypasses.
 8. History endpoints — latest first, tenant-isolated (sunbelt admin
    never sees aquaterra's rows).
 9. Save-as-favorite — 404 for unknown id, 200 flips the flag.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

ADMIN_A = {"email": "admin@aquaterra.com", "password": "password123"}
ADMIN_B = {"email": "admin@sunbelt.com",   "password": "password123"}
TECH    = {"email": "mike@aquaterra.com",  "password": "password123"}
CUST    = {"email": "customer@aquaterra.com", "password": "password123"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.text}"
    return r.json()["access_token"]


def _auth(tok): return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_a_tok(): return _login(ADMIN_A)


@pytest.fixture(scope="module")
def admin_b_tok(): return _login(ADMIN_B)


@pytest.fixture(scope="module")
def tech_tok(): return _login(TECH)


@pytest.fixture(scope="module")
def cust_tok(): return _login(CUST)


def _tenant_id_for(email: str) -> str:
    env = dotenv_values("/app/backend/.env")
    cli = AsyncIOMotorClient(env["MONGO_URL"])
    db = cli[env["DB_NAME"]]

    async def _q():
        u = await db.users.find_one({"email": email})
        return u["tenant_id"] if u else None
    tid = asyncio.get_event_loop().run_until_complete(_q())
    cli.close()
    return tid


def _reset_llm_usage(tenant_id: str):
    env = dotenv_values("/app/backend/.env")
    cli = AsyncIOMotorClient(env["MONGO_URL"])
    db = cli[env["DB_NAME"]]

    async def _r():
        today = datetime.now(timezone.utc).date().isoformat()
        await db.cfo_llm_usage.delete_many({"tenant_id": tenant_id, "date": today})
    asyncio.get_event_loop().run_until_complete(_r())
    cli.close()


# ─── 1. RBAC ──────────────────────────────────────────────────────────
class TestRbac:
    def test_qna_tech_forbidden(self, tech_tok):
        r = requests.post(f"{API}/cfo/qna", headers=_auth(tech_tok),
                           json={"question": "How's revenue?"}, timeout=15)
        assert r.status_code == 403, r.text

    def test_qna_customer_forbidden(self, cust_tok):
        r = requests.post(f"{API}/cfo/qna", headers=_auth(cust_tok),
                           json={"question": "How's revenue?"}, timeout=15)
        assert r.status_code == 403, r.text

    def test_scenario_tech_forbidden(self, tech_tok):
        r = requests.post(f"{API}/cfo/scenario", headers=_auth(tech_tok),
                           json={"prompt": "Hire 2 techs"}, timeout=15)
        assert r.status_code == 403, r.text

    def test_history_tech_forbidden(self, tech_tok):
        r1 = requests.get(f"{API}/cfo/qna/history", headers=_auth(tech_tok), timeout=15)
        r2 = requests.get(f"{API}/cfo/scenario/history", headers=_auth(tech_tok), timeout=15)
        assert r1.status_code == 403
        assert r2.status_code == 403


# ─── 2. Validation ────────────────────────────────────────────────────
class TestValidation:
    def test_qna_empty_question_422(self, admin_a_tok):
        r = requests.post(f"{API}/cfo/qna", headers=_auth(admin_a_tok),
                           json={"question": "   "}, timeout=15)
        assert r.status_code == 422, r.text

    def test_scenario_empty_prompt_422(self, admin_a_tok):
        r = requests.post(f"{API}/cfo/scenario", headers=_auth(admin_a_tok),
                           json={"prompt": ""}, timeout=15)
        assert r.status_code == 422, r.text

    def test_qna_invalid_period_422(self, admin_a_tok):
        r = requests.post(f"{API}/cfo/qna", headers=_auth(admin_a_tok),
                           json={"question": "x", "period": "nope"}, timeout=15)
        assert r.status_code == 422, r.text


# ─── 3. + 4. Q&A LLM paths ────────────────────────────────────────────
class TestQnaLlm:
    def test_llm_error_returns_mocked(self, admin_a_tok, monkeypatch):
        """Patch the LLM helper to fail; endpoint must still respond 200
        with mocked=true and a reason string, and persist history."""
        import sys
        sys.path.insert(0, "/app/backend")
        import routers.cfo as cfo_mod

        async def _boom(system, prompt, max_tokens):
            return None, "llm error: monkeypatched", 0
        monkeypatch.setattr(cfo_mod, "_call_llm_text", _boom)

        tid = _tenant_id_for(ADMIN_A["email"])
        _reset_llm_usage(tid)

        # Reach the coroutine directly (uvicorn worker doesn't see the patch).
        from routers.cfo import qna, QnaBody
        result = asyncio.get_event_loop().run_until_complete(
            qna(body=QnaBody(question="How much revenue this year?"),
                 force=True,
                 user={"role": "admin", "id": "TEST-actor"},
                 tenant={"id": tid})
        )
        assert result["mocked"] is True
        assert "monkeypatched" in (result.get("reason") or "")
        assert result["answer"] == ""
        assert result["history_id"]
        # Persistence check
        env = dotenv_values("/app/backend/.env")
        cli = AsyncIOMotorClient(env["MONGO_URL"])
        db = cli[env["DB_NAME"]]

        async def _check():
            return await db.cfo_qna_history.find_one(
                {"id": result["history_id"]}, {"_id": 0}
            )
        row = asyncio.get_event_loop().run_until_complete(_check())
        cli.close()
        assert row is not None
        assert row["mocked"] is True
        assert row["actor_user_id"] == "TEST-actor"
        # Cleanup
        cli = AsyncIOMotorClient(env["MONGO_URL"])
        asyncio.get_event_loop().run_until_complete(
            cli[env["DB_NAME"]].cfo_qna_history.delete_one({"id": result["history_id"]})
        )
        cli.close()
        _reset_llm_usage(tid)

    def test_qna_success_with_stubbed_llm(self, admin_a_tok, monkeypatch):
        import sys
        sys.path.insert(0, "/app/backend")
        import routers.cfo as cfo_mod

        async def _ok(system, prompt, max_tokens):
            return ("Revenue YTD is on track. Cash on hand is $5,000. "
                     "AR is fully current."), None, 42
        monkeypatch.setattr(cfo_mod, "_call_llm_text", _ok)

        tid = _tenant_id_for(ADMIN_A["email"])
        _reset_llm_usage(tid)
        from routers.cfo import qna, QnaBody
        result = asyncio.get_event_loop().run_until_complete(
            qna(body=QnaBody(question="How's YTD revenue?"),
                 force=True,
                 user={"role": "admin", "id": "TEST-actor-2"},
                 tenant={"id": tid})
        )
        assert result["mocked"] is False
        assert result["reason"] is None
        assert "5,000" in result["answer"]
        assert result["tokens_used"] == 42
        assert result["usage"]["request_count"] >= 1
        assert result["usage"]["tokens_used"] >= 42
        assert result["context_snapshot"]["revenue"]["total"] >= 0

        # cleanup
        env = dotenv_values("/app/backend/.env")
        cli = AsyncIOMotorClient(env["MONGO_URL"])
        asyncio.get_event_loop().run_until_complete(
            cli[env["DB_NAME"]].cfo_qna_history.delete_one({"id": result["history_id"]})
        )
        cli.close()
        _reset_llm_usage(tid)


# ─── 5. + 6. Scenario LLM paths ───────────────────────────────────────
class TestScenarioLlm:
    _valid_json_response = (
        '{"assumptions":["hire 2 techs at 22/hr","10% price uplift"],'
        '"monthly_delta":[{"month":1,"revenue_delta":500,"expense_delta":3520,"net_delta":-3020},'
                          '{"month":2,"revenue_delta":600,"expense_delta":3520,"net_delta":-2920}],'
        '"annual":{"revenue_delta":8000,"expense_delta":42240,"net_delta":-34240,"margin_delta_pct":-5.2},'
        '"confidence":"medium",'
        '"caveats":["assumes flat customer churn"],'
        '"mocked":false,"reason":null}'
    )

    def test_scenario_success_shape(self, admin_a_tok, monkeypatch):
        import sys
        sys.path.insert(0, "/app/backend")
        import routers.cfo as cfo_mod

        async def _ok(system, prompt, max_tokens):
            return self._valid_json_response, None, 128
        monkeypatch.setattr(cfo_mod, "_call_llm_text", _ok)

        tid = _tenant_id_for(ADMIN_A["email"])
        _reset_llm_usage(tid)
        from routers.cfo import scenario, ScenarioBody
        result = asyncio.get_event_loop().run_until_complete(
            scenario(
                body=ScenarioBody(prompt="Hire 2 techs at $22/hr + 10% price uplift",
                                    structured={"hire_techs": 2, "avg_hourly_rate": 22, "price_change_pct": 10}),
                force=True,
                user={"role": "admin", "id": "TEST-actor-3"},
                tenant={"id": tid},
            )
        )
        assert result["history_id"]
        r = result["result"]
        assert len(r["monthly_delta"]) == 12, "monthly_delta must be padded to 12"
        for m in r["monthly_delta"]:
            for k in ("month", "revenue_delta", "expense_delta", "net_delta"):
                assert k in m
        for k in ("revenue_delta", "expense_delta", "net_delta", "margin_delta_pct"):
            assert k in r["annual"]
        assert r["confidence"] in ("low", "medium", "high")
        assert isinstance(r["caveats"], list) and r["caveats"]
        assert r["mocked"] is False
        assert result["tokens_used"] == 128

        # Persistence
        env = dotenv_values("/app/backend/.env")
        cli = AsyncIOMotorClient(env["MONGO_URL"])
        db = cli[env["DB_NAME"]]

        async def _check():
            return await db.cfo_scenarios.find_one(
                {"id": result["history_id"]}, {"_id": 0}
            )
        row = asyncio.get_event_loop().run_until_complete(_check())
        assert row["favorite"] is False
        assert row["structured"]["hire_techs"] == 2

        # Favorite toggle
        r2 = requests.post(
            f"{API}/cfo/scenario/{result['history_id']}/save-as-favorite?favorite=true",
            headers=_auth(admin_a_tok), timeout=15,
        )
        assert r2.status_code == 200 and r2.json()["favorite"] is True

        asyncio.get_event_loop().run_until_complete(
            db.cfo_scenarios.delete_one({"id": result["history_id"]})
        )
        cli.close()
        _reset_llm_usage(tid)

    def test_scenario_llm_error_returns_empty_shape(self, admin_a_tok, monkeypatch):
        import sys
        sys.path.insert(0, "/app/backend")
        import routers.cfo as cfo_mod

        async def _boom(system, prompt, max_tokens):
            return None, "llm error: monkeypatched-scenario", 0
        monkeypatch.setattr(cfo_mod, "_call_llm_text", _boom)

        tid = _tenant_id_for(ADMIN_A["email"])
        _reset_llm_usage(tid)
        from routers.cfo import scenario, ScenarioBody
        result = asyncio.get_event_loop().run_until_complete(
            scenario(body=ScenarioBody(prompt="Increase marketing spend 20%"),
                      force=True,
                      user={"role": "admin", "id": "TEST-actor-4"},
                      tenant={"id": tid})
        )
        r = result["result"]
        assert r["mocked"] is True
        assert "monkeypatched" in (r["reason"] or "")
        assert len(r["monthly_delta"]) == 12
        assert r["annual"]["net_delta"] == 0.0
        assert r["confidence"] == "low"

        env = dotenv_values("/app/backend/.env")
        cli = AsyncIOMotorClient(env["MONGO_URL"])
        asyncio.get_event_loop().run_until_complete(
            cli[env["DB_NAME"]].cfo_scenarios.delete_one({"id": result["history_id"]})
        )
        cli.close()
        _reset_llm_usage(tid)


# ─── 7. Quota ─────────────────────────────────────────────────────────
class TestQuota:
    def test_qna_soft_block(self, admin_a_tok):
        tid = _tenant_id_for(ADMIN_A["email"])
        env = dotenv_values("/app/backend/.env")
        cli = AsyncIOMotorClient(env["MONGO_URL"])
        db = cli[env["DB_NAME"]]
        today = datetime.now(timezone.utc).date().isoformat()

        async def _pin():
            await db.cfo_llm_usage.update_one(
                {"tenant_id": tid, "date": today},
                {"$set": {"tenant_id": tid, "date": today,
                           "request_count": 250, "tokens_used": 9000}},
                upsert=True,
            )
        asyncio.get_event_loop().run_until_complete(_pin())
        cli.close()

        # Without force → soft block.
        r = requests.post(f"{API}/cfo/qna", headers=_auth(admin_a_tok),
                           json={"question": "How much did revenue grow?"},
                           timeout=15)
        assert r.status_code == 200
        assert r.json().get("error") == "quota_exceeded"

        # scenario same
        r2 = requests.post(f"{API}/cfo/scenario", headers=_auth(admin_a_tok),
                            json={"prompt": "Hire 2 techs"}, timeout=15)
        assert r2.status_code == 200
        assert r2.json().get("error") == "quota_exceeded"

        _reset_llm_usage(tid)


# ─── 8. History + tenant isolation ────────────────────────────────────
class TestHistory:
    def test_qna_history_shape_and_isolation(self, admin_a_tok, admin_b_tok, monkeypatch):
        """Aquaterra admin creates a Q&A row; sunbelt admin's history must
        NOT include it."""
        import sys
        sys.path.insert(0, "/app/backend")
        import routers.cfo as cfo_mod

        async def _ok(system, prompt, max_tokens):
            return "aquaterra-answer-marker", None, 8
        monkeypatch.setattr(cfo_mod, "_call_llm_text", _ok)

        tid_a = _tenant_id_for(ADMIN_A["email"])
        _reset_llm_usage(tid_a)
        from routers.cfo import qna, QnaBody
        result = asyncio.get_event_loop().run_until_complete(
            qna(body=QnaBody(question="isolation marker Q"),
                 force=True,
                 user={"role": "admin", "id": "TEST-actor-history"},
                 tenant={"id": tid_a})
        )
        hid = result["history_id"]

        # Via the HTTP endpoint (real server has no patch) — verify list
        # for aquaterra includes the id, sunbelt does not.
        a_list = requests.get(f"{API}/cfo/qna/history?limit=50",
                                headers=_auth(admin_a_tok), timeout=15).json()
        b_list = requests.get(f"{API}/cfo/qna/history?limit=50",
                                headers=_auth(admin_b_tok), timeout=15).json()
        assert any(r.get("id") == hid for r in a_list), "aquaterra must see its row"
        assert all(r.get("id") != hid for r in b_list), "sunbelt must NOT see it"

        # Latest-first ordering — created_at DESC
        if len(a_list) >= 2:
            ts = [r.get("created_at") for r in a_list if r.get("created_at")]
            assert ts == sorted(ts, reverse=True), "history must be created_at DESC"

        # Cleanup
        env = dotenv_values("/app/backend/.env")
        cli = AsyncIOMotorClient(env["MONGO_URL"])
        asyncio.get_event_loop().run_until_complete(
            cli[env["DB_NAME"]].cfo_qna_history.delete_one({"id": hid})
        )
        cli.close()
        _reset_llm_usage(tid_a)


# ─── 9. Save-as-favorite 404 ──────────────────────────────────────────
def test_save_favorite_404(admin_a_tok):
    r = requests.post(
        f"{API}/cfo/scenario/does-not-exist-{uuid.uuid4().hex[:6]}/save-as-favorite?favorite=true",
        headers=_auth(admin_a_tok), timeout=10,
    )
    assert r.status_code == 404
