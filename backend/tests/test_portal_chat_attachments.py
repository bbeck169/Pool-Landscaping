"""Phase B2 · Feb 2026 — Portal chat attachment ownership + hydration tests.

Direct-call the router functions (not HTTP) — matches the pattern
used by other portal_chats coverage (see phase20b tests).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.inserted: List[Dict[str, Any]] = []

    async def find_one(self, q, proj=None):
        for d in self.docs:
            ok = all(d.get(k) == v for k, v in q.items()
                      if not isinstance(v, dict))
            if ok:
                return dict(d)
        return None

    def find(self, q, proj=None):
        matched = []
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if isinstance(v, dict) and "$in" in v:
                    if d.get(k) not in v["$in"]:
                        ok = False; break
                elif isinstance(v, dict) and "$ne" in v:
                    if d.get(k) == v["$ne"]:
                        ok = False; break
                elif d.get(k) != v:
                    ok = False; break
            if ok:
                matched.append(dict(d))
        class _Cursor:
            def __init__(self, rows): self.rows = rows
            def sort(self, *_a, **_k): return self
            async def to_list(self, _n): return self.rows
        return _Cursor(matched)

    async def insert_one(self, doc):
        self.inserted.append(dict(doc))
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id="fake")

    async def update_one(self, *_a, **_k):
        return SimpleNamespace(matched_count=1, modified_count=1)


@pytest.fixture
def fake_db():
    TENANT = "t-1"
    CUSTOMER_A = "cust-A"
    CUSTOMER_B = "cust-B"
    USER_A = "user-A"
    JOB_A = "job-A"
    JOB_B = "job-B"

    files = _FakeCollection([
        # File 1: linked to customer A → A can attach
        {"id": "f-cust-A", "tenant_id": TENANT,
         "linked_entity_type": "customer", "linked_entity_id": CUSTOMER_A,
         "original_filename": "cust-a.pdf", "content_type": "application/pdf",
         "size": 1024, "uploaded_by_user_id": USER_A, "is_deleted": False},
        # File 2: linked to a job owned by A → A can attach
        {"id": "f-job-A", "tenant_id": TENANT,
         "linked_entity_type": "job", "linked_entity_id": JOB_A,
         "original_filename": "job-a.png", "content_type": "image/png",
         "size": 2048, "uploaded_by_user_id": USER_A, "is_deleted": False},
        # File 3: linked to customer B → A must NOT be able to attach
        {"id": "f-cust-B", "tenant_id": TENANT,
         "linked_entity_type": "customer", "linked_entity_id": CUSTOMER_B,
         "original_filename": "cust-b.pdf", "content_type": "application/pdf",
         "size": 512, "uploaded_by_user_id": "user-B", "is_deleted": False},
        # File 4: linked to a job owned by B → A must NOT be able to attach
        {"id": "f-job-B", "tenant_id": TENANT,
         "linked_entity_type": "job", "linked_entity_id": JOB_B,
         "original_filename": "job-b.png", "content_type": "image/png",
         "size": 4096, "uploaded_by_user_id": "user-B", "is_deleted": False},
    ])
    jobs = _FakeCollection([
        {"id": JOB_A, "tenant_id": TENANT, "customer_id": CUSTOMER_A},
        {"id": JOB_B, "tenant_id": TENANT, "customer_id": CUSTOMER_B},
    ])
    chats = _FakeCollection([
        {"id": "chat-A", "tenant_id": TENANT, "customer_id": CUSTOMER_A,
         "subject": "Hi", "last_message_at": "2026-02-01T00:00:00Z",
         "unread_by_admin": 0, "unread_by_customer": 0,
         "assigned_admin_id": None},
    ])
    messages = _FakeCollection([])
    users = _FakeCollection([])
    # Phase K8 · Feb-2026 — resolver now reads db.customers to derive
    # the canonical bubble sender_name.  Seed a customer row for A so
    # the existing attachment tests keep exercising the write path.
    customers = _FakeCollection([
        {"id": CUSTOMER_A, "tenant_id": TENANT, "name": "Customer A"},
        {"id": CUSTOMER_B, "tenant_id": TENANT, "name": "Customer B"},
    ])

    return SimpleNamespace(
        files=files, jobs=jobs,
        portal_chats=chats, portal_chat_messages=messages,
        users=users, customers=customers,
        _consts={
            "TENANT": TENANT, "CUSTOMER_A": CUSTOMER_A,
            "CUSTOMER_B": CUSTOMER_B, "USER_A": USER_A,
            "JOB_A": JOB_A, "JOB_B": JOB_B,
        },
    )


def _tenant(fake_db):
    return {"id": fake_db._consts["TENANT"]}


def _customer_user(fake_db, cid_key="CUSTOMER_A", uid_key="USER_A"):
    return {
        "id": fake_db._consts[uid_key],
        "role": "customer",
        "customer_id": fake_db._consts[cid_key],
        "name": "Customer A",
    }


def _import_router(fake_db):
    """Import the router module under a monkey-patched ``db``."""
    with patch("config.db", fake_db):
        # reload to pick up patched db module-level binding
        import importlib
        import routers.portal_chats as portal_chats
        import services.chat_attachment_hydration as hydrator
        importlib.reload(hydrator)
        importlib.reload(portal_chats)
        return portal_chats


def test_portal_chat_send_message_with_own_customer_file_success(fake_db):
    m = _import_router(fake_db)
    body = m.MessagePostIn(body="hello", attachment_ids=["f-cust-A"])
    result = _run(m.post_message("chat-A", body,
                                   user=_customer_user(fake_db),
                                   tenant=_tenant(fake_db)))
    assert result["attachment_ids"] == ["f-cust-A"]
    assert result["attachments"][0]["id"] == "f-cust-A"
    assert result["attachments"][0]["signed_url"].endswith("/download")
    assert len(fake_db.portal_chat_messages.inserted) == 1


def test_portal_chat_send_message_with_own_job_file_success(fake_db):
    m = _import_router(fake_db)
    body = m.MessagePostIn(body="see attached", attachment_ids=["f-job-A"])
    result = _run(m.post_message("chat-A", body,
                                   user=_customer_user(fake_db),
                                   tenant=_tenant(fake_db)))
    assert result["attachment_ids"] == ["f-job-A"]
    assert result["attachments"][0]["mime"] == "image/png"


def test_portal_chat_send_message_with_other_customer_file_403(fake_db):
    m = _import_router(fake_db)
    from fastapi import HTTPException
    body = m.MessagePostIn(body="x", attachment_ids=["f-cust-B"])
    with pytest.raises(HTTPException) as exc:
        _run(m.post_message("chat-A", body,
                              user=_customer_user(fake_db),
                              tenant=_tenant(fake_db)))
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "not_your_attachment"
    assert exc.value.detail["file_id"] == "f-cust-B"
    assert len(fake_db.portal_chat_messages.inserted) == 0


def test_portal_chat_send_message_with_other_job_file_403(fake_db):
    m = _import_router(fake_db)
    from fastapi import HTTPException
    body = m.MessagePostIn(body="x", attachment_ids=["f-job-B"])
    with pytest.raises(HTTPException) as exc:
        _run(m.post_message("chat-A", body,
                              user=_customer_user(fake_db),
                              tenant=_tenant(fake_db)))
    assert exc.value.status_code == 403
    assert exc.value.detail["file_id"] == "f-job-B"
    assert len(fake_db.portal_chat_messages.inserted) == 0


def test_portal_chat_list_returns_signed_urls(fake_db):
    m = _import_router(fake_db)
    # First send a message with one attachment
    body = m.MessagePostIn(body="hello", attachment_ids=["f-cust-A"])
    _run(m.post_message("chat-A", body,
                          user=_customer_user(fake_db),
                          tenant=_tenant(fake_db)))
    # Now GET the thread
    result = _run(m.get_messages("chat-A",
                                   user=_customer_user(fake_db),
                                   tenant=_tenant(fake_db)))
    msgs = result["messages"]
    assert len(msgs) == 1
    atts = msgs[0]["attachments"]
    assert len(atts) == 1
    assert atts[0]["signed_url"] == "/api/files/f-cust-A/download"
    assert atts[0]["filename"] == "cust-a.pdf"
    assert atts[0]["mime"] == "application/pdf"
    assert atts[0]["size"] == 1024


def test_portal_chat_send_without_attachments_still_works(fake_db):
    """Regression guard — plain text-only message must still send."""
    m = _import_router(fake_db)
    body = m.MessagePostIn(body="just text")
    result = _run(m.post_message("chat-A", body,
                                   user=_customer_user(fake_db),
                                   tenant=_tenant(fake_db)))
    assert result["body"] == "just text"
    assert result["attachment_ids"] == []
    assert result["attachments"] == []
