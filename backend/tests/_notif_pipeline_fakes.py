"""Feb-2026 · Service Notifications Pipeline · shared test fakes.

Motor-compatible in-memory stubs used by every
``test_service_reminder_*.py`` and ``test_reschedule_*.py`` file.
Kept in the ``tests/`` folder so pytest picks them up as an
importable module; the leading underscore blocks pytest from
treating them as test cases.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _matches(row: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for k, v in query.items():
        if k == "$or":
            if not any(_matches(row, sub) for sub in v):
                return False
            continue
        if k == "$and":
            if not all(_matches(row, sub) for sub in v):
                return False
            continue
        if isinstance(v, dict):
            if "$exists" in v:
                if v["$exists"] != (k in row):
                    return False
                continue
            if "$in" in v:
                if row.get(k) not in v["$in"]:
                    return False
                continue
            if "$nin" in v:
                if row.get(k) in v["$nin"]:
                    return False
                continue
            if "$ne" in v:
                if row.get(k) == v["$ne"]:
                    return False
                continue
            return False
        if row.get(k) != v:
            return False
    return True


class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])
        self.inserts: List[Dict[str, Any]] = []
        self.updates: List[Dict[str, Any]] = []

    async def find_one(self, query, projection=None):  # noqa: ARG002
        for row in self.rows:
            if _matches(row, query):
                return dict(row)
        return None

    async def insert_one(self, doc):
        self.inserts.append(dict(doc))
        self.rows.append(dict(doc))
        return type("R", (), {"inserted_id": doc.get("id")})()

    async def update_one(self, filt, update):
        for row in self.rows:
            if _matches(row, filt):
                self.updates.append({"filter": dict(filt),
                                       "update": dict(update)})
                if "$set" in update:
                    row.update(update["$set"])
                return type("R", (), {"modified_count": 1})()
        return type("R", (), {"modified_count": 0})()

    async def count_documents(self, query):
        return sum(1 for r in self.rows if _matches(r, query))

    def find(self, query=None, projection=None):  # noqa: ARG002
        outer = self
        q = query or {}

        class _Cursor:
            def __init__(self):
                self._rows = [dict(r) for r in outer.rows if _matches(r, q)]

            def __aiter__(self):
                self._it = iter(self._rows)
                return self

            async def __anext__(self):
                try:
                    return next(self._it)
                except StopIteration:
                    raise StopAsyncIteration

            def sort(self, *_a, **_k):
                return self

            async def to_list(self, _n=None):
                return list(self._rows)

        return _Cursor()


class _DB:
    """Bundle collection stubs used by the pipeline module."""

    def __init__(
        self, *, jobs=None, customers=None, tenants=None,
        notifications_sent_log=None, communication_opt_outs=None,
    ):
        self.jobs = _Coll(jobs)
        self.customers = _Coll(customers)
        self.tenants = _Coll(tenants)
        self.notifications_sent_log = _Coll(notifications_sent_log)
        self.communication_opt_outs = _Coll(communication_opt_outs)


class _EmailCapture:
    """Async callable mimicking ``comms_email_adapter.send_email``."""

    def __init__(self, ret_status: str = "mocked"):
        self.calls: List[Dict[str, Any]] = []
        self._status = ret_status

    async def __call__(self, *args, **kwargs):
        self.calls.append(dict(kwargs))
        return {"status": self._status, "provider_id": "mock"}


class _SMSCapture:
    """Async callable mimicking ``comms_sms_adapter.send_sms``."""

    def __init__(self, ret_status: str = "mocked"):
        self.calls: List[Dict[str, Any]] = []
        self._status = ret_status

    async def __call__(self, *args, **kwargs):
        self.calls.append(dict(kwargs))
        return {"status": self._status, "provider_id": "mock",
                 "character_count": 0, "segment_count": 0}
