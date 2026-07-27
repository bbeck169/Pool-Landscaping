"""Task QQ Phase 2.7 · Feb 2026 — Zapier bridge defensive hardening.

Ships tests for the missing-field defaults, test-payload short-
circuit, malformed-JSON handling, dispatch fencing, and the
correlation_id that appears on every response body + log line.

Uses the same in-memory FakeCollection pattern as Phase 2.5 so we
can drive the TestClient without contending with the real Motor
event loop.
"""
from __future__ import annotations

import logging
import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_TEST_SECRET = "test_" + uuid.uuid4().hex + uuid.uuid4().hex


@pytest.fixture(scope="module", autouse=True)
def _patch_bridge_db():
    """Module-scoped so it runs BEFORE the ``client`` fixture is
    built. Rebinds ``bridge_module.db`` to THIS file's ``_fake`` and
    sets the shared-secret env var. Cleanup restores both."""
    import os as _os
    prev_secret = _os.environ.get("LUMINO_ZAPIER_SHARED_SECRET", "")
    prev_db = getattr(bridge_module, "db", None)
    bridge_module.db = _fake
    _os.environ["LUMINO_ZAPIER_SHARED_SECRET"] = _TEST_SECRET
    yield
    if prev_db is not None:
        bridge_module.db = prev_db
    if prev_secret:
        _os.environ["LUMINO_ZAPIER_SHARED_SECRET"] = prev_secret
    else:
        _os.environ.pop("LUMINO_ZAPIER_SHARED_SECRET", None)


class _FakeCollection:
    def __init__(self):
        self._by_id: dict[str, dict] = {}

    async def find_one(self, query, projection=None):
        if "lumino_event_id" in query:
            eid = query["lumino_event_id"]
            for doc in self._by_id.values():
                if doc.get("lumino_event_id") == eid:
                    return dict(doc)
            return None
        if "raw.data.payment_id" in query:
            pid = query["raw.data.payment_id"]
            for doc in self._by_id.values():
                raw = doc.get("raw") or {}
                data = raw.get("data") or {}
                if data.get("payment_id") == pid:
                    return dict(doc)
            return None
        return None

    async def insert_one(self, doc):
        self._by_id[doc["id"]] = dict(doc)
        class _R:
            inserted_id = doc["id"]
        return _R()

    def clear(self):
        self._by_id.clear()

    def all(self):
        return list(self._by_id.values())


class _FakeDB:
    def __init__(self):
        self.payment_events = _FakeCollection()


import routers.lumino_zapier_bridge as bridge_module    # noqa: E402
from routers.lumino_zapier_bridge import router as _bridge_router  # noqa: E402

_fake = _FakeDB()


@pytest.fixture(scope="module")
def app():
    a = FastAPI()
    a.include_router(_bridge_router, prefix="/api")
    return a


@pytest.fixture(scope="module")
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_fake_events():
    yield
    _fake.payment_events.clear()


def _hdr(secret_ok: bool = True, event_type: str | None = None) -> dict:
    h = {"Content-Type": "application/json"}
    if secret_ok:
        h["x-zapier-shared-secret"] = _TEST_SECRET
    if event_type is not None:
        h["event_type"] = event_type
    return h


