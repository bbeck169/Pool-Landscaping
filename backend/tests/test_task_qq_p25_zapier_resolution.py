"""Task QQ Phase 2.5 · Feb 2026 — Zapier bridge event_type resolution.

In-process TestClient suite that exercises the header-first → payload
inference → unknown fallback resolution ladder.

Design note — we monkeypatch ``routers.lumino_zapier_bridge.db``
onto an in-memory fake because the real motor client is bound to
the FastAPI app's startup event loop, and driving it from a sync
``TestClient`` (which uses its own anyio portal loop) triggers
"attached to a different loop" errors. The fake exposes only the
``payment_events`` collection and only the three methods this
router calls — ``find_one``, ``insert_one``, and the collection's
absence of update/delete (we handle those in test setup).
"""
from __future__ import annotations

import logging
import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ─── Test-scoped shared secret ────────────────────────────────────
# Random per pytest run, never reused, and NOT any value that has
# been pasted in chat / email / logs.
_TEST_SECRET = "test_" + uuid.uuid4().hex + uuid.uuid4().hex
# NOTE: env var is set per-test via the autouse fixture below —
# NOT at module import time. Prevents cross-file interference with
# the Phase 2.7 hardening tests.


# ─── In-memory fake for ``db.payment_events`` ─────────────────────
class _FakeCollection:
    def __init__(self):
        self._by_id: dict[str, dict] = {}

    async def find_one(self, query, projection=None):
        # Handle only the queries the router issues:
        # {"lumino_event_id": <id>} and {"raw.data.payment_id": <pid>}
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


@pytest.fixture(scope="module", autouse=True)
def _patch_bridge_db():
    """Module-scoped autouse — sets shared secret + db BEFORE the
    ``client`` module fixture is built, and BEFORE Phase 2.7's
    module-scoped fixture (whichever runs later wins for env, so
    each file's fixture re-seats state at its own module setup)."""
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


def _post(client, *, event_id: str, event_type_header: str | None = None,
          data: dict | None = None, use_secret: bool = True):
    headers = {"Content-Type": "application/json"}
    if use_secret:
        headers["x-zapier-shared-secret"] = _TEST_SECRET
    if event_type_header is not None:
        headers["event_type"] = event_type_header
    body = {
        "event_id": event_id,
        "occurred_at": "2026-02-01T12:00:00Z",
        "data": data or {},
    }
    return client.post("/api/webhooks/lumino/zapier",
                          headers=headers, json=body)


def _fetch_event(event_id: str) -> dict | None:
    for doc in _fake.payment_events.all():
        if doc.get("lumino_event_id") == event_id:
            return doc
    return None


# ═══════════════════════════════════════════════════════════════════
# Shared-secret verification — 401 paths.
# ═══════════════════════════════════════════════════════════════════
def test_shared_secret_missing_header_returns_401(client):
    r = _post(client, event_id="qq_p25_no_secret",
                data={"status": "paid"}, use_secret=False)
    assert r.status_code == 401


def test_shared_secret_wrong_header_returns_401(client):
    headers = {"Content-Type": "application/json",
                 "x-zapier-shared-secret": "definitely-wrong"}
    r = client.post("/api/webhooks/lumino/zapier",
                       headers=headers,
                       json={"event_id": "qq_p25_wrong_secret",
                              "data": {"status": "paid"}})
    assert r.status_code == 401


def test_shared_secret_correct_header_returns_200(client):
    r = _post(client, event_id="qq_p25_ok_secret",
                event_type_header="payment.created",
                data={"status": "paid", "payment_id": "pay_ok_1"})
    assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════
# Header path — valid value → resolution_source="header".
# ═══════════════════════════════════════════════════════════════════
def test_valid_header_uses_header(client):
    eid = "qq_p25_hdr_valid"
    r = _post(client, event_id=eid,
                event_type_header="payment.updated",
                data={"status": "paid", "payment_id": "pay_hdr_1"})
    assert r.status_code == 200
    body = r.json()
    assert body["event_type"] == "payment.updated"
    assert body["resolution_source"] == "header"
    doc = _fetch_event(eid)
    assert doc is not None
    assert doc["event_type"] == "payment.updated"
    assert doc["resolution_source"] == "header"


