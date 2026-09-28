"""MTH-C · Feb-2026 — shared test helpers.

Extends the MTH-A FakeDB with the collections MTH-C reads/writes
(``ai_action_audit``, ``ai_comms_deferred_queue``, ``ai_escalations``,
``ai_employees``, ``ai_employee_actions``, ``tenants``, ``users``,
``sms_messages``, ``sms_inbound``) plus a monkeypatch fixture that
swaps ``config.db`` module-wide.  Also imports the MTH-A ``run``
helper so every new test file can drive coroutines the same way.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from tests._mth_a_helpers import FakeDB as _MTHAFakeDB, _Coll, run  # noqa: F401


class MTHCFakeDB(_MTHAFakeDB):
    def __init__(self):
        super().__init__()
        self.ai_employees = _Coll("ai_employees")
        self.ai_employee_actions = _Coll("ai_employee_actions")
        self.ai_action_audit = _Coll("ai_action_audit")
        self.ai_comms_deferred_queue = _Coll("ai_comms_deferred_queue")
        self.ai_escalations = _Coll("ai_escalations")
        self.tenants = _Coll("tenants")
        self.users = _Coll("users")
        self.sms_messages = _Coll("sms_messages")
        self.sms_inbound = _Coll("sms_inbound")
        # Additional Mongo-style access for the MTH-C code paths
        # that use ``db[COLLECTION_NAME]`` string subscripting.
        self._by_name = {
            "tenant_ai_rules": self.tenant_ai_rules,
            "tenant_ai_rules_revisions": self.tenant_ai_rules_revisions,
            "platform_ai_rule_defaults": self.platform_ai_rule_defaults,
            "ai_employees": self.ai_employees,
            "ai_employee_actions": self.ai_employee_actions,
            "ai_action_audit": self.ai_action_audit,
            "ai_comms_deferred_queue": self.ai_comms_deferred_queue,
            "ai_escalations": self.ai_escalations,
            "tenants": self.tenants,
            "users": self.users,
            "sms_messages": self.sms_messages,
            "sms_inbound": self.sms_inbound,
        }

    def __getitem__(self, name: str) -> _Coll:
        if name not in self._by_name:
            self._by_name[name] = _Coll(name)
            setattr(self, name, self._by_name[name])
        return self._by_name[name]

    def reset(self) -> None:                                       # noqa: D401
        for c in self._by_name.values():
            c.rows.clear()


@pytest.fixture
def mth_c_db(monkeypatch):
    """Swap ``config.db`` + ``store.db`` with an isolated FakeDB.

    Also clears the MTH-A tenant-rules cache so state doesn't leak
    across tests in the same module.
    """
    import config
    from services.tenant_ai_rules import cache, store
    fake = MTHCFakeDB()
    monkeypatch.setattr(config, "db", fake, raising=False)
    monkeypatch.setattr(store, "db", fake, raising=False)
    cache.invalidate_all()
    return fake


def seed_rules_doc(fake, tenant_id: str, rules: Dict[str, Any],
                     master: bool = True) -> None:
    """Seed a tenant_ai_rules doc directly (bypasses ``save_category``
    so tests can install exact rule shapes without triggering
    revision + audit side-effects)."""
    fake.tenant_ai_rules.rows.append({
        "id": f"rules-{tenant_id}",
        "tenant_id": tenant_id,
        "revision_number": 1,
        "rules": rules,
        "override_map": {},
        "master_ai_send_live_comms": master,
        "last_updated_at": "2026-02-05T10:00:00+00:00",
        "last_updated_by_id": "system",
        "last_updated_by_name": "system",
        "last_update_reason": "test seed",
    })


def seed_platform_defaults(fake, rules: Dict[str, Any]) -> None:
    fake.platform_ai_rule_defaults.rows.append({
        "id": "platform-defaults",
        "rules": rules,
        "revision_number": 1,
        "last_updated_at": "2026-02-05T10:00:00+00:00",
        "last_updated_by_id": "system",
        "last_updated_by_name": "system",
        "last_update_reason": "test seed",
    })