# ═══════════════════════════════════════════════════════════════════
# 2.7 · Missing / malformed fields — no 500s.
# ═══════════════════════════════════════════════════════════════════
def test_missing_event_id_generates_one_and_returns_200(client):
    r = client.post("/api/webhooks/lumino/zapier",
                        headers=_hdr(event_type="payment.created"),
                        json={"data": {"status": "paid",
                                            "payment_id": "pay_1"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["event_id"].startswith("gen_")
    assert body["correlation_id"]


def test_missing_data_defaults_to_empty_dict(client):
    r = client.post("/api/webhooks/lumino/zapier",
                        headers=_hdr(event_type="payment.created"),
                        json={"event_id": "qq_p27_no_data"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["event_id"] == "qq_p27_no_data"


def test_missing_occurred_at_defaults_to_now(client):
    r = client.post("/api/webhooks/lumino/zapier",
                        headers=_hdr(event_type="payment.created"),
                        json={"event_id": "qq_p27_no_ts",
                                "data": {"status": "paid",
                                            "payment_id": "p_ts"}})
    assert r.status_code == 200, r.text
    doc = _fake.payment_events.all()[-1]
    assert doc["raw"]["occurred_at"]                             # defaulted


def test_missing_header_and_status_stores_unknown_no_500(client):
    r = client.post("/api/webhooks/lumino/zapier",
                        headers=_hdr(),
                        json={"event_id": "qq_p27_unknown",
                                "data": {"payment_id": "p_x"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["event_type"] == "unknown"
    assert body["resolution_source"] == "unknown"


# ═══════════════════════════════════════════════════════════════════
# 2.7 · Malformed JSON → clean 400, not 500.
# ═══════════════════════════════════════════════════════════════════
def test_malformed_json_returns_400_with_correlation_id(client):
    r = client.post("/api/webhooks/lumino/zapier",
                        headers=_hdr(),
                        data=b'{"event_id": "broken"')             # trailing comma / missing }
    assert r.status_code == 400
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "invalid_json_body"
    assert body["correlation_id"]


# ═══════════════════════════════════════════════════════════════════
# 2.7 · Zapier test-payload short-circuit.
# ═══════════════════════════════════════════════════════════════════
def test_empty_body_returns_test_mode_true(client):
    r = client.post("/api/webhooks/lumino/zapier",
                        headers=_hdr(), json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["test_mode"] is True
    assert body["correlation_id"]


def test_data_only_body_returns_test_mode_true(client):
    r = client.post("/api/webhooks/lumino/zapier",
                        headers=_hdr(), json={"data": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["test_mode"] is True


def test_null_body_returns_test_mode_true(client):
    # jsdon "null" body is parsed by json.loads to None.
    r = client.post("/api/webhooks/lumino/zapier",
                        headers=_hdr(), data=b"null")
    assert r.status_code == 200
    body = r.json()
    assert body["test_mode"] is True


def test_test_mode_bypassed_when_event_type_header_present(client):
    """If the caller took the trouble to set an event_type header,
    treat it as a real event even if data is empty — do NOT swallow
    it as a test payload."""
    r = client.post("/api/webhooks/lumino/zapier",
                        headers=_hdr(event_type="payment.created"),
                        json={})
    assert r.status_code == 200
    body = r.json()
    assert body.get("test_mode") is not True


# ═══════════════════════════════════════════════════════════════════
# 2.7 · Dispatch fencing — a downstream crash must NOT 500 the bridge.
# ═══════════════════════════════════════════════════════════════════
def test_dispatch_crash_still_returns_200(client, monkeypatch):
    async def _boom(*_a, **_kw):
        raise RuntimeError("simulated downstream bug")
    monkeypatch.setattr(bridge_module, "_dispatch", _boom)
    r = client.post("/api/webhooks/lumino/zapier",
                        headers=_hdr(event_type="payment.created"),
                        json={"event_id": "qq_p27_boom",
                                "data": {"status": "paid",
                                            "payment_id": "p_bx"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["dispatched"] is False
    assert "dispatch_error" in body
    assert "simulated downstream bug" in body["dispatch_error"]


# ═══════════════════════════════════════════════════════════════════
# 2.7 · Correlation id — every response body carries one, and every
# log line for a request shares it.
# ═══════════════════════════════════════════════════════════════════
def test_correlation_id_present_on_every_response(client, caplog):
    caplog.set_level(logging.INFO, logger="lumino_zapier_bridge")
    r = client.post("/api/webhooks/lumino/zapier",
                        headers=_hdr(event_type="payment.created"),
                        json={"event_id": "qq_p27_cid",
                                "data": {"status": "paid",
                                            "payment_id": "p_cid"}})
    assert r.status_code == 200
    cid = r.json()["correlation_id"]
    assert cid
    # Grep the captured logs for the same correlation id — proves
    # the response id matches the log id (grepable post-mortem).
    log_lines = [rec.message for rec in caplog.records]
    assert any(cid in msg for msg in log_lines), (
        f"correlation_id {cid} not found in log lines"
    )


def test_correlation_id_present_on_401(client):
    r = client.post("/api/webhooks/lumino/zapier",
                        headers=_hdr(secret_ok=False),
                        json={"event_id": "x"})
    assert r.status_code == 401
    body = r.json()
    assert body["ok"] is False
    assert body["correlation_id"]


def test_correlation_id_present_on_400_malformed(client):
    r = client.post("/api/webhooks/lumino/zapier",
                        headers=_hdr(), data=b"garbage{")
    assert r.status_code == 400
    body = r.json()
    assert body["correlation_id"]


# ═══════════════════════════════════════════════════════════════════
# 2.7 · Header redaction — the shared secret must NOT appear in
# full in any log line.
# ═══════════════════════════════════════════════════════════════════
def test_shared_secret_redacted_in_logs(client, caplog):
    caplog.set_level(logging.INFO, logger="lumino_zapier_bridge")
    r = client.post("/api/webhooks/lumino/zapier",
                        headers=_hdr(event_type="payment.created"),
                        json={"event_id": "qq_p27_redact",
                                "data": {"status": "paid",
                                            "payment_id": "p_r"}})
    assert r.status_code == 200
    log_lines = "\n".join(rec.message for rec in caplog.records)
    # The full secret must not appear.
    assert _TEST_SECRET not in log_lines, (
        "FULL shared secret leaked into log line — check "
        "_redact_headers()"
    )
    # But a 6-char prefix + ellipsis SHOULD appear so ops can
    # correlate which secret Zapier sent.
    assert _TEST_SECRET[:6] in log_lines