# ═══════════════════════════════════════════════════════════════════
# Header path — junk value → falls back to inference.
# ═══════════════════════════════════════════════════════════════════
def test_unknown_header_value_falls_back_to_inference(client):
    eid = "qq_p25_hdr_garbage"
    r = _post(client, event_id=eid,
                event_type_header="totally.not.a.real.event",
                data={"status": "refunded", "payment_id": "pay_garb_1"})
    assert r.status_code == 200
    body = r.json()
    assert body["event_type"] == "payment.refunded"
    assert body["resolution_source"] == "inferred"


# ═══════════════════════════════════════════════════════════════════
# Payload inference — data.status ladder.
# ═══════════════════════════════════════════════════════════════════
def test_missing_header_infers_refunded(client):
    eid = "qq_p25_inf_refunded"
    r = _post(client, event_id=eid,
                event_type_header=None,
                data={"status": "refunded", "payment_id": "pay_ref_1"})
    assert r.status_code == 200
    assert r.json()["event_type"] == "payment.refunded"
    assert r.json()["resolution_source"] == "inferred"


def test_missing_header_infers_payment_created_when_new(client):
    eid = "qq_p25_inf_created"
    r = _post(client, event_id=eid,
                event_type_header=None,
                data={"status": "succeeded",
                        "payment_id": "pay_new_" + uuid.uuid4().hex[:8]})
    assert r.status_code == 200
    assert r.json()["event_type"] == "payment.created"
    assert r.json()["resolution_source"] == "inferred"


def test_missing_header_infers_payment_updated_when_seen_before(client):
    pid = "pay_repeat_" + uuid.uuid4().hex[:8]
    # First sighting → payment.created.
    r1 = _post(client, event_id="qq_p25_first_" + uuid.uuid4().hex[:6],
                 event_type_header=None,
                 data={"status": "succeeded", "payment_id": pid})
    assert r1.status_code == 200
    assert r1.json()["event_type"] == "payment.created"
    # Second sighting of same payment_id → payment.updated.
    r2 = _post(client, event_id="qq_p25_second_" + uuid.uuid4().hex[:6],
                 event_type_header=None,
                 data={"status": "paid", "payment_id": pid})
    assert r2.status_code == 200
    assert r2.json()["event_type"] == "payment.updated"


def test_missing_header_infers_failed_as_payment_updated(client):
    eid = "qq_p25_inf_failed"
    r = _post(client, event_id=eid,
                event_type_header=None,
                data={"status": "declined", "payment_id": "pay_fail_1"})
    assert r.status_code == 200
    assert r.json()["event_type"] == "payment.updated"


def test_missing_header_infers_subscription_canceled(client):
    eid = "qq_p25_inf_sub_cancel"
    r = _post(client, event_id=eid,
                event_type_header=None,
                data={"status": "canceled",
                        "subscription_id": "sub_x_1"})
    assert r.status_code == 200
    assert r.json()["event_type"] == "subscription.canceled"


# ═══════════════════════════════════════════════════════════════════
# Unknown path — payload didn't resolve, WARN log + stored anyway.
# ═══════════════════════════════════════════════════════════════════
def test_unknown_status_stored_as_unknown_with_warn(client, caplog):
    caplog.set_level(logging.WARNING, logger="lumino_zapier_bridge")
    eid = "qq_p25_unknown"
    r = _post(client, event_id=eid,
                event_type_header=None,
                data={"status": "something_weird",
                        "payment_id": "pay_weird_1"})
    assert r.status_code == 200
    body = r.json()
    assert body["event_type"] == "unknown"
    assert body["resolution_source"] == "unknown"
    doc = _fetch_event(eid)
    assert doc is not None
    assert doc["event_type"] == "unknown"
    assert doc["resolution_source"] == "unknown"
    warn_msgs = [rec.message for rec in caplog.records
                     if rec.levelno >= logging.WARNING]
    assert any("could not resolve event_type" in m for m in warn_msgs), \
        f"Expected WARN log, got: {warn_msgs}"


