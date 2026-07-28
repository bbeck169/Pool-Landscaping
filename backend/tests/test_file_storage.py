"""Phase F0 · Feb 2026 — file storage service + /api/files/* router tests.

Zero live HTTP — every ``requests.*`` call is monkey-patched. Uses
an in-memory FakeCollection for the ``files`` collection so no
Motor event loop is needed.
"""
from __future__ import annotations

import io
import os
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import services.file_storage as fs


# ═══════════════════════════════════════════════════════════════════
# fake requests + fake db
# ═══════════════════════════════════════════════════════════════════
class _FakeResp:
    def __init__(self, status_code: int, json_body: Optional[Dict[str, Any]] = None,
                 content: bytes = b"", text_body: str = "",
                 headers: Optional[Dict[str, str]] = None):
        self.status_code = status_code
        self._json = json_body
        self.content = content
        self.text = text_body or (str(json_body) if json_body else "")
        self.headers = headers or {}

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


class _RequestsRecorder:
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self.queue: List[_FakeResp] = []

    def queue_response(self, *responses: _FakeResp):
        self.queue.extend(responses)

    def _pop(self, method: str, url: str, **kw) -> _FakeResp:
        self.calls.append({"method": method, "url": url, **kw})
        if not self.queue:
            raise AssertionError(f"no queued response for {method} {url}")
        return self.queue.pop(0)

    def post(self, url, json=None, timeout=None, **kw):
        return self._pop("POST", url, json=json)

    def put(self, url, data=None, headers=None, timeout=None, **kw):
        return self._pop("PUT", url, data_len=len(data or b""),
                            headers=dict(headers or {}))

    def get(self, url, headers=None, timeout=None, **kw):
        return self._pop("GET", url, headers=dict(headers or {}))


class _FakeFilesColl:
    def __init__(self):
        self.docs: Dict[str, Dict[str, Any]] = {}

    async def insert_one(self, doc):
        self.docs[doc["id"]] = dict(doc)

    async def find_one(self, query):
        for d in self.docs.values():
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None

    async def update_one(self, query, update):
        for d in self.docs.values():
            if all(d.get(k) == v for k, v in query.items()):
                d.update(update.get("$set", {}))
                return
        raise KeyError("no match")

    def find(self, query, projection=None):
        rows = [dict(d) for d in self.docs.values()
                  if all(d.get(k) == v for k, v in query.items())]
        return _FakeCursor(rows)


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_a, **_k):
        return self

    async def to_list(self, n=None):
        return self.rows[: n or len(self.rows)]


# ═══════════════════════════════════════════════════════════════════
# fixtures
# ═══════════════════════════════════════════════════════════════════
@pytest.fixture(autouse=True)
def _reset_fs_state(monkeypatch):
    fs._reset_for_tests()
    monkeypatch.setenv("EMERGENT_LLM_KEY", "emergent-key-test")


@pytest.fixture
def rec(monkeypatch):
    r = _RequestsRecorder()
    monkeypatch.setattr(fs.requests, "post", r.post)
    monkeypatch.setattr(fs.requests, "put", r.put)
    monkeypatch.setattr(fs.requests, "get", r.get)
    return r


@pytest.fixture
def fake_files_coll(monkeypatch):
    coll = _FakeFilesColl()
    # Patch db.files on the router module (which imports ``db`` at module load).
    import routers.files as files_router
    monkeypatch.setattr(files_router.db, "files", coll, raising=False)
    return coll


@pytest.fixture
def app_client(monkeypatch, fake_files_coll):
    """FastAPI test client with a stubbed auth dependency via
    ``app.dependency_overrides`` (the correct FastAPI pattern — patching
    the module attribute post-import doesn't rebind the already-baked
    ``Depends(get_current_user)`` references)."""
    import routers.files as files_router
    from utils import get_current_user as real_get_current_user

    async def _stub_user():
        return {"id": "user-1", "tenant_id": "tenant-A",
                "role": "customer", "email": "c1@test"}

    a = FastAPI()
    a.include_router(files_router.router, prefix="/api")
    a.dependency_overrides[real_get_current_user] = _stub_user
    # Also override the download endpoint's inline helper so it
    # doesn't require a real JWT to resolve the query-param path.
    async def _stub_resolver(request, auth=None):
        return await _stub_user()
    monkeypatch.setattr(files_router, "_resolve_bearer_or_query_auth", _stub_resolver)
    return TestClient(a)


# ═══════════════════════════════════════════════════════════════════
# 1–4 · service-layer tests
# ═══════════════════════════════════════════════════════════════════
def test_init_storage_success_caches_key(rec):
    rec.queue_response(_FakeResp(200, {"storage_key": "sk-xxx"}))
    k = fs.init_storage()
    assert k == "sk-xxx"
    assert fs.is_storage_configured() is True
    # Second call — no additional POST.
    k2 = fs.init_storage()
    assert k2 == "sk-xxx"
    assert len(rec.calls) == 1


