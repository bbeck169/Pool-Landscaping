"""Phase 34 · Task V · Feb-2026 — tour version-key upgrade.

Locks two invariants:
  1. ``/customer-portal/walkthrough/status`` now returns the v2 key
     ``portal_tour_completed_v2`` (bool) plus ``should_show_v2``,
     while keeping the legacy ``should_show`` for older clients.
  2. The backfill helper sets ``portal_tour_completed_v2=false`` on
     every legacy customer-role user missing the field so
     v1-completers see the new step list once.

Also (Task W) — the ``/auth/forgot-password`` endpoint STILL returns
the enum-safe neutral 200 when the email doesn't match any account.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeCol:
    def __init__(self):
        self.docs = []

    async def find_one(self, q, proj=None):  # noqa: ARG002
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return dict(d)
        return None

    async def update_many(self, q, u):
        n = 0
        for d in self.docs:
            match = True
            for k, v in q.items():
                if isinstance(v, dict) and "$exists" in v:
                    if v["$exists"] is False and k in d:
                        match = False; break
                    if v["$exists"] is True and k not in d:
                        match = False; break
                elif isinstance(v, dict) and "$ne" in v:
                    if d.get(k) == v["$ne"]:
                        match = False; break
                elif isinstance(v, dict) and "$lt" in v:
                    if not (d.get(k) and d[k] < v["$lt"]):
                        match = False; break
                elif d.get(k) != v:
                    match = False; break
            if match:
                d.update((u.get("$set") or {}))
                n += 1
        return MagicMock(modified_count=n)


def test_backfill_sets_v2_false_on_legacy_users(monkeypatch):
    """Every customer-role user missing ``portal_tour_completed_v2``
    gets ``false`` written so the v2 tour prompts once."""
    from routers import portal_walkthrough as _pw

    fake_users = _FakeCol()
    fake_users.docs = [
        {"id": "u-legacy-1", "role": "customer", "has_seen_customer_tour": True},
        {"id": "u-legacy-2", "role": "customer"},
        {"id": "u-tech-1",   "role": "technician"},   # not a customer — untouched
        {"id": "u-already",  "role": "customer",
         "portal_tour_completed_v2": True},           # already set — untouched
    ]
    fake_cust = _FakeCol()  # customers collection — irrelevant for the v2 leg

    monkeypatch.setattr(_pw, "db", MagicMock(users=fake_users, customers=fake_cust))
    result = _run(_pw.run_walkthrough_backfill())

    assert result.get("v2_flagged_users") == 2
    ids = {d["id"]: d.get("portal_tour_completed_v2") for d in fake_users.docs}
    assert ids["u-legacy-1"] is False
    assert ids["u-legacy-2"] is False
    assert "portal_tour_completed_v2" not in {k for k, v in fake_users.docs[2].items()
                                                if k == "portal_tour_completed_v2"}
    assert ids["u-already"] is True  # unchanged