# ═══════════════════════════════════════════════════════════════════
# Idempotency — same event_id twice → deduped.
# ═══════════════════════════════════════════════════════════════════
def test_duplicate_event_id_is_deduped(client):
    eid = "qq_p25_dedupe"
    body = {"event_id": eid, "occurred_at": "2026-02-01T12:00:00Z",
              "data": {"status": "paid", "payment_id": "pay_dd_1"}}
    headers = {"Content-Type": "application/json",
                 "x-zapier-shared-secret": _TEST_SECRET,
                 "event_type": "payment.created"}
    r1 = client.post("/api/webhooks/lumino/zapier",
                        headers=headers, json=body)
    r2 = client.post("/api/webhooks/lumino/zapier",
                        headers=headers, json=body)
    assert r1.status_code == 200 and r1.json()["deduped"] is False
    assert r2.status_code == 200 and r2.json()["deduped"] is True


# ═══════════════════════════════════════════════════════════════════
# Guardrail — compromised chat secrets must never appear in code
# or env. This test grep-scans for every leaked value we know about
# and fails loudly if a future contributor pastes any of them back.
#
# Feb 2026 update — extended from 1 → 4 values after a second
# Zapier secret + a RapidAPI key + a live Lumino secret were pasted
# in chat and confirmed compromised. All values are assembled at
# runtime from parts so THIS test file itself never contains any
# literal (else the grep would flag itself).
#
# Feb 2026 update #2 — extended from 4 → 6 values after a rotated
# OpenWebNinja key (V5) and a rotated Zapier shared secret (V6)
# were also pasted in chat and immediately marked compromised.
# ═══════════════════════════════════════════════════════════════════
def test_compromised_secret_not_present_anywhere():
    import pathlib
    # All 6 known-compromised values, assembled from parts.
    V1 = "zap_lum_" + "9f7d4c2e" + "8b1a5f6e" + "3d9c2b7a" + "8e1f4d6c"
    V2 = "zap_lum_" + "a7f2e9d1" + "c4b8h6j3" + "k1m5n2p9" + "q7r4s8t1"
    V3 = "ak_" + "r0gahuut" + "3djgfat0" + "3tpn7fxe" + "ckss99qz" + "t3oobqq9ycjd201"
    V4 = "sk_live_" + "b116141e" + "_4j0jCE_" + "8tyZHQtc" + "fDlIDle4" + "hk8cv2hRhAKQ7A"
    V5 = "ak_" + "n1ojoydj" + "bmr5lcsu" + "ijkhm7mv" + "cqqk1o29" + "2jvzhvbo68yeq9y"
    V6 = "zap_lum_" + "n3q6t9w2" + "z5c8f1h4" + "k7m0p3r6" + "s9v2w5y"
    compromised = {
        "V1_zapier_shared_secret_1": V1,
        "V2_zapier_shared_secret_2": V2,
        "V3_rapidapi_key": V3,
        "V4_lumino_live_secret": V4,
        "V5_openwebninja_key_rotated": V5,
        "V6_zapier_shared_secret_rotated": V6,
    }
    # Repo-scope scan — /app is the source-of-truth workspace and
    # the only tree deploys can source. /var/log, /tmp, /root are
    # ephemeral pod state and not shipped, so they're intentionally
    # out of scope for the regression guard.
    root = pathlib.Path("/app")
    # Skip vendor / build / cache trees that can't possibly ship a
    # secret and would balloon the scan by hours.
    SKIP_DIRS = {"node_modules", "__pycache__", ".git", ".yarn",
                 ".cache", "dist", "build", ".next", ".venv"}
    SKIP_SUFFIX = {".pyc", ".so", ".png", ".jpg", ".jpeg", ".pdf",
                    ".zip", ".gz", ".mp4", ".mp3", ".woff",
                    ".woff2", ".ttf", ".ico", ".webp"}
    hits: list[str] = []
    for p in root.rglob("*"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if not p.is_file():
            continue
        if p.suffix in SKIP_SUFFIX:
            continue
        try:
            if p.stat().st_size > 20 * 1024 * 1024:
                continue
        except OSError:
            continue
        try:
            text = p.read_text(errors="ignore")
        except Exception:
            continue
        for label, v in compromised.items():
            if v in text:
                hits.append(f"{label} → {p}")
    assert not hits, (
        "COMPROMISED SECRET(S) leaked into repo — purge immediately "
        f"and rotate every affected credential:\n  " + "\n  ".join(hits)
    )
