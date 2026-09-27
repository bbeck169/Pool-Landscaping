"""AIHUB-A · Feb-2026 — registry shape tests.

Locks the 18-employee spec at import time:

* Exactly 18 rows.
* All required fields non-empty.
* ``human_name`` values unique.
* ``avatar_slug`` values unique.
* ``org_department`` non-empty and in the vocabulary.
* ``hierarchy_order`` values are the sequence 1..18 (spec-locked).
* Every non-executive row has a ``manager_key`` that resolves.
* Only ``marco_executive`` + ``nova`` carry ``orchestrator=True``.

These are pure source-lints — no live DB required.
"""
from __future__ import annotations

import pytest

from services.ai_hub.employee_registry import (
    ALLOWED_DEPARTMENTS,
    DEFAULT_ACTION_LIMIT_MONTHLY,
    DEPT_EXECUTIVE, DEPT_MARKETING, DEPT_OPERATIONS,
    EMPLOYEES, EmployeeSpec, get_spec, registry_size, to_seed_doc,
)


# ═══════════════════════════════════════════════════════════════════
# Cardinality + shape
# ═══════════════════════════════════════════════════════════════════
def test_registry_ships_exactly_18_employees():
    assert registry_size() == 18
    assert len(EMPLOYEES) == 18


def test_every_spec_is_a_frozen_dataclass():
    for e in EMPLOYEES:
        assert isinstance(e, EmployeeSpec)
        with pytest.raises(Exception):
            # Frozen — assignment raises.
            e.human_name = "hacker"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════
# Required-field completeness
# ═══════════════════════════════════════════════════════════════════
def test_every_spec_has_required_fields_non_empty():
    for e in EMPLOYEES:
        assert e.key and isinstance(e.key, str)
        assert e.human_name and isinstance(e.human_name, str)
        assert e.codename and e.codename.isupper()
        assert e.role_title and isinstance(e.role_title, str)
        assert e.org_department in ALLOWED_DEPARTMENTS
        assert e.avatar_slug == e.key
        assert e.avatar_url.startswith("http")


def test_default_authorization_is_off_for_every_spec():
    """Fail-safe default — spec + brief demand every employee
    lands unauthorized on migration; admin flips one by one."""
    for e in EMPLOYEES:
        assert e.default_authorized_for_public_use is False


def test_default_action_limit_is_60000():
    assert DEFAULT_ACTION_LIMIT_MONTHLY == 60000
    for e in EMPLOYEES:
        assert e.default_action_limit_monthly == 60000


# ═══════════════════════════════════════════════════════════════════
# Uniqueness invariants
# ═══════════════════════════════════════════════════════════════════
def test_keys_are_unique():
    keys = [e.key for e in EMPLOYEES]
    assert len(set(keys)) == len(keys)


def test_human_names_are_unique():
    """No two humans share a first name — the FE roster row
    label is the human name, and dup names would be indistinguishable."""
    names = [e.human_name for e in EMPLOYEES]
    assert len(set(names)) == len(names), (
        f"duplicate human_name in registry: {names}"
    )


def test_avatar_slugs_are_unique():
    """Slug clash would corrupt the CDN URL map."""
    slugs = [e.avatar_slug for e in EMPLOYEES]
    assert len(set(slugs)) == len(slugs)


def test_codenames_are_unique():
    """Codename doubles as the LLM's routing symbol — dup breaks
    MARCO's delegate_task."""
    codes = [e.codename for e in EMPLOYEES]
    assert len(set(codes)) == len(codes)


# ═══════════════════════════════════════════════════════════════════
# Hierarchy invariants
# ═══════════════════════════════════════════════════════════════════
def test_hierarchy_orders_are_exact_sequence_1_to_18():
    orders = sorted(e.hierarchy_order for e in EMPLOYEES)
    assert orders == list(range(1, 19)), (
        f"hierarchy_order sequence broken: {orders}"
    )


def test_every_non_executive_has_a_manager_that_resolves():
    keys = {e.key for e in EMPLOYEES}
    for e in EMPLOYEES:
        if e.org_department == DEPT_EXECUTIVE:
            assert e.manager_key is None, (
                f"{e.key} is executive but carries manager_key "
                f"{e.manager_key!r}"
            )
        else:
            assert e.manager_key in keys, (
                f"{e.key} manager_key {e.manager_key!r} does not "
                f"resolve to any registry entry"
            )


# ═══════════════════════════════════════════════════════════════════
# Department cardinality per spec v5
# ═══════════════════════════════════════════════════════════════════
def test_department_split_matches_spec_v5():
    by_dept: dict = {}
    for e in EMPLOYEES:
        by_dept.setdefault(e.org_department, []).append(e.key)
    assert len(by_dept[DEPT_EXECUTIVE]) == 2, by_dept[DEPT_EXECUTIVE]
    assert len(by_dept[DEPT_MARKETING]) == 13, by_dept[DEPT_MARKETING]
    assert len(by_dept[DEPT_OPERATIONS]) == 3, by_dept[DEPT_OPERATIONS]


# ═══════════════════════════════════════════════════════════════════
# Orchestrator invariant — MARCO + NOVA only
# ═══════════════════════════════════════════════════════════════════
def test_only_marco_and_nova_carry_orchestrator():
    orchestrators = {e.key for e in EMPLOYEES if e.orchestrator}
    assert orchestrators == {"marco_executive", "nova"}, (
        f"unexpected orchestrator set: {orchestrators}"
    )


# ═══════════════════════════════════════════════════════════════════
# Helper — get_spec + to_seed_doc
# ═══════════════════════════════════════════════════════════════════
def test_get_spec_resolves_known_key_and_none_for_unknown():
    e = get_spec("nova")
    assert e is not None and e.human_name == "Sarah"
    assert get_spec("no_such_key") is None


def test_to_seed_doc_produces_dict_shape_with_new_fields():
    doc = to_seed_doc(get_spec("nova"))
    for required in (
        "key", "name", "human_name", "codename", "role", "role_title",
        "org_department", "hierarchy_order", "manager_key",
        "orchestrator", "avatar_url", "avatar_slug", "system_prompt",
        "audience", "authorized_for_public_use", "action_limit_monthly",
        "is_legacy",
    ):
        assert required in doc, f"missing {required} in seed doc"
    assert doc["authorized_for_public_use"] is False
    assert doc["action_limit_monthly"] == 60000
    assert doc["is_legacy"] is False
    assert doc["audience"] == "admin"