def test_init_storage_missing_env_key_disables_storage(rec, monkeypatch):
    monkeypatch.delenv("EMERGENT_LLM_KEY", raising=False)
    result = fs.init_storage()
    assert result is None
    assert fs.is_storage_configured() is False
    # No HTTP call fired.
    assert rec.calls == []


def test_put_object_success_returns_metadata(rec):
    rec.queue_response(
        _FakeResp(200, {"storage_key": "sk-1"}),
        _FakeResp(200, {"path": "poolscape-crm/t/g/x.png",
                         "size": 5, "etag": "aaa"}),
    )
    fs.init_storage()
    r = fs.put_object("poolscape-crm/t/g/x.png", b"hello", "image/png")
    assert r == {"path": "poolscape-crm/t/g/x.png", "size": 5, "etag": "aaa"}


def test_put_object_403_triggers_reinit_and_retry(rec):
    rec.queue_response(
        _FakeResp(200, {"storage_key": "sk-1"}),         # init
        _FakeResp(403, text_body="expired"),                # put 1 → 403
        _FakeResp(200, {"storage_key": "sk-2"}),         # re-init
        _FakeResp(200, {"path": "p", "size": 3,
                         "etag": "bbb"}),                          # put 2 → 200
    )
    fs.init_storage()
    r = fs.put_object("p", b"abc", "image/png")
    assert r["etag"] == "bbb"
    # 4 total calls: init, put, init, put.
    assert len(rec.calls) == 4
    assert fs._storage_key == "sk-2"


