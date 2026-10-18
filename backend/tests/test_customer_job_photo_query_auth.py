"""TD-67 · Feb-2026 — Customer job-photo stream `?auth=` fallback.

Pre-TD-67, ``GET /api/customers/me/jobs/{jid}/photos/{photo_id}``
required a Bearer ``Authorization`` header, which ``<img src>`` can
never attach — so the portal service-report detail page's "Job
photos" grid rendered every tile as a broken image on prod. The
fix mirrors the pre-existing ``routers/files.py::
_resolve_bearer_or_query_auth`` pattern: accept EITHER the Bearer
header OR a ``?auth=<token>`` query param, so ``<img src>`` with a
``?auth=<token>`` suffix loads normally while existing scripted
clients (curl / mobile app) continue to use the header path.

This file pins the three-case contract directly against the
``stream_customer_job_photo`` handler.  No live Mongo required —
``db`` is monkeypatched with a tiny async in-memory stub that
mirrors the ``find_one`` + projection surface the handler calls.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import jwt
import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.requests import Request


# ═══════════════════════════════════════════════════════════════════
# Minimal Mongo stub — only ``find_one`` on ``users`` + ``jobs`` is
# exercised by the handler + its ``get_current_user`` dependency.
# ═══════════════════════════════════════════════════════════════════
class _Collection:
    def __init__(self, rows: List[Dict[str, Any]]):
        self.rows = list(rows)

    async def find_one(self, query: dict, _projection: dict = None):
        for r in self.rows:
            ok = True
            for k, v in query.items():
                rv = r.get(k)
                if isinstance(v, dict) and "$ne" in v:
                    if rv == v["$ne"]:
                        ok = False
                        break
                elif rv != v:
                    ok = False
                    break
            if ok:
                return r
        return None


class _DB:
    def __init__(self, users: List[dict], jobs: List[dict]):
        self.users = _Collection(users)
        self.jobs = _Collection(jobs)


# ═══════════════════════════════════════════════════════════════════
# Fixture — a signed JWT for a seeded portal customer.
# ═══════════════════════════════════════════════════════════════════
_TENANT_ID = "t_td67"
_CUST_ID = "cust_td67"
_USER_ID = "user_td67"
_JOB_ID = "job_td67"
_PHOTO_ID = "photo_td67"


def _make_token(uid: str = _USER_ID) -> str:
    from utils import JWT_SECRET, JWT_ALGO
    exp = datetime.now(timezone.utc) + timedelta(minutes=5)
    return jwt.encode({"sub": uid, "exp": exp}, JWT_SECRET, algorithm=JWT_ALGO)


def _make_request(headers: Dict[str, str] = None) -> Request:
    """Build a Starlette ``Request`` with the given header dict.

    The handler only reads ``request.headers.get('authorization')``
    so we can skip the ASGI scope minutiae.
    """
    raw: List[tuple] = []
    for k, v in (headers or {}).items():
        raw.append((k.lower().encode(), v.encode()))
    scope = {
        "type": "http", "method": "GET", "path": "/", "raw_path": b"/",
        "query_string": b"", "headers": raw, "client": ("127.0.0.1", 0),
        "server": ("test", 80),
    }
    return Request(scope)


def _seed_db() -> _DB:
    """Build a minimal in-memory DB stub with one user + one job + one photo."""
    photo = {
        "id": _PHOTO_ID,
        # Embedded base64 data URI so the handler takes the
        # fallback branch (no S3 import required for this contract
        # test). The handler requires the ``data:...;base64,...``
        # prefix — raw base64 without the header surfaces as "503
        # no_storage_backing".
        "data": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
        "mime": "image/png",
        "is_deleted": False,
    }
    return _DB(
        users=[{
            "id": _USER_ID, "tenant_id": _TENANT_ID,
            "role": "customer", "customer_id": _CUST_ID,
            "active": True, "deleted_at": None,
        }],
        jobs=[{
            "id": _JOB_ID, "tenant_id": _TENANT_ID,
            "customer_id": _CUST_ID,
            "photos": [photo],
        }],
    )


@pytest.fixture
def _handler(monkeypatch):
    """Yield the handler coroutine with a monkeypatched ``db``."""
    import routers.service_reports as sr

    db_stub = _seed_db()
    monkeypatch.setattr(sr, "db", db_stub)

    # Also monkeypatch the ``db`` used by ``get_current_user`` so
    # the JWT ``users.find_one`` lookup resolves to our stub user.
    import utils as _utils
    monkeypatch.setattr(_utils, "db", db_stub)

    return sr.stream_customer_job_photo


# ═══════════════════════════════════════════════════════════════════
# 1 · Bearer header → 200 (regression lock for scripted clients).
# ═══════════════════════════════════════════════════════════════════
def test_bearer_header_streams_photo(_handler):
    handler = _handler
    token = _make_token()
    req = _make_request({"authorization": f"Bearer {token}"})

    resp = asyncio.run(handler(
        jid=_JOB_ID, photo_id=_PHOTO_ID, request=req, auth=None,
    ))
    assert resp.status_code == 200
    assert resp.media_type == "image/png"
    assert len(resp.body) > 0


# ═══════════════════════════════════════════════════════════════════
# 2 · ``?auth=<token>`` query param → 200 (the <img src> use case).
# ═══════════════════════════════════════════════════════════════════
def test_query_auth_param_streams_photo(_handler):
    handler = _handler
    token = _make_token()
    req = _make_request({})  # no Authorization header

    resp = asyncio.run(handler(
        jid=_JOB_ID, photo_id=_PHOTO_ID, request=req, auth=token,
    ))
    assert resp.status_code == 200
    assert resp.media_type == "image/png"


# ═══════════════════════════════════════════════════════════════════
# 3 · Missing both → 401 not_authenticated.
# ═══════════════════════════════════════════════════════════════════
def test_missing_both_raises_401(_handler):
    handler = _handler
    req = _make_request({})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler(
            jid=_JOB_ID, photo_id=_PHOTO_ID, request=req, auth=None,
        ))
    assert exc.value.status_code == 401
    assert exc.value.detail == "not_authenticated"
