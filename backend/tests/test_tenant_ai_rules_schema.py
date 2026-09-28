"""MTH-A · Feb-2026 — Index bootstrap contract tests.

Locks:

* ``ensure_tenant_ai_rules_indexes`` registers the four required
  indexes on the three collections.
* The tenant-id index on ``tenant_ai_rules`` is UNIQUE.
* The revisions index sorts DESCENDING on ``revision_number``.
* The platform-defaults ``key`` index is UNIQUE.

We inspect the ``create_indexes`` invocations against a recording
DB stub instead of hitting a real Mongo — the migration itself is
Motor-agnostic (accepts any DB with the right coroutine surface).
"""
from __future__ import annotations

import asyncio

from services.tenant_ai_rules.indexes import (
    ensure_tenant_ai_rules_indexes,
)


class _RecordingColl:
    def __init__(self):
        self.calls = []

    async def create_indexes(self, models):
        self.calls.append(list(models))


class _RecordingDB:
    def __init__(self):
        self._colls = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._colls.setdefault(name, _RecordingColl())


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _index_by_name(coll, name):
    for call in coll.calls:
        for model in call:
            if model.document.get("name") == name:
                return model.document
    return None


def test_tenant_ai_rules_unique_index_registered():
    db = _RecordingDB()
    _run(ensure_tenant_ai_rules_indexes(db))
    idx = _index_by_name(db.tenant_ai_rules,
                          "tenant_ai_rules_tenant_id_unique")
    assert idx is not None
    assert idx.get("unique") is True
    assert idx.get("background") is True


def test_tenant_ai_rules_last_updated_index_registered():
    db = _RecordingDB()
    _run(ensure_tenant_ai_rules_indexes(db))
    idx = _index_by_name(db.tenant_ai_rules,
                          "tenant_ai_rules_last_updated_at_bg")
    assert idx is not None
    assert idx.get("unique") is not True


def test_revisions_index_sorts_desc_on_revision_number():
    db = _RecordingDB()
    _run(ensure_tenant_ai_rules_indexes(db))
    idx = _index_by_name(db.tenant_ai_rules_revisions,
                          "tenant_ai_rules_revisions_tenant_rev_bg")
    assert idx is not None
    key = idx.get("key")
    assert key is not None
    # PyMongo represents ``key`` as a SON — iterate to inspect.
    keys = list(key.items()) if hasattr(key, "items") else list(key)
    assert keys[0][0] == "tenant_id"
    assert keys[0][1] == 1                                        # asc
    assert keys[1][0] == "revision_number"
    assert keys[1][1] == -1                                       # desc


def test_platform_defaults_key_index_unique():
    db = _RecordingDB()
    _run(ensure_tenant_ai_rules_indexes(db))
    idx = _index_by_name(db.platform_ai_rule_defaults,
                          "platform_ai_rule_defaults_key_unique")
    assert idx is not None
    assert idx.get("unique") is True


def test_ensure_indexes_idempotent():
    """Re-running the bootstrap must not raise (PyMongo dedupes on
    the driver side)."""
    db = _RecordingDB()
    _run(ensure_tenant_ai_rules_indexes(db))
    _run(ensure_tenant_ai_rules_indexes(db))
    # Two invocations recorded — the driver treats each as a no-op
    # via matching index names.
    assert len(db.tenant_ai_rules.calls) == 2
