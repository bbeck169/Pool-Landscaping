"""Phase 15A — Real-time notifications, CSAT survey loop, digital signatures."""
import base64
import json
import os
from pathlib import Path

import requests
from dotenv import dotenv_values

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE, "REACT_APP_BACKEND_URL must be set"

ADMIN = ("admin@aquaterra.com", "password123")


def _login(email, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _pick_job(headers):
    r = requests.get(f"{BASE}/api/jobs", headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()[0]["id"]


def _pick_quote(headers):
    r = requests.get(f"{BASE}/api/quotes?doc_type=quote", headers=headers, timeout=15)
    r.raise_for_status()
    quotes = r.json()
    return quotes[0]["id"]


# ─── CSAT ────────────────────────────────────────────────────────────────────
class TestCSAT:
    def test_send_survey_admin(self):
        h = _login(*ADMIN)
        jid = _pick_job(h)
        r = requests.post(f"{BASE}/api/csat/send/{jid}", headers=h, json={"channel": "email"}, timeout=15)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert data["ok"] is True
        assert "token" in data["survey"]

    def test_send_survey_idempotent(self):
        h = _login(*ADMIN)
        jid = _pick_job(h)
        r1 = requests.post(f"{BASE}/api/csat/send/{jid}", headers=h, json={"channel": "email"}, timeout=15).json()
        r2 = requests.post(f"{BASE}/api/csat/send/{jid}", headers=h, json={"channel": "email"}, timeout=15).json()
        assert r1["survey"]["token"] == r2["survey"]["token"]

    def test_public_get_and_submit_detractor_creates_task(self):
        h = _login(*ADMIN)
        # Pick a job that hasn't been surveyed yet. Fall back to any job if all have surveys.
        jobs = requests.get(f"{BASE}/api/jobs", headers=h, timeout=15).json()
        existing = requests.get(f"{BASE}/api/csat", headers=h, timeout=15).json()
        surveyed_jids = {s.get("job_id") for s in existing.get("surveys", [])}
        candidates = [j for j in jobs if j["id"] not in surveyed_jids]
        assert candidates, "No un-surveyed jobs available for test"
        jid = candidates[0]["id"]
        r = requests.post(f"{BASE}/api/csat/send/{jid}", headers=h, json={"channel": "email"}, timeout=15).json()
        token = r["survey"]["token"]

        # Public GET (no auth)
        pub = requests.get(f"{BASE}/api/public/csat/{token}", timeout=15)
        assert pub.status_code == 200
        assert pub.json()["nps_score"] is None

        # Submit detractor
        sub = requests.post(f"{BASE}/api/public/csat/{token}/submit",
                            json={"nps_score": 2, "csat_score": 1, "comment": "TEST_PHASE15A bad"},
                            timeout=15)
        assert sub.status_code == 200
        assert sub.json()["ok"] is True

        # Verify a task was created
        tasks = requests.get(f"{BASE}/api/tasks", headers=h, timeout=15).json()
        det_tasks = [t for t in tasks if t.get("source") == "csat-detractor" and t.get("job_id") == jid]
        assert len(det_tasks) >= 1
        assert det_tasks[0]["priority"] == "high"

    def test_double_submit_rejected(self):
        h = _login(*ADMIN)
        jobs = requests.get(f"{BASE}/api/jobs", headers=h, timeout=15).json()
        existing = requests.get(f"{BASE}/api/csat", headers=h, timeout=15).json()
        surveyed_jids = {s.get("job_id") for s in existing.get("surveys", [])}
        candidates = [j for j in jobs if j["id"] not in surveyed_jids]
        assert candidates, "No un-surveyed jobs available for test"
        jid = candidates[0]["id"]
        token = requests.post(f"{BASE}/api/csat/send/{jid}", headers=h, json={}, timeout=15).json()["survey"]["token"]
        requests.post(f"{BASE}/api/public/csat/{token}/submit",
                      json={"nps_score": 10, "csat_score": 5}, timeout=15)
        second = requests.post(f"{BASE}/api/public/csat/{token}/submit",
                               json={"nps_score": 9, "csat_score": 4}, timeout=15)
        assert second.status_code == 400

    def test_summary_includes_new_response(self):
        h = _login(*ADMIN)
        r = requests.get(f"{BASE}/api/csat", headers=h, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "summary" in data and "surveys" in data
        assert data["summary"]["total_sent"] >= 1


# ─── Signatures ──────────────────────────────────────────────────────────────
class TestSignatures:
    PNG_1x1 = ("data:image/png;base64,"
               "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

    def test_request_and_submit_signature_flips_status(self):
        h = _login(*ADMIN)
        qid = _pick_quote(h)
        r = requests.post(f"{BASE}/api/quotes/{qid}/request-signature",
                          headers=h,
                          json={"signer_email": "sig-test@example.com", "message": "TEST_PHASE15A"},
                          timeout=15)
        assert r.status_code == 200, r.text[:400]
        token = r.json()["token"]

        # Public GET (no auth)
        pub = requests.get(f"{BASE}/api/public/sign/{token}", timeout=15)
        assert pub.status_code == 200
        assert pub.json()["signed"] is False
        assert pub.json()["doc"]["title"]

        # Submit
        sub = requests.post(f"{BASE}/api/public/sign/{token}/submit",
                            json={"signer_name": "TEST Phase15A Signer", "signature_svg": self.PNG_1x1},
                            timeout=15)
        assert sub.status_code == 200
        assert "signed_at" in sub.json()

        # Admin verifies hash matches
        sig = requests.get(f"{BASE}/api/quotes/{qid}/signature", headers=h, timeout=15).json()
        assert sig["signed"] is True
        assert sig["signer_name"] == "TEST Phase15A Signer"
        assert sig["hash_matches"] is True

        # Quote status flipped
        q = requests.get(f"{BASE}/api/quotes/{qid}", headers=h, timeout=15).json()
        assert q["status"] == "signed"
        assert q["signer_name"] == "TEST Phase15A Signer"

    def test_double_sign_rejected(self):
        h = _login(*ADMIN)
        qid = _pick_quote(h)
        r = requests.post(f"{BASE}/api/quotes/{qid}/request-signature",
                          headers=h, json={"signer_email": "sig-test@example.com"}, timeout=15).json()
        token = r["token"]
        requests.post(f"{BASE}/api/public/sign/{token}/submit",
                      json={"signer_name": "First", "signature_svg": self.PNG_1x1}, timeout=15)
        second = requests.post(f"{BASE}/api/public/sign/{token}/submit",
                               json={"signer_name": "Second", "signature_svg": self.PNG_1x1}, timeout=15)
        assert second.status_code == 400

    def test_signed_pdf_download(self):
        h = _login(*ADMIN)
        qid = _pick_quote(h)
        r = requests.post(f"{BASE}/api/quotes/{qid}/request-signature", headers=h,
                          json={"signer_email": "sig-test@example.com"}, timeout=15).json()
        token = r["token"]
        requests.post(f"{BASE}/api/public/sign/{token}/submit",
                      json={"signer_name": "PDF Test", "signature_svg": self.PNG_1x1}, timeout=15)
        pdf = requests.get(f"{BASE}/api/public/sign/{token}/pdf", timeout=15)
        assert pdf.status_code == 200
        assert pdf.content[:4] == b"%PDF"
        assert len(pdf.content) > 500


# ─── Realtime ────────────────────────────────────────────────────────────────
class TestRealtime:
    def test_sse_endpoint_rejects_bad_token(self):
        # SSE with invalid token should 401
        r = requests.get(f"{BASE}/api/sse/notifications?token=invalidtoken",
                         timeout=5, stream=False)
        assert r.status_code == 401

    def test_broadcast_endpoint_returns_delivery_count(self):
        r = requests.post(f"{BASE}/api/realtime/broadcast-test",
                          json={"user_id": "*", "type": "test", "payload": {"n": 1}},
                          timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "delivered" in body

    def test_websocket_receives_broadcast(self):
        # End-to-end WS handshake + broadcast delivery.
        try:
            import websocket  # websocket-client
        except Exception:
            import pytest
            pytest.skip("websocket-client not installed")

        h = _login(*ADMIN)
        # Extract user_id from token
        token = h["Authorization"].split(" ")[1]
        payload = token.split(".")[1]
        payload += "=" * ((4 - len(payload) % 4) % 4)
        user_id = json.loads(base64.urlsafe_b64decode(payload))["sub"]

        ws_url = BASE.replace("http://", "ws://").replace("https://", "wss://") + f"/api/ws/notifications?token={token}"
        ws = websocket.create_connection(ws_url, timeout=10)
        try:
            hello = json.loads(ws.recv())
            assert hello["type"] == "connected"
            # Trigger a broadcast
            requests.post(f"{BASE}/api/realtime/broadcast-test",
                          json={"user_id": user_id, "type": "phase15a-test", "payload": {"ok": 1}},
                          timeout=10)
            ws.settimeout(5)
            msg = json.loads(ws.recv())
            assert msg["type"] == "phase15a-test"
            assert msg["payload"] == {"ok": 1}
        finally:
            ws.close()


# ─── Cleanup ─────────────────────────────────────────────────────────────────
def test_zzz_cleanup():
    """Purge TEST_PHASE15A survey rows + tasks so re-runs are hermetic."""
    from motor.motor_asyncio import AsyncIOMotorClient
    import asyncio
    mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("DB_NAME") or "test_database"
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    async def _clean():
        await db.tasks.delete_many({"description": {"$regex": "TEST_PHASE15A", "$options": "i"}})
        await db.csat_surveys.delete_many({"comment": {"$regex": "TEST_PHASE15A", "$options": "i"}})
        await db.signatures.delete_many({"message": "TEST_PHASE15A"})
    asyncio.run(_clean())
    client.close()