# ═══════════════════════════════════════════════════════════════════
# 5–15 · router tests
# ═══════════════════════════════════════════════════════════════════
def test_upload_endpoint_happy_path(rec, app_client, fake_files_coll):
    rec.queue_response(
        _FakeResp(200, {"storage_key": "sk-up"}),
        _FakeResp(200, {"path": "poolscape-crm/tenant-A/job/x.png",
                         "size": 4, "etag": "eee"}),
    )
    fs.init_storage()
    r = app_client.post(
        "/api/files/upload",
        files={"file": ("pic.png", b"\x89PNG", "image/png")},
        data={"purpose": "job_photo",
                 "linked_entity_type": "job", "linked_entity_id": "job-1"},
        headers={"Authorization": "Bearer stub"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"]
    assert body["url"] == f"/api/files/{body['id']}/download"
    assert body["content_type"] == "image/png"
    # Mongo doc inserted.
    assert body["id"] in fake_files_coll.docs
    doc = fake_files_coll.docs[body["id"]]
    assert doc["tenant_id"] == "tenant-A"
    assert doc["purpose"] == "job_photo"
    assert doc["linked_entity_id"] == "job-1"
    assert doc["is_deleted"] is False


def test_upload_rejects_over_size_limit(rec, app_client):
    rec.queue_response(_FakeResp(200, {"storage_key": "sk"}))
    fs.init_storage()
    big = b"x" * (fs.__dict__.get("_ignored", 0) + 26 * 1024 * 1024)
    r = app_client.post(
        "/api/files/upload",
        files={"file": ("big.pdf", big, "application/pdf")},
        headers={"Authorization": "Bearer stub"},
    )
    assert r.status_code == 413
    assert r.json()["detail"]["code"] == "FILE_TOO_LARGE"


def test_upload_rejects_wrong_mime(rec, app_client):
    rec.queue_response(_FakeResp(200, {"storage_key": "sk"}))
    fs.init_storage()
    r = app_client.post(
        "/api/files/upload",
        files={"file": ("note.txt", b"hello", "text/plain")},
        headers={"Authorization": "Bearer stub"},
    )
    assert r.status_code == 415
    assert r.json()["detail"]["code"] == "UNSUPPORTED_MIME"


def test_upload_requires_auth(rec, monkeypatch, fake_files_coll):
    """Isolated app WITHOUT the stub — verifies the real auth dep 401s."""
    rec.queue_response(_FakeResp(200, {"storage_key": "sk"}))
    fs.init_storage()
    import routers.files as files_router
    a = FastAPI()
    a.include_router(files_router.router, prefix="/api")
    c = TestClient(a)
    r = c.post(
        "/api/files/upload",
        files={"file": ("x.png", b"\x89PNG", "image/png")},
    )
    # HTTPBearer(auto_error=True) returns 403 by default; some setups
    # 401. Accept either as the "auth required" signal.
    assert r.status_code in (401, 403)


def test_download_serves_file_with_bearer_auth(rec, app_client, fake_files_coll):
    rec.queue_response(
        _FakeResp(200, {"storage_key": "sk-d"}),
        _FakeResp(200, {"path": "poolscape-crm/tenant-A/g/x.png",
                         "size": 3, "etag": "e"}),
        _FakeResp(200, content=b"PIX", headers={"Content-Type": "image/png"}),
    )
    fs.init_storage()
    up = app_client.post(
        "/api/files/upload",
        files={"file": ("x.png", b"PIX", "image/png")},
        headers={"Authorization": "Bearer stub"},
    )
    file_id = up.json()["id"]
    r = app_client.get(
        f"/api/files/{file_id}/download",
        headers={"Authorization": "Bearer stub"},
    )
    assert r.status_code == 200
    assert r.content == b"PIX"
    assert r.headers["content-type"].startswith("image/png")
    assert 'inline; filename="x.png"' in r.headers["content-disposition"]


def test_download_serves_file_with_query_param_auth(rec, app_client, fake_files_coll):
    rec.queue_response(
        _FakeResp(200, {"storage_key": "sk-q"}),
        _FakeResp(200, {"path": "poolscape-crm/tenant-A/g/y.pdf",
                         "size": 4, "etag": "q"}),
        _FakeResp(200, content=b"PDFD",
                    headers={"Content-Type": "application/pdf"}),
    )
    fs.init_storage()
    up = app_client.post(
        "/api/files/upload",
        files={"file": ("y.pdf", b"PDFD", "application/pdf")},
        headers={"Authorization": "Bearer stub"},
    )
    file_id = up.json()["id"]
    r = app_client.get(f"/api/files/{file_id}/download?auth=any-non-empty")
    assert r.status_code == 200
    assert r.content == b"PDFD"


def test_download_wrong_tenant_returns_404(rec, app_client, fake_files_coll):
    # Insert a doc for tenant B directly.
    import routers.files as files_router
    fake_files_coll.docs["file-B"] = {
        "id": "file-B", "tenant_id": "tenant-B",
        "storage_path": "poolscape-crm/tenant-B/g/z.png",
        "content_type": "image/png", "original_filename": "z.png",
        "size": 3, "is_deleted": False, "uploaded_by_user_id": "u-B",
    }
    r = app_client.get("/api/files/file-B/download",
                          headers={"Authorization": "Bearer stub"})
    assert r.status_code == 404


def test_download_soft_deleted_returns_404(rec, app_client, fake_files_coll):
    fake_files_coll.docs["file-S"] = {
        "id": "file-S", "tenant_id": "tenant-A",
        "storage_path": "p", "content_type": "image/png",
        "original_filename": "s.png", "size": 3,
        "is_deleted": True, "uploaded_by_user_id": "user-1",
    }
    r = app_client.get("/api/files/file-S/download",
                          headers={"Authorization": "Bearer stub"})
    assert r.status_code == 404


def test_delete_soft_deletes(rec, app_client, fake_files_coll):
    fake_files_coll.docs["file-D"] = {
        "id": "file-D", "tenant_id": "tenant-A",
        "storage_path": "p", "content_type": "image/png",
        "original_filename": "d.png", "size": 3,
        "is_deleted": False, "uploaded_by_user_id": "user-1",
    }
    r = app_client.post("/api/files/file-D/delete",
                           headers={"Authorization": "Bearer stub"})
    assert r.status_code == 204
    assert fake_files_coll.docs["file-D"]["is_deleted"] is True
    assert fake_files_coll.docs["file-D"]["deleted_at"] is not None
    # NO storage call fired for a delete.
    assert not any("objects/" in c.get("url", "") for c in rec.calls)


def test_delete_wrong_user_forbidden(rec, app_client, fake_files_coll):
    fake_files_coll.docs["file-X"] = {
        "id": "file-X", "tenant_id": "tenant-A",
        "storage_path": "p", "content_type": "image/png",
        "original_filename": "x.png", "size": 3,
        "is_deleted": False, "uploaded_by_user_id": "some-other-user",
    }
    r = app_client.post("/api/files/file-X/delete",
                           headers={"Authorization": "Bearer stub"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "NOT_UPLOADER"


def test_list_by_entity(rec, app_client, fake_files_coll):
    # Two matching, one different entity, one different tenant.
    fake_files_coll.docs["f1"] = {"id": "f1", "tenant_id": "tenant-A",
                                        "linked_entity_type": "job", "linked_entity_id": "job-1",
                                        "is_deleted": False, "created_at": "2026-01-01T00:00:00Z"}
    fake_files_coll.docs["f2"] = {"id": "f2", "tenant_id": "tenant-A",
                                        "linked_entity_type": "job", "linked_entity_id": "job-1",
                                        "is_deleted": False, "created_at": "2026-01-02T00:00:00Z"}
    fake_files_coll.docs["f3"] = {"id": "f3", "tenant_id": "tenant-A",
                                        "linked_entity_type": "job", "linked_entity_id": "job-2",
                                        "is_deleted": False, "created_at": "2026-01-03T00:00:00Z"}
    fake_files_coll.docs["f4"] = {"id": "f4", "tenant_id": "tenant-B",
                                        "linked_entity_type": "job", "linked_entity_id": "job-1",
                                        "is_deleted": False, "created_at": "2026-01-04T00:00:00Z"}
    r = app_client.get(
        "/api/files?linked_entity_type=job&linked_entity_id=job-1",
        headers={"Authorization": "Bearer stub"},
    )
    assert r.status_code == 200
    body = r.json()
    ids = sorted(x["id"] for x in body["items"])
    assert ids == ["f1", "f2"]
    assert body["count"] == 2
    for row in body["items"]:
        assert row["url"] == f"/api/files/{row['id']}/download"
