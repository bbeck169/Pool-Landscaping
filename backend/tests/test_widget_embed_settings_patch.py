"""Feb-2026 F4 Enhancement — ``PATCH /api/tenants/settings/widget-embed``.

Endpoint contract:
  * Admin / super_admin only (403 otherwise).
  * Fields are nested under ``tenant.settings.*`` so the F4 auto-
    enqueue helper (``services/public_checkin_enqueue.py``) picks
    up the flag from the same place it already reads.
  * Idempotency + cross-tenant safety: the caller's own ``tenant_id``
    is authoritative — nothing in the body can retarget another
    tenant.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest
from fastapi import HTTPException

from routers import tenants as tenants_router


class _FakeColl:
    def __init__(self, rows=None):
        self._rows = list(rows or [])
        self.update_calls = []

    async def find_one(self, q, projection=None):
        for r in self._rows:
            if all(r.get(k) == v for k, v in q.items()):
                return dict(r)
        return None

    async def update_one(self, q, upd):
        self.update_calls.append({"q": dict(q), "upd": dict(upd)})
        set_ops = upd.get("$set", {})
        for r in self._rows:
            if all(r.get(k) == v for k, v in q.items()):
                for path, value in set_ops.items():
                    if path.startswith("settings."):
                        r.setdefault("settings", {})
                        r["settings"][path.split(".", 1)[1]] = value
                    else:
                        r[path] = value
                break
        return type("R", (), {"matched_count": 1, "modified_count": 1})()


class _FakeDb:
    def __init__(self, tenants):
        self.tenants = _FakeColl(tenants)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _admin(user_id="u-1", tenant_id="t-1"):
    return {"id": user_id, "tenant_id": tenant_id, "role": "admin"}


def test_patch_widget_embed_flips_auto_enqueue_on(monkeypatch):
    tenants_coll = [{"id": "t-1", "settings": {}}]
    fake = _FakeDb(tenants_coll)
    monkeypatch.setattr(tenants_router, "db", fake)

    body = tenants_router.WidgetEmbedSettingsUpdate(
        auto_enqueue_public_checkins=True,
    )
    result = _run(tenants_router.patch_widget_embed_settings(
        body=body, user=_admin(),
    ))
    assert result["auto_enqueue_public_checkins"] is True
    assert tenants_coll[0]["settings"]["auto_enqueue_public_checkins"] is True


def test_patch_widget_embed_stamps_dismissed_at(monkeypatch):
    tenants_coll = [{"id": "t-1", "settings": {}}]
    fake = _FakeDb(tenants_coll)
    monkeypatch.setattr(tenants_router, "db", fake)

    body = tenants_router.WidgetEmbedSettingsUpdate(
        widget_embed_seo_prompt_dismissed_at="2026-02-14T10:00:00+00:00",
    )
    result = _run(tenants_router.patch_widget_embed_settings(
        body=body, user=_admin(),
    ))
    assert (result["widget_embed_seo_prompt_dismissed_at"]
             == "2026-02-14T10:00:00+00:00")
    assert (tenants_coll[0]["settings"]
             ["widget_embed_seo_prompt_dismissed_at"]
             == "2026-02-14T10:00:00+00:00")


def test_patch_widget_embed_rejects_non_admin(monkeypatch):
    tenants_coll = [{"id": "t-1", "settings": {}}]
    fake = _FakeDb(tenants_coll)
    monkeypatch.setattr(tenants_router, "db", fake)

    body = tenants_router.WidgetEmbedSettingsUpdate(
        auto_enqueue_public_checkins=True,
    )
    for role in ("technician", "manager", "customer", "portal_customer"):
        user = _admin()
        user["role"] = role
        with pytest.raises(HTTPException) as exc:
            _run(tenants_router.patch_widget_embed_settings(
                body=body, user=user,
            ))
        assert exc.value.status_code == 403


def test_patch_widget_embed_rejects_empty_body(monkeypatch):
    tenants_coll = [{"id": "t-1", "settings": {}}]
    fake = _FakeDb(tenants_coll)
    monkeypatch.setattr(tenants_router, "db", fake)

    body = tenants_router.WidgetEmbedSettingsUpdate()
    with pytest.raises(HTTPException) as exc:
        _run(tenants_router.patch_widget_embed_settings(
            body=body, user=_admin(),
        ))
    assert exc.value.status_code == 400


def test_patch_widget_embed_writes_only_to_callers_tenant(monkeypatch):
    """Cross-tenant safety — the endpoint MUST use the caller's
    tenant_id, never a body-supplied id. The body Pydantic model
    doesn't even have a tenant field, so this test proves the
    update filter is ``{"id": <caller tenant>}``.
    """
    tenants_coll = [
        {"id": "t-mine", "settings": {}},
        {"id": "t-other", "settings": {}},
    ]
    fake = _FakeDb(tenants_coll)
    monkeypatch.setattr(tenants_router, "db", fake)

    body = tenants_router.WidgetEmbedSettingsUpdate(
        auto_enqueue_public_checkins=True,
    )
    _run(tenants_router.patch_widget_embed_settings(
        body=body, user=_admin(tenant_id="t-mine"),
    ))
    # Only the caller's tenant row must be mutated.
    assert tenants_coll[0]["settings"].get("auto_enqueue_public_checkins") is True
    assert tenants_coll[1]["settings"] == {}
    # Verify the update filter itself was ``{"id": "t-mine"}``.
    assert fake.tenants.update_calls[0]["q"] == {"id": "t-mine"}


# ── GET counterpart · Feb-2026 ──────────────────────────────────
class _FakeJobsColl:
    """Minimal jobs collection double for the eligibility probe."""
    def __init__(self, rows):
        self._rows = list(rows)

    async def find_one(self, q, projection=None):
        cutoff = (q.get("completed_at") or {}).get("$gte")
        for r in self._rows:
            if r.get("tenant_id") != q.get("tenant_id"):
                continue
            if r.get("status") != q.get("status"):
                continue
            if cutoff and (r.get("completed_at") or "") < cutoff:
                continue
            return dict(r)
        return None


class _FakeDbWithJobs:
    def __init__(self, tenants, jobs=None):
        self.tenants = _FakeColl(tenants)
        self.jobs = _FakeJobsColl(jobs or [])


def test_get_widget_embed_prompt_true_when_flag_off_and_recent_job(monkeypatch):
    from datetime import datetime, timezone, timedelta
    recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    tenants_coll = [{"id": "t-1", "settings": {}}]
    fake = _FakeDbWithJobs(tenants_coll, jobs=[
        {"tenant_id": "t-1", "status": "completed",
         "completed_at": recent},
    ])
    monkeypatch.setattr(tenants_router, "db", fake)
    tenant = {"id": "t-1", "settings": {}}
    result = _run(tenants_router.get_widget_embed_settings(
        user=_admin(), tenant=tenant,
    ))
    assert result["should_show_seo_prompt"] is True
    assert result["has_recent_completed_jobs"] is True
    assert result["auto_enqueue_public_checkins"] is False


def test_get_widget_embed_prompt_false_when_flag_on(monkeypatch):
    from datetime import datetime, timezone, timedelta
    recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    tenants_coll = [{"id": "t-1",
                       "settings": {"auto_enqueue_public_checkins": True}}]
    fake = _FakeDbWithJobs(tenants_coll, jobs=[
        {"tenant_id": "t-1", "status": "completed",
         "completed_at": recent},
    ])
    monkeypatch.setattr(tenants_router, "db", fake)
    tenant = {"id": "t-1",
               "settings": {"auto_enqueue_public_checkins": True}}
    result = _run(tenants_router.get_widget_embed_settings(
        user=_admin(), tenant=tenant,
    ))
    assert result["should_show_seo_prompt"] is False


def test_get_widget_embed_prompt_false_when_already_dismissed(monkeypatch):
    from datetime import datetime, timezone, timedelta
    recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    tenants_coll = [{"id": "t-1",
                       "settings": {"widget_embed_seo_prompt_dismissed_at":
                                     "2026-02-10T00:00:00+00:00"}}]
    fake = _FakeDbWithJobs(tenants_coll, jobs=[
        {"tenant_id": "t-1", "status": "completed",
         "completed_at": recent},
    ])
    monkeypatch.setattr(tenants_router, "db", fake)
    tenant = {"id": "t-1",
               "settings": {"widget_embed_seo_prompt_dismissed_at":
                             "2026-02-10T00:00:00+00:00"}}
    result = _run(tenants_router.get_widget_embed_settings(
        user=_admin(), tenant=tenant,
    ))
    assert result["should_show_seo_prompt"] is False


def test_get_widget_embed_prompt_false_when_no_recent_job(monkeypatch):
    tenants_coll = [{"id": "t-1", "settings": {}}]
    fake = _FakeDbWithJobs(tenants_coll, jobs=[])
    monkeypatch.setattr(tenants_router, "db", fake)
    tenant = {"id": "t-1", "settings": {}}
    result = _run(tenants_router.get_widget_embed_settings(
        user=_admin(), tenant=tenant,
    ))
    assert result["should_show_seo_prompt"] is False
    assert result["has_recent_completed_jobs"] is False


def test_get_widget_embed_rejects_tech(monkeypatch):
    tenants_coll = [{"id": "t-1", "settings": {}}]
    fake = _FakeDbWithJobs(tenants_coll)
    monkeypatch.setattr(tenants_router, "db", fake)
    user = _admin(); user["role"] = "technician"
    with pytest.raises(HTTPException) as exc:
        _run(tenants_router.get_widget_embed_settings(
            user=user, tenant={"id": "t-1"},
        ))
    assert exc.value.status_code == 403
